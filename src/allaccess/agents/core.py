"""The agent substrate: typed contracts, the reasoning plane, and abstention.

Every agent in this system takes a typed input and returns a typed `Finding`. No
agent returns prose, and no agent's output can become authoritative without
passing the same validation as any other event on the stream.

**Two reasoning planes.** `OfflineReasoner` is deterministic: it produces the
narrative fields of a finding from templates over the evidence the deterministic
services computed. `GeminiReasoner` calls Gemini on Vertex AI for the same fields.
Both are constrained to the same job — *interpreting and explaining evidence* —
and neither is ever asked whether something is feasible. That question has one
answer, and the solver owns it.

The reason the offline plane exists is not convenience. It is that the benchmark
must be reproducible and the judging must not depend on a model endpoint being
reachable. Every number in `docs/BENCHMARK.md` comes from the offline plane; the
Gemini plane is exercised by `--reasoning gemini` and its behaviour is compared
in `docs/BENCHMARK.md` §7 rather than assumed identical.

**Abstention is a first-class outcome.** An agent that cannot support a claim
returns `FindingStatus.ABSTAINED`, and the contract rules on the finding subject
refuse a blocking finding with no evidence. The benchmark measures how often
agents correctly abstain, because an agent that always has an opinion is an agent
whose opinions are worthless.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..contracts import (
    Classification,
    ConstraintDomain,
    Finding,
    FindingStatus,
    Role,
    stable_hash,
    utcnow,
)


@dataclass
class ReasoningCall:
    """One call to the reasoning plane. Recorded for the observability view."""

    agent: str
    purpose: str
    plane: str
    prompt_chars: int
    response_chars: int
    latency_ms: float
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    #: Identifiers or quantities the response carried that the facts did not
    #: support. Non-empty means the response was discarded.
    rejected_claims: tuple[str, ...] = ()


class Reasoner(Protocol):
    plane: str

    def narrate(self, agent: str, purpose: str, facts: dict[str, Any],
                template: str) -> str: ...
    def calls(self) -> list[ReasoningCall]: ...


class OfflineReasoner:
    """Deterministic narration from structured facts.

    Renders `template` against `facts`. Same input, same output, every time —
    which is what makes a thousand-scenario benchmark mean something.
    """

    plane = "offline"

    def __init__(self) -> None:
        self._calls: list[ReasoningCall] = []

    def narrate(self, agent: str, purpose: str, facts: dict[str, Any],
                template: str) -> str:
        started = time.perf_counter()
        try:
            text = template.format(**facts)
        except (KeyError, IndexError, ValueError) as exc:
            # A template referring to a fact that is not there is a bug in the
            # agent, not something to paper over with a vague sentence.
            text = f"[{agent}: narration unavailable ({exc})]"
        elapsed = (time.perf_counter() - started) * 1000.0
        self._calls.append(ReasoningCall(
            agent=agent, purpose=purpose, plane=self.plane,
            prompt_chars=len(template), response_chars=len(text), latency_ms=elapsed,
        ))
        return text

    def calls(self) -> list[ReasoningCall]:
        return list(self._calls)


#: Identifier shapes this system uses. Anything matching one of these in a
#: model's output is checkable against the facts it was given, which is what
#: makes grounding enforceable rather than requested.
_IDENTIFIER = re.compile(
    r"\b(?:C|ACC|SC|PLAN|LOC|VEH|BOOK|PERM|CAST|CREW|DEPT|EV|DISR)-[A-Z0-9-]+\b"
)
#: Numbers with operational meaning. Bare small integers ("two units") are not
#: worth policing; a measurement, a time, a cost or a percentage is.
_QUANTITY = re.compile(r"\b\d[\d,]*\.?\d*\s*(?:mm|cm|m|km|kph|kg|%|min|minutes|hours)\b|"
                       r"\b\d{1,2}:\d{2}\b|\b\d{4,}\b")


def _facts_corpus(facts: dict[str, Any]) -> str:
    """Everything the model was told, flattened for containment checks."""
    import json

    return json.dumps(facts, default=str).lower()


def ungrounded_claims(text: str, facts: dict[str, Any]) -> tuple[str, ...]:
    """Identifiers and quantities in `text` that do not appear in `facts`.

    This is the check that lets a language model into a production decision
    system at all. The model is given facts a deterministic layer has already
    established and asked to express them; this reads what came back and finds
    anything it could not have got from the input. A constraint id nobody
    mentioned, a threshold in millimetres that appears nowhere, a call time an
    hour off — each is a specific, mechanical thing to look for, and each is the
    kind of detail a fluent paragraph carries convincingly.

    It does not check that the prose is *true*, which no regular expression can.
    It checks that every checkable token is one the model was handed. When it
    finds one, `narrate()` discards the response and uses the deterministic
    template instead, and records that it did.
    """
    corpus = _facts_corpus(facts)
    unsupported: list[str] = []

    # Identifiers are matched whole and nothing else will do. Comparing them
    # loosely is how `C-XXX-001` passes because `ACC-001` was in the facts and
    # the digits happen to agree — an invented constraint id waved through on
    # the strength of a shared suffix.
    for match in _IDENTIFIER.findall(text):
        if match.strip().lower() not in corpus:
            unsupported.append(match.strip())

    # A quantity is supported if its digits appear anywhere: "45 mm" and
    # "threshold_mm: 45" are one fact written two ways, and requiring the units
    # to match the JSON key spelling would reject correct prose.
    for match in _QUANTITY.findall(text):
        token = match.strip().lower()
        digits = re.sub(r"[^\d.:]", "", token)
        if token in corpus or (digits and digits in corpus):
            continue
        unsupported.append(match.strip())

    return tuple(dict.fromkeys(unsupported))


class GeminiReasoner:
    """Gemini on Vertex AI, for interpretation and explanation only.

    Three things constrain what this plane can do, in increasing order of how
    much they are worth.

    1. **The system instruction** forbids feasibility judgements and invention.
       This is the weakest control and it is listed first so it is not mistaken
       for the important one.
    2. **The caller never asks a question whose answer would be a decision.**
       `narrate()` receives facts the deterministic layer has already
       established and asks only for their expression. There is no code path
       that asks Gemini whether a plan is feasible, because feasibility has one
       answer and `constraints.registry.evaluate` owns it.
    3. **Every response is checked before it is used.** `ungrounded_claims()`
       reads the returned text for identifiers and quantities that do not appear
       in the facts the model was given. A response carrying an invented
       constraint id or an invented measurement is discarded in favour of the
       deterministic template, and the rejection is recorded on the call. This
       is the control that does the work: it does not ask the model to behave,
       it checks whether it did.

    A failed call, an empty response and a rejected response all fall back to
    the offline plane and all set `degraded`. A run that silently produced
    template output while reporting "Gemini" would misrepresent itself.
    """

    plane = "gemini"

    SYSTEM_INSTRUCTION = (
        "You are an expert assistant inside a film production decision system. "
        "You explain and summarise evidence that a deterministic constraint solver has "
        "already evaluated. You never decide whether a plan is feasible, never invent "
        "constraints, resources, people, times or costs, and never contradict the "
        "structured facts you are given. If the facts do not support a statement, say so. "
        "Write in plain production language, in at most three sentences. Do not include "
        "any personal information beyond what appears in the facts, and never speculate "
        "about why a person requires an access arrangement. "
        "Every identifier and every measurement you write must appear in the facts you "
        "were given; anything else will be rejected automatically and discarded."
    )

    def __init__(self, model: str = "gemini-3.7-flash", project: str | None = None,
                 location: str = "us-central1") -> None:
        self.model = model
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        self.location = os.environ.get("GOOGLE_CLOUD_LOCATION", location)
        self._calls: list[ReasoningCall] = []
        self._fallback = OfflineReasoner()
        self._client = None
        self.degraded = False
        #: Responses discarded for carrying an unsupported claim.
        self.rejected = 0

    def _ensure_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
        return self._client

    def narrate(self, agent: str, purpose: str, facts: dict[str, Any],
                template: str) -> str:
        import json

        prompt = (
            f"Agent: {agent}\nPurpose: {purpose}\n"
            f"Structured facts (authoritative, do not contradict):\n"
            f"{json.dumps(facts, indent=2, default=str)}\n\n"
            "Write the finding headline as one or two sentences of plain production "
            "language. State only what the facts support."
        )
        started = time.perf_counter()
        try:
            client = self._ensure_client()
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "system_instruction": self.SYSTEM_INSTRUCTION,
                    "temperature": 0.2,
                    "max_output_tokens": 300,
                },
            )
            text = (response.text or "").strip()
            usage = getattr(response, "usage_metadata", None)
            elapsed = (time.perf_counter() - started) * 1000.0
            if not text:
                raise RuntimeError("empty response")

            # The control that matters. Anything checkable in the response has
            # to have come from the facts; if it did not, the response is not
            # used at all. Discarding a fluent paragraph over one invented
            # identifier is the correct trade in a system whose whole claim is
            # that no model output reaches a decision unchecked.
            rejected = ungrounded_claims(text, facts)
            self._calls.append(ReasoningCall(
                agent=agent, purpose=purpose, plane=self.plane,
                prompt_chars=len(prompt), response_chars=len(text),
                latency_ms=elapsed, model=self.model,
                tokens_in=getattr(usage, "prompt_token_count", None) if usage else None,
                tokens_out=getattr(usage, "candidates_token_count", None) if usage else None,
                rejected_claims=rejected,
            ))
            if rejected:
                self.degraded = True
                self.rejected += 1
                return self._fallback.narrate(agent, purpose, facts, template)
            return text
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000.0
            self.degraded = True
            self._calls.append(ReasoningCall(
                agent=agent, purpose=purpose, plane=self.plane,
                prompt_chars=len(prompt), response_chars=0, latency_ms=elapsed,
                model=self.model, error=str(exc)[:200],
            ))
            return self._fallback.narrate(agent, purpose, facts, template)

    def calls(self) -> list[ReasoningCall]:
        return list(self._calls) + self._fallback.calls()


def build_reasoner(mode: str | None = None) -> Reasoner:
    """The reasoning plane named by the environment or the CLI.

    Defaults to offline. `AA_REASONING_MODE=gemini` (or `--reasoning gemini`)
    selects Vertex AI.
    """
    selected = (mode or os.environ.get("AA_REASONING_MODE", "offline")).lower()
    if selected == "gemini":
        return GeminiReasoner(
            model=os.environ.get("AA_GEMINI_MODEL", "gemini-3.7-flash")
        )
    return OfflineReasoner()


# ---------------------------------------------------------------------------
# The agent base
# ---------------------------------------------------------------------------


@dataclass
class AgentContext:
    """Everything an agent is allowed to read. Nothing outside this is in scope."""

    disruption_id: str
    now: Any
    reasoner: Reasoner
    twin: Any = None
    problem: Any = None
    plans: list[Any] = field(default_factory=list)
    violations: list[Any] = field(default_factory=list)
    blast: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


class Agent:
    """Base class. Subclasses implement `assess` and return typed findings."""

    name: str = "agent"
    domain: ConstraintDomain = ConstraintDomain.APPROVAL
    authority: Role | None = None
    classification: Classification = Classification.PRODUCTION_INTERNAL

    def finding(
        self,
        context: AgentContext,
        *,
        status: FindingStatus,
        headline: str,
        scope: tuple[str, ...] = (),
        evidence: tuple[str, ...] = (),
        constraints: tuple[str, ...] = (),
        assumptions: tuple[str, ...] = (),
        confidence: float = 1.0,
        uncertainty: dict[str, Any] | None = None,
        hints: dict[str, Any] | None = None,
    ) -> Finding:
        # Structural guarantee mirrored from the data contract: a blocking
        # finding with no evidence is not permitted to exist, so the failure
        # happens here rather than at the stream boundary where the agent that
        # caused it is no longer on the stack.
        if status is FindingStatus.BLOCKING and not evidence:
            raise ValueError(
                f"{self.name} produced a blocking finding with no evidence: {headline}"
            )
        if status is FindingStatus.ABSTAINED and constraints:
            raise ValueError(
                f"{self.name} abstained but cited constraints: {constraints}"
            )
        return Finding(
            finding_id="F-" + stable_hash(
                [self.name, context.disruption_id, headline]
            )[:10].upper(),
            disruption_id=context.disruption_id,
            producer=self.name,
            domain=self.domain,
            scope=scope,
            status=status,
            headline=headline,
            evidence=evidence,
            applicable_constraints=constraints,
            assumptions=assumptions,
            confidence=confidence,
            uncertainty=uncertainty or {},
            required_authority=self.authority,
            solver_hints=hints or {},
            classification=self.classification,
            created_at=utcnow(),
        )

    def assess(self, context: AgentContext) -> list[Finding]:  # pragma: no cover - abstract
        raise NotImplementedError

    def run(self, context: AgentContext) -> list[Finding]:
        """Assess, converting an unexpected failure into an abstention.

        An agent that crashes must not take the disruption down with it, and must
        not silently vanish either — a coordinator that required this assessment
        needs to see that it did not happen.
        """
        try:
            return self.assess(context)
        except Exception as exc:
            return [self.finding(
                context,
                status=FindingStatus.ABSTAINED,
                headline=(
                    f"{self.name} could not complete its assessment and has abstained: "
                    f"{type(exc).__name__}"
                ),
                confidence=0.0,
                assumptions=(f"error: {str(exc)[:200]}",),
            )]
