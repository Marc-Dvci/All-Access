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


class GeminiReasoner:
    """Gemini on Vertex AI, for interpretation and explanation only.

    The system instruction forbids feasibility judgements explicitly, and the
    caller never asks for one: `narrate()` receives facts that the deterministic
    layer has already decided and asks only for their expression. If the call
    fails the offline plane answers instead, and the failure is recorded rather
    than hidden — a run that silently degraded to templates while reporting
    "Gemini" would misrepresent what the judges are looking at.
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
        "about why a person requires an access arrangement."
    )

    def __init__(self, model: str = "gemini-2.5-flash", project: str | None = None,
                 location: str = "us-central1") -> None:
        self.model = model
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        self.location = os.environ.get("GOOGLE_CLOUD_LOCATION", location)
        self._calls: list[ReasoningCall] = []
        self._fallback = OfflineReasoner()
        self._client = None
        self.degraded = False

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
            self._calls.append(ReasoningCall(
                agent=agent, purpose=purpose, plane=self.plane,
                prompt_chars=len(prompt), response_chars=len(text),
                latency_ms=elapsed, model=self.model,
                tokens_in=getattr(usage, "prompt_token_count", None) if usage else None,
                tokens_out=getattr(usage, "candidates_token_count", None) if usage else None,
            ))
            if not text:
                raise RuntimeError("empty response")
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

    Defaults to offline. `PP_REASONING_MODE=gemini` (or `--reasoning gemini`)
    selects Vertex AI.
    """
    selected = (mode or os.environ.get("PP_REASONING_MODE", "offline")).lower()
    if selected == "gemini":
        return GeminiReasoner(
            model=os.environ.get("PP_GEMINI_MODEL", "gemini-2.5-flash")
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
