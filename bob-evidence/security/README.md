# Security findings

Findings from IBM Bob **Security Review** mode sessions, one file per session.

## Status

**Empty. No Security Review session has been run.**

The threat model those sessions will be reviewed against is
`../../docs/THREAT_MODEL.md`. UC-04 in `../USE_CASES.md` carries the brief and,
deliberately, a known ground-truth finding — the per-process approval signing key
when `AA_APPROVAL_KEY` is unset — so a session's output can be judged rather than
admired.

## Format

One file per session: `<uc-id>-<nnn>-findings.md`, with SARIF alongside where the
tooling produces it.

Each finding must carry:

- the code path, by file and line
- a concrete exploitation sequence — "consider validating input" is not a finding
- severity, and the reasoning for it
- whether it is already mitigated, and by what

Findings that turn out to be already mitigated are **recorded as such, not
deleted**. A review that silently drops its false positives cannot be assessed,
and the mitigation being named is useful to the next reader.

No fix is applied in the same session as the review. That is workflow step 6 and
step 7, in that order.
