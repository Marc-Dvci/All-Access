# Engineering standards — All-Access

These apply in every mode.

## The one rule that outranks the others

**A language model never decides feasibility.** Gemini interprets unstructured
input, explains solver output and writes role-specific communication. Whether a
plan is feasible is decided by `solver/predicates.py` and nothing else. If you
find yourself writing code where a model's answer determines whether work can go
ahead, stop and raise it.

## Typed boundaries

Nothing passes free-form text between components. Every record that crosses an
agent, stream or system boundary is a validated model in `contracts.py` with an
explicit schema version. If you need a new field, add it to the contract and to
the data contract in `stream/schemas.py`, and check compatibility.

## Fail closed

A check that cannot reach a verdict reports a violation. This matters most for
access and safety predicates: an arrangement the system cannot confirm is an
arrangement that is not satisfied. Never write `except: pass` around a
constraint evaluation.

## Evidence, not categories

A violation message must carry the measurement that failed. "The doorway is
760 mm where 850 mm is required" is actionable. "Accessibility concern" is not,
and a location manager cannot act on it.

## Numbers need artifacts

Never write a figure into a docstring, comment, README or document unless a
committed artifact or a runnable command produces it. If a claim has no artifact,
generate the artifact or drop the claim.

## Privacy

There is no field anywhere in this system that records *why* a person needs an
access arrangement, and there must never be one. `execution/privacy.py`
maintains a `PROHIBITED_FIELDS` tripwire; if you ever find yourself adding a
field it would catch, the design is wrong, not the tripwire.

## Style

- Line length 100. Ruff with `E,F,W,I`.
- Comments explain *why*, not *what*. Do not narrate the code.
- Docstrings on modules and non-obvious functions. State what the code
  guarantees and what it deliberately does not.
- Match the surrounding code's idiom.
