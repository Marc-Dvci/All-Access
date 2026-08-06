"""LEGACY call-sheet integration — the "before" artefact for the IBM Bob evidence.

DO NOT FIX THIS FILE. It is preserved deliberately as the starting condition for
the Bob modernization use case (bob-evidence/USE_CASES.md#uc-03), and the
before/after comparison is worthless if someone tidies it. `callsheet_modern.py`
is the version that runs in the hero workflow; this one exists so the difference
is a diff rather than a claim.

Its defects, all of them intentional and all of them documented in
bob-evidence/reviews/uc-03-review.md:

1. No schema. It takes a dict and pokes at whatever keys happen to be there.
2. Mutable module-level state shared between callers.
3. Polling. `poll_for_changes` busy-checks a global and returns whatever it finds.
4. No idempotency. Publishing the same revision twice publishes it twice.
5. Errors swallowed by a bare except that returns None, so failure looks like
   "no change".
6. Publishes personal data into the log line.
7. Off-by-one revision numbering: the first publish is revision 2.
8. No contract tests, no failure tests, no acknowledgment path.

Item 7 is a real bug that the modernization found. It is left in.
"""

from __future__ import annotations

import time

# Mutable module-level state, shared by every caller. Defect 2.
CALL_SHEET_STORE = {}
REVISION_COUNTER = 1
LAST_POLL = 0
PENDING = []
PUBLISH_LOG = []


def set_call_sheet(production, data):
    """Store a call sheet. No validation of any kind."""
    global REVISION_COUNTER
    CALL_SHEET_STORE[production] = data
    REVISION_COUNTER = REVISION_COUNTER + 1
    PENDING.append(production)
    return REVISION_COUNTER


def publish_revision(production, changes):
    """Publish a revised call sheet.

    No idempotency key, no version check, no schema. Called twice with the same
    changes, it publishes twice and increments twice.
    """
    global REVISION_COUNTER
    try:
        existing = CALL_SHEET_STORE.get(production)
        if existing == None:
            existing = {}
        for k in changes:
            existing[k] = changes[k]
        CALL_SHEET_STORE[production] = existing
        REVISION_COUNTER = REVISION_COUNTER + 1
        # Defect 6: personal data straight into the log line.
        cast = changes.get("cast_calls", {})
        line = "published rev %s for %s cast=%s" % (REVISION_COUNTER, production, cast)
        PUBLISH_LOG.append(line)
        unused = time.time()
        return {"revision": REVISION_COUNTER, "ok": True}
    except:
        # Defect 5: every failure looks like "nothing happened".
        return None


def poll_for_changes(timeout=5):
    """Poll the shared list for anything new. Defect 3."""
    global LAST_POLL
    started = time.time()
    found = []
    while time.time() - started < timeout:
        if len(PENDING) > 0:
            found.append(PENDING.pop(0))
            break
        time.sleep(0.05)
    LAST_POLL = time.time()
    return found


def get_revision():
    return REVISION_COUNTER


def reset():
    """Only used by the migration test harness."""
    global REVISION_COUNTER, LAST_POLL
    CALL_SHEET_STORE.clear()
    PENDING.clear()
    PUBLISH_LOG.clear()
    REVISION_COUNTER = 1
    LAST_POLL = 0
