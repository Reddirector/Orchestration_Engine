# PREREG_AMENDMENTS.md

**Date:** 2026-11-15  
**Document:** Deviations from `docs/PREREG.md` (frozen `prereg-v1`).

---

## Deviations in Pilot Matrix Execution

1. **Crash Points:**
   - *PREREG.md specification:* Planned matrix at `CP-B2`.
   - *Executed matrix:* Pilot sweep initially focused on `CP-B2` (hard OS worker exit after service commit).
   - *Amendment:* Full benchmark matrix must explicitly run `CP-A`, `CP-B1`, `CP-B2`, `CP-C`, `CP-D`, and `CP-E` across all guards.

2. **Sample Sizes & Drift Types:**
   - *PREREG.md specification:* 20 seeds across `D0`, `D1`, `D4`.
   - *Executed matrix:* Expanded to `D0` through `D5` at 10 seeds for full guard sweep, yielding 30 trials per (guard, drift_type) cell across the 3 scenarios.
   - *Amendment:* Record exact seed allocation and cell trials explicitly per variant rather than pooling across scenarios.

3. **Guard Configurations (Default vs. Documented Workaround):**
   - *PREREG.md specification:* Evaluate both default and documented workaround configs (`G1_workaround`, `G2_workaround`, `G3b`).
   - *Executed matrix:* The initial pilot table pooled third-party guards in default configuration only.
   - *Amendment:* Explicitly evaluate and report default and documented-workaround configurations side by side for all third-party guards (`G1`, `G2`, `G3a` vs `G1_workaround`, `G2_workaround`, `G3b`).

4. **Negative Controls (N1, N2, N3):**
   - *PREREG.md specification:* False-block evaluation on `N1` and `N2`.
   - *Executed matrix:* Negative controls were evaluated via unit tests but omitted from the consolidated summary matrix.
   - *Amendment:* Add `N1`, `N2`, and `N3` to the reporting matrix across all guards to measure false-block rate directly.
