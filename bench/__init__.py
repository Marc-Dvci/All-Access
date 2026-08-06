"""The ProductionPulse benchmark.

`harness.py` runs one disruption and measures it against the ground truth held
in `productionpulse.disruptions`. `report.py` aggregates. `run_benchmark.py` is
the entry point, and `calibration.py` checks the simulator against itself.

Nothing here is imported by `src/productionpulse`. The benchmark reads the
system; the system does not know it is being measured.
"""
