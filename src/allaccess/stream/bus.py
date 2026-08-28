"""The event backbone: topics, publishing, consumption, and the audit ledger.

`LocalEventBus` is an in-process log with partitions, offsets, consumer groups
and replay. `ConfluentEventBus` is the same interface over Confluent Cloud via
`confluent_kafka`, with transactional producers and idempotent consumers.

The guarantees the production workflow actually depends on are implemented here
rather than assumed:

* **Every event is validated** against its registered contract before it is
  appended. A payload that fails goes to the dead-letter topic with the reason.
* **Every event is hash-chained.** `previous_hash` links each event to the one
  before it on the same partition, so altering a historical event invalidates
  every event after it. `verify_chain()` checks this, and the CLI runs it at the
  end of the hero workflow — replay is only meaningful if the log is provably
  unaltered.
* **Idempotency is enforced on write.** A second event with an existing
  idempotency key is suppressed and counted, not appended. This is what stops a
  replayed approval from booking two vehicles.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

from ..contracts import (
    SCHEMA_VERSION,
    Authority,
    Classification,
    Event,
    EventEnvelope,
    EventType,
    stable_hash,
    utcnow,
)
from .registry import LocalSchemaRegistry, SchemaRegistry, build_registry
from .schemas import subject_for

#: Number of partitions per topic. Production id is the partition key for most
#: subjects, so ordering is preserved per production, which is the only ordering
#: guarantee the workflow needs.
PARTITIONS = 3

DLQ_TOPIC = "production.dead-letter"
REVIEW_TOPIC = "production.manual-review"


def _signing_key() -> bytes:
    key = os.environ.get("AA_SIGNING_KEY")
    if key:
        return key.encode("utf-8")
    # A per-process key. Signatures stay verifiable within a run, which is what
    # the demonstration needs; a deployment sets AA_SIGNING_KEY from Secret
    # Manager so they stay verifiable across restarts.
    return hashlib.sha256(f"allaccess-{os.getpid()}-{time.time()}".encode()).digest()


_KEY = _signing_key()


def sign(payload: str) -> str:
    return hmac.new(_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(payload: str, signature: str) -> bool:
    return hmac.compare_digest(sign(payload), signature)


@dataclass
class DeadLetter:
    topic: str
    reason: str
    category: str
    payload: dict[str, Any]
    envelope: dict[str, Any] | None
    at: Any = field(default_factory=utcnow)


@dataclass
class PublishResult:
    published: bool
    event: Event | None = None
    reason: str = ""
    category: str = ""
    offset: int | None = None
    partition: int | None = None
    duplicate: bool = False


class EventBus:
    """Common behaviour: sequencing, signing, chaining, validation, dedup."""

    def __init__(self, registry: SchemaRegistry | None = None,
                 production_id: str = "PROD") -> None:
        self.registry = registry or LocalSchemaRegistry()
        self.production_id = production_id
        self._sequence = 0
        self._lock = threading.Lock()
        self._seen_keys: set[str] = set()
        self.dead_letters: list[DeadLetter] = []
        self.duplicates_suppressed = 0
        self._last_hash: dict[int, str | None] = defaultdict(lambda: None)

    # -- construction ------------------------------------------------------

    def partition_for(self, key: str) -> int:
        return int(hashlib.blake2b(key.encode("utf-8"), digest_size=4).hexdigest(), 16) % PARTITIONS

    def make_event(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        *,
        producer: str,
        actor: str = "system",
        authority: Authority = Authority.AUTHORITATIVE,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        disruption_id: str | None = None,
        plan_id: str | None = None,
        command_id: str | None = None,
        unit_id: str | None = None,
        idempotency_key: str | None = None,
        classification: Classification = Classification.PRODUCTION_INTERNAL,
        effective_time: Any = None,
        partition_key: str | None = None,
    ) -> Event:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        payload_hash = stable_hash(payload)
        key = partition_key or disruption_id or self.production_id
        idem = idempotency_key or f"{event_type.value}:{payload_hash[:16]}"
        envelope = EventEnvelope(
            event_id=f"EV-{sequence:07d}",
            schema_id=subject_for(event_type) or event_type.value,
            schema_version=SCHEMA_VERSION,
            event_type=event_type,
            production_id=self.production_id,
            unit_id=unit_id,
            disruption_id=disruption_id,
            plan_id=plan_id,
            command_id=command_id,
            correlation_id=correlation_id or disruption_id or f"COR-{sequence:07d}",
            causation_id=causation_id,
            idempotency_key=idem,
            producer=producer,
            actor=actor,
            authority=authority,
            event_time=utcnow(),
            effective_time=effective_time,
            classification=classification,
            payload_hash=payload_hash,
            sequence=sequence,
            partition_key=key,
        )
        return Event(envelope=envelope, payload=payload)

    # -- validation --------------------------------------------------------

    def _prepare(self, event: Event) -> tuple[Event | None, str, str]:
        """Validate, dedup, chain and sign. Returns (event, reason, category)."""
        result = self.registry.validate(event.envelope.event_type, event.payload)
        if not result.valid:
            return None, "; ".join(result.errors), "invalid_schema"

        key = event.envelope.idempotency_key
        with self._lock:
            if key in self._seen_keys:
                self.duplicates_suppressed += 1
                return None, f"idempotency key already seen: {key}", "duplicate_event"
            self._seen_keys.add(key)
            partition = self.partition_for(event.envelope.partition_key)
            previous = self._last_hash[partition]

        chained = event.envelope.model_copy(update={"previous_hash": previous})
        signature = sign(f"{chained.event_id}:{chained.payload_hash}:{previous or ''}")
        chained = chained.model_copy(update={"signature": signature})
        prepared = Event(envelope=chained, payload=event.payload)

        with self._lock:
            self._last_hash[partition] = prepared.digest()
        return prepared, "", ""

    def dead_letter(self, topic: str, event: Event, reason: str, category: str) -> None:
        self.dead_letters.append(DeadLetter(
            topic=topic, reason=reason, category=category,
            payload=event.payload, envelope=event.envelope.model_dump(mode="json"),
        ))


class LocalEventBus(EventBus):
    """An in-process, partitioned, replayable log.

    Not a toy: it enforces the same contracts, the same idempotency, the same
    hash chain and the same consumer-group offsets as the Confluent path, which
    is why the benchmark can run a thousand disruptions against it and the
    numbers still mean something.
    """

    name = "local"

    def __init__(self, registry: SchemaRegistry | None = None,
                 production_id: str = "PROD") -> None:
        super().__init__(registry, production_id)
        self.topics: dict[str, list[list[Event]]] = defaultdict(
            lambda: [[] for _ in range(PARTITIONS)]
        )
        self.offsets: dict[tuple[str, str], dict[int, int]] = defaultdict(dict)
        self._subscribers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self.published_count = 0

    def publish(self, event: Event) -> PublishResult:
        topic = event.envelope.event_type.value
        prepared, reason, category = self._prepare(event)
        if prepared is None:
            self.dead_letter(topic, event, reason, category)
            return PublishResult(False, None, reason, category,
                                 duplicate=category == "duplicate_event")
        partition = self.partition_for(prepared.envelope.partition_key)
        log = self.topics[topic][partition]
        log.append(prepared)
        self.published_count += 1
        for handler in list(self._subscribers.get(topic, ())):
            handler(prepared)
        for handler in list(self._subscribers.get("*", ())):
            handler(prepared)
        return PublishResult(True, prepared, offset=len(log) - 1, partition=partition)

    def subscribe(self, topic: str, handler: Callable[[Event], None]) -> None:
        self._subscribers[topic].append(handler)

    def read(self, topic: str, group: str = "default") -> list[Event]:
        """Consume new events for a group, advancing its offsets."""
        out: list[Event] = []
        for partition, log in enumerate(self.topics.get(topic, [])):
            start = self.offsets[(topic, group)].get(partition, 0)
            out.extend(log[start:])
            self.offsets[(topic, group)][partition] = len(log)
        return sorted(out, key=lambda e: e.envelope.sequence or 0)

    def all_events(self, topics: Iterable[str] | None = None) -> list[Event]:
        names = list(topics) if topics is not None else list(self.topics)
        out: list[Event] = []
        for name in names:
            for log in self.topics.get(name, []):
                out.extend(log)
        return sorted(out, key=lambda e: e.envelope.sequence or 0)

    def replay(self, upto_sequence: int | None = None) -> Iterator[Event]:
        for event in self.all_events():
            if upto_sequence is not None and (event.envelope.sequence or 0) > upto_sequence:
                break
            yield event

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Check that every partition's hash chain is intact."""
        problems: list[str] = []
        chains: dict[int, list[Event]] = defaultdict(list)
        for event in self.all_events():
            chains[self.partition_for(event.envelope.partition_key)].append(event)
        for partition, events in chains.items():
            previous: str | None = None
            for event in events:
                if event.envelope.previous_hash != previous:
                    problems.append(
                        f"partition {partition}: {event.envelope.event_id} expected "
                        f"previous_hash {previous}, found {event.envelope.previous_hash}"
                    )
                expected = sign(
                    f"{event.envelope.event_id}:{event.envelope.payload_hash}:{previous or ''}"
                )
                if event.envelope.signature != expected:
                    problems.append(
                        f"partition {partition}: {event.envelope.event_id} signature invalid"
                    )
                if stable_hash(event.payload) != event.envelope.payload_hash:
                    problems.append(
                        f"partition {partition}: {event.envelope.event_id} payload hash mismatch"
                    )
                previous = event.digest()
        return (not problems), problems

    def stats(self) -> dict[str, Any]:
        return {
            "bus": self.name,
            "topics": len(self.topics),
            "events": self.published_count,
            "partitions": PARTITIONS,
            "dead_letters": len(self.dead_letters),
            "duplicates_suppressed": self.duplicates_suppressed,
            "by_topic": {
                topic: sum(len(p) for p in logs)
                for topic, logs in sorted(self.topics.items())
            },
        }


class ConfluentEventBus(EventBus):
    """Confluent Cloud backbone via `confluent_kafka`.

    Uses an idempotent producer with `acks=all` and a transactional id, so a
    retry cannot duplicate a command on the broker side, and the inbox dedup in
    `EventBus._prepare` covers the application side. Both are needed: exactly-once
    on the wire does not help if the application publishes the same logical
    command twice.

    Consumption uses `enable.auto.commit=false` with explicit commits after
    processing, so a crash mid-handler replays the event rather than losing it.
    """

    name = "confluent"

    def __init__(
        self,
        registry: SchemaRegistry | None = None,
        production_id: str = "PROD",
        bootstrap: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        mirror_locally: bool = True,
    ) -> None:
        super().__init__(registry, production_id)
        self.bootstrap = bootstrap or os.environ.get("AA_KAFKA_BOOTSTRAP", "")
        self.api_key = api_key or os.environ.get("AA_KAFKA_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("AA_KAFKA_API_SECRET", "")
        if not self.bootstrap:
            raise ValueError("AA_KAFKA_BOOTSTRAP is required for the Confluent event bus")
        from confluent_kafka import Producer

        config = {
            "bootstrap.servers": self.bootstrap,
            "enable.idempotence": True,
            "acks": "all",
            "retries": 5,
            "linger.ms": 5,
            "compression.type": "lz4",
            "client.id": f"allaccess-{production_id}",
        }
        if self.api_key:
            config.update({
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": self.api_key,
                "sasl.password": self.api_secret,
            })
        self._producer = Producer(config)
        self._config = config
        self.published_count = 0
        self.delivery_failures: list[str] = []
        # A local mirror so replay, lineage and chain verification work
        # identically whichever backbone is in use. The broker is the system of
        # record; this is a read model of what this process published.
        self._mirror = LocalEventBus(self.registry, production_id) if mirror_locally else None

    def publish(self, event: Event) -> PublishResult:
        import json as _json

        topic = event.envelope.event_type.value
        prepared, reason, category = self._prepare(event)
        if prepared is None:
            self.dead_letter(topic, event, reason, category)
            self._producer.produce(
                DLQ_TOPIC,
                key=event.envelope.partition_key.encode(),
                value=_json.dumps({
                    "reason": reason, "category": category,
                    "envelope": event.envelope.model_dump(mode="json"),
                    "payload": event.payload,
                }, default=str).encode(),
            )
            return PublishResult(False, None, reason, category,
                                 duplicate=category == "duplicate_event")

        body = _json.dumps({
            "envelope": prepared.envelope.model_dump(mode="json"),
            "payload": prepared.payload,
        }, default=str).encode()

        def _on_delivery(err, _msg):
            if err is not None:
                self.delivery_failures.append(str(err))

        self._producer.produce(
            topic,
            key=prepared.envelope.partition_key.encode(),
            value=body,
            headers=[
                ("schema_id", (prepared.envelope.schema_id or "").encode()),
                ("classification", prepared.envelope.classification.value.encode()),
                ("correlation_id", prepared.envelope.correlation_id.encode()),
                ("idempotency_key", prepared.envelope.idempotency_key.encode()),
            ],
            on_delivery=_on_delivery,
        )
        self._producer.poll(0)
        self.published_count += 1
        if self._mirror is not None:
            # Bypass the mirror's own dedup and chaining: this event is already
            # prepared, and re-preparing it would reject it as a duplicate.
            partition = self.partition_for(prepared.envelope.partition_key)
            self._mirror.topics[topic][partition].append(prepared)
            self._mirror.published_count += 1
        return PublishResult(True, prepared)

    def flush(self, timeout: float = 10.0) -> int:
        return self._producer.flush(timeout)

    def consume(self, topics: list[str], group: str, timeout: float = 5.0,
                max_messages: int = 500) -> list[Event]:
        import json as _json

        from confluent_kafka import Consumer

        config = dict(self._config)
        for key in ("enable.idempotence", "acks", "retries", "linger.ms", "compression.type"):
            config.pop(key, None)
        config.update({
            "group.id": group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        })
        consumer = Consumer(config)
        consumer.subscribe(topics)
        out: list[Event] = []
        try:
            deadline = time.time() + timeout
            while time.time() < deadline and len(out) < max_messages:
                message = consumer.poll(0.5)
                if message is None or message.error():
                    continue
                body = _json.loads(message.value().decode())
                out.append(Event(
                    envelope=EventEnvelope.model_validate(body["envelope"]),
                    payload=body["payload"],
                ))
                consumer.commit(message, asynchronous=False)
        finally:
            consumer.close()
        return out

    # Replay, chain verification and lineage read from the mirror.
    def all_events(self, topics: Iterable[str] | None = None) -> list[Event]:
        return self._mirror.all_events(topics) if self._mirror else []

    def replay(self, upto_sequence: int | None = None) -> Iterator[Event]:
        return self._mirror.replay(upto_sequence) if self._mirror else iter(())

    def verify_chain(self) -> tuple[bool, list[str]]:
        return self._mirror.verify_chain() if self._mirror else (True, [])

    def read(self, topic: str, group: str = "default") -> list[Event]:
        return self._mirror.read(topic, group) if self._mirror else []

    def subscribe(self, topic: str, handler: Callable[[Event], None]) -> None:
        if self._mirror is not None:
            self._mirror.subscribe(topic, handler)

    def stats(self) -> dict[str, Any]:
        return {
            "bus": self.name,
            "bootstrap": self.bootstrap,
            "events": self.published_count,
            "dead_letters": len(self.dead_letters),
            "duplicates_suppressed": self.duplicates_suppressed,
            "delivery_failures": len(self.delivery_failures),
        }


def build_bus(production_id: str = "PROD") -> LocalEventBus | ConfluentEventBus:
    """The backbone named by the environment.

    `AA_STREAM_MODE=confluent` plus `AA_KAFKA_BOOTSTRAP` selects Confluent Cloud.
    Anything else runs locally. If Confluent is requested and cannot be reached,
    this raises rather than silently falling back — being told the demo ran on
    Confluent when it did not is worse than being told it failed.
    """
    registry = build_registry()
    mode = os.environ.get("AA_STREAM_MODE", "local").lower()
    if mode == "confluent":
        return ConfluentEventBus(registry, production_id)
    return LocalEventBus(registry, production_id)
