# Solver Engineering — additional rules

- **You may implement constraints. You may not decide them.**
  `src/productionpulse/constraints/registry.py` is owned by the production's
  safety lead, UPM and accessibility coordinator. Do not edit it. If a predicate
  needs a constraint that does not exist, raise it in the brief.
- Never change a constraint's `kind` from `HARD` to `SOFT`. A soft access or
  safety constraint is one the objective function can trade away.
- Objectives are all minimised and none of them may describe safety or access.
  `test_objectives_exclude_safety_and_access` enforces this.
- Every predicate needs a test that proves it rejects something. A constraint
  never observed to say no is untested.
- Search may be approximate. The verdict may not: `engine.validate()` re-runs
  the full registry against the finished plan, and that path must stay
  independent of the search.
