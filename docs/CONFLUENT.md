# The event backbone

Confluent is where every consequential fact in this system lives. Not a message
queue bolted to the side of a database — the event log *is* the record, the twin
is a fold over it, and `verify_replay()` asserts on every benchmark scenario that
rebuilding from the log reproduces live state exactly.

Implemented in `src/allaccess/stream/`. 23 data contracts, 49 event types,
six domains.

---

## 1. Two implementations, one interface

| | `LocalEventBus` | `ConfluentEventBus` |
|---|---|---|
| Transport | in-process partitioned log | Confluent Cloud via `confluent_kafka` |
| Schema Registry | `LocalSchemaRegistry` over `schemas.py` | `ConfluentSchemaRegistry` over the REST API |
| Validation | same code | same code |
| Hash chain | same code | same code |
| Idempotency | same code | same code |

Selected by `AA_EVENT_BACKBONE`; `local` is the default.

The local bus is not a mock. It performs the same contract validation, the same
compatibility enforcement, the same dead-lettering, the same idempotency
suppression and the same hash chaining, because those behaviours are what the
workflow depends on and testing against a version that skips them would prove
nothing. That is what makes the offline benchmark an honest measurement rather
than a demonstration of a stub.

**What the local bus does not give you:** partition rebalancing, consumer-group
coordination across processes, broker failure, network partition, or Stream
Lineage as a hosted service. Those are properties of the cluster, not of this
code, and no number in `BENCHMARK.md` claims them.

---

## 2. Event domains

| Domain | Examples | Classification |
|---|---|---|
| Source | `weather.alerted`, `cast.changed`, `location.changed`, `access_service.changed` | production internal / personal |
| State | `twin.entity.updated`, `schedule.state.changed` | production internal |
| Assessment | `scope.assessed`, `safety.assessed`, `access.assessed` | operational requirement |
| Decision | `plan.generated`, `plan.rejected`, `plan.approved` | production internal |
| Execution | `command.issued`, `command.completed`, `acknowledgment.received` | production internal |
| Audit and learning | `verification.completed`, `disruption.closed` | production internal |

Full catalogue: `GET /api/streams`, or `governance.catalog()`. It is generated
from the contract registry rather than maintained by hand, so it cannot describe
a topic that does not exist or miss one that does.

---

## 3. Data contracts

Each subject in `schemas.py` declares a JSON Schema, an owner role, a
compatibility mode (`BACKWARD` throughout), a data classification, and **domain
rules beyond structural typing**.

The rules are the part that earns its place. A structurally valid payload can
still be rejected: an approval event whose `constraint_hash` does not match the
active constraint set, a command whose `plan_version` is stale, a source event
whose `effective_time` is in the future. `validate_rules()` evaluates these
against the payload, and `Publisher` calls it **before** the event reaches a
topic.

An event that fails goes to the dead-letter topic with the reason attached. In
the 1,000-scenario run, 28 events were dead-lettered — every one of them a
deliberately malformed event from the `schema_incompatibility` fault injection.

Compatibility is checkable without a session: `tools/mcp_schema_registry.py`
exposes `check_compatibility` over MCP, which is what IBM Bob is given so that a
proposed contract change is assessed against the registered schema rather than
guessed at.

---

## 4. Guarantees, and where they are enforced

### Hash chain

`previous_hash` links each event to its predecessor on the same partition.
Altering a historical event invalidates every event after it. `verify_chain()`
checks it, the CLI runs it at the end of the hero workflow, and the benchmark
records `hash_chain_intact_rate` — **1.000 across 1,000 scenarios**.

### Idempotency on write

A second event carrying an existing idempotency key is suppressed and counted,
not appended. This is what stops a replayed approval from booking two vehicles.
Measured as `duplicates_suppressed`, and exercised deliberately by the
`duplicate_event` fault: **16 of 16 handled**.

### Outbox and inbox

A command is written to the outbox in the same step that records the decision,
then published — a crash between deciding and publishing leaves the command in
the outbox to be republished, so a decision cannot be silently lost. On the
receiving side, a target system records the idempotency keys it has processed
and acknowledges a replayed command again without *applying* it again.

### Plan-version checks

Every command carries the plan version it belongs to. A target holding a newer
version rejects the older command as stale rather than applying it out of order.

### Saga dependencies

A briefing command that depends on the location being confirmed is not issued
until the confirmation completes. Issuing everything at once and hoping is how a
crew gets briefed on a location the production has not yet secured.

---

## 5. Materialised state (Flink)

Every view in `stream/views.py` is a fold over the event log — it consumes events
in sequence and maintains current state. The same logic exists twice:

| View | What it holds |
|---|---|
| `disruption_state` | current state of every open disruption |
| `open_commands` | commands issued and not yet completed |
| `unacknowledged` | messages requiring acknowledgment that have none |
| `operational_kpis` | delay, overtime, idle and communication counts |
| `access_at_risk` | approved arrangements whose mechanism is currently unavailable |

- **In process**, as `MaterializedViews`. This is what the CLI, the API and the
  benchmark read.
- **On Confluent Cloud for Apache Flink**, as the SQL in `FLINK_STATEMENTS`, kept
  at the foot of the same module rather than in a separate directory so the two
  cannot drift apart unnoticed. `tests/test_stream.py` asserts every view has a
  committed statement.

The Python is the testable artifact and the SQL is the deployable one. Keeping
both honest is why `verify_replay()` matters: a view that cannot be rebuilt from
the log is not a view, it is a second source of truth.

**Event time and watermarks.** Events carry `effective_time` — when the change
takes effect in the world — separately from `event_time`, when it was emitted.
Views that care about ordering use `effective_time` and hold a watermark, so an
update that arrives late is applied in the right order rather than dropped.
`late_events` counts them, which is what makes the `late_event` fault injection
checkable: the coordinator must refuse to act on a stale report *and* the view
must count it.

**Not run on Confluent Cloud for Apache Flink.** The SQL is committed and
structurally checked; no statement has been submitted to a hosted Flink cluster.

---

## 6. Lineage

`governance.trace()` walks `causation_id` backwards from any event to the source
event that caused it, and forwards to everything it caused. In the hero
scenario that is the path from the weather alert through the assessments, the
plan, the approval, the commands and the acknowledgments — **derived from the
log**, not drawn separately as a diagram and hoped to still be accurate.

Mean lineage size across the corpus: 51.9 nodes per disruption.

Visible at `GET /api/replay` and in the Decision Replay view.

---

## 7. Replay

`replay_to(n)` rebuilds the materialised views at any sequence number.
`verify_replay()` asserts a full replay reproduces live state exactly.

`replay_identical_rate` is **1.000 across 1,000 scenarios**. This is the property
that makes the audit trail worth having: a reviewer asking "why did they choose
that?" gets the state the decision was made against, not today's state with
hindsight applied.

The twin's bitemporality is the other half. Every fact carries when it is true in
the world *and* when the system learned it, so `as_of(when, known_at)` returns
what the production believed at a moment, and facts recorded after that instant
are invisible however true they turned out to be.

---

## 8. Running against Confluent Cloud

```bash
export AA_EVENT_BACKBONE=confluent
export AA_CONFLUENT_BOOTSTRAP=pkc-xxxxx.region.provider.confluent.cloud:9092
export AA_CONFLUENT_API_KEY=...        # cluster key
export AA_CONFLUENT_API_SECRET=...
export AA_SCHEMA_REGISTRY_URL=https://psrc-xxxxx.region.provider.confluent.cloud
export AA_SCHEMA_REGISTRY_KEY=...
export AA_SCHEMA_REGISTRY_SECRET=...

pip install -e ".[confluent]"
python -m allaccess.cli hero
```

`ConfluentSchemaRegistry.register_all()` registers all 23 subjects and sets their
compatibility modes on first run. `GET /api/about` reports which backbone and
which registry are live, so a viewer never has to guess which one they are
looking at.

## 9. Which backbone is live

`AA_EVENT_BACKBONE` selects it, and `GET /api/about` reports it, so a viewer
never has to guess. The two implementations sit behind one interface and are
exercised by the same tests: the local bus performs the same schema validation,
the same hash chaining, the same idempotency suppression and the same
dead-lettering, which is what makes a measurement taken on one meaningful for
the other. `environment` in `bench/results/summary.json` records which backbone
produced the committed figures.

`governance.trace()` is this system's own lineage over its own log, computed
from `causation_id` — independent of any hosted lineage product, and available
in the offline demo.
