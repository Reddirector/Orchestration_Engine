# PREREG_AMENDMENTS.md

**Date:** 2026-11-15  
**Document:** Methodological amendments and deviations from `docs/PREREG.md` (`prereg-v1`).

## Matrix Deviations & Amendments Table

| Item | PREREG Specification (Line) | Executed Matrix (Evidence in results file) | Reason for Deviation |
|---|---|---|---|
| **Sample Size / Trial Counts** | Line 31: "Seeds per cell: 20 distinct seeds per (guard, scenario, drift_type) cell for the pilot sweep." | Core cells (`D0`, `D1`, `D4` on `G0`, `G1`, `G2`, `G3a`, `G5`) ran 30 seeds per scenario (90 trials pooled across `S1`, `S2`, `S3`). Expanded drift types (`D2`, `D3`, `D5`) and guards `G4`, `G7` ran 10 seeds per scenario (30 trials pooled, 10 per individual cell). | The 10 vs 30 vs 90 trial counts reflect pooling across scenarios: 10 seeds * 3 scenarios = 30 trials; 30 seeds * 3 scenarios = 90 trials. Reason for deviation from 20 seeds/cell: reason not recorded. |
| **Crash Points** | Line 29: "Crash Points: CP-B2 (Hard OS worker kill after service commit)" | Only `CP-B2` was executed in `experiments/summary/pilot_results.jsonl`. Crash points `CP-A`, `CP-B1`, `CP-C`, `CP-D`, and `CP-E`: NOT RUN (planned). | Focus of pilot sweep was post-commit worker crash; other crash points have no results file and remain NOT RUN (planned). |
| **Drift Taxonomy Scope** | Line 30: "Drift Types: D0 (Control), D1 (Numeric format), D4 (Volatile UUID/reference)" | Executed `D0`, `D1`, `D2`, `D3`, `D4`, and `D5` in `experiments/summary/pilot_results.jsonl`. Sub-mutators `D2a` (key reorder only) and `D2b` (whitespace only) evaluated in standalone verification. | Expanded from 3 to 6 drift types in pilot sweep; reason not recorded. |
| **Guard Configurations** | Line 27: "Baselines & Workarounds: G0 (none), G1_workaround, G2_workaround, G3b, G5 (stepkey), G6 (server_key)" | Default configurations (`G0`, `G1`, `G2`, `G3a`, `G4`, `G5`, `G7`) executed in `experiments/summary/pilot_results.jsonl`. Workaround configurations (`G1_workaround`, `G2_workaround`, `G3b`, `G6`): NOT RUN (planned). | Workaround configurations have no results file in `experiments/` and remain NOT RUN (planned). |
| **Negative Controls** | Line 11: "...while maintaining a false-block rate on negative controls N1 and N2 below 1.0%." | `N1`, `N2`, and `N3` in matrix results: NOT RUN (planned). Zero N1/N2/N3 rows exist in `experiments/summary/pilot_results.jsonl`. | Unit tests exist in `tests/test_harness.py`, but full matrix runs for N1, N2, N3 have no results file and remain NOT RUN (planned). |
