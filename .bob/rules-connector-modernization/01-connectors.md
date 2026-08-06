# Connector Modernization — additional rules

- **Do not repair `callsheet_legacy.py`.** It is the preserved "before" artifact.
  The modernization evidence is a diff, and a diff against tidied code proves
  nothing.
- Write the parity test first. `test_modern_matches_legacy_semantics` pins the
  intended content both connectors must agree on; fix defects only where the
  legacy behaviour was wrong, and say so.
- One defect, one test, one commit. A test must fail without its fix.
- Every fixed defect goes in the module docstring table with the test that
  covers it.
- Personal data never reaches a log line. The legacy connector wrote cast call
  times into its log; that is a person's whereabouts in a log with a different
  audience and retention policy from the call sheet.
