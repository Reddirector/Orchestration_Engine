# RegenBench Pre-Registration (prereg-v1)

**Frozen Date:** 2026-11-14  
**Status:** Frozen before Phase 3 Pilot evaluation runs.

---

## 1. Hypotheses
- **H1 (Guards leak under drift):** At least one exact-argument guard in its default configuration (`G1 call4agents`, `G2 agentraas`, `G3a idempotent-tools`) has a duplicate-effect rate (`DUP / trials`) whose lower 95% confidence bound is above 0 on at least one of the drift types `D1` through `D5`.
- **H2 (Natural drift exists):** Natural drift of type `D1` through `D5` occurs at 0.5% or more for at least one model and context condition in Phase 4.
- **H3 (IntentKey cuts duplicates):** IntentKey (`G4`, Phase 5) eliminates duplicate side effects on `D1` through `D5` relative to exact-argument keys, while maintaining a false-block rate on negative controls `N1` and `N2` below 1.0%.

---

## 2. Decision Gates
- **Gate 1 (Pilot Gate):**
  If after the synthetic pilot, every third-party guard **in its default configuration** (`G1`, `G2`, `G3a`) has an upper 95% Wilson confidence bound under 1% duplicates on `D1` to `D5`, stop the project, write a short negative-result note, and skip IntentGuard.
  *(Note: Workaround configurations `G1_workaround`, `G2_workaround`, `G3b`, and `G5`/`G6` are reported separately and do not trigger Gate 1 kill).*
- **Gate 2 (Natural Drift Gate):**
  If natural drift on `D1` to `D5` is under 0.5% across all tested local models **and** the capped frontier-model check also shows under 0.5%, report limited real-world impact.

---

## 3. Pilot Matrix & Sample Sizes
- **Guards evaluated in Pilot:**
  - Third-party defaults: `G1` (`call4agents`), `G2` (`agentraas`), `G3a` (`idempotent-tools`)
  - Baselines & Workarounds: `G0` (`none`), `G1_workaround`, `G2_workaround`, `G3b`, `G5` (`stepkey`), `G6` (`server_key`)
- **Scenarios:** `S1` (Payments), `S2` (Email), `S3` (Tickets)
- **Crash Points:** `CP-B2` (Hard OS worker kill after service commit)
- **Drift Types:** `D0` (Control), `D1` (Numeric format), `D4` (Volatile UUID/reference)
- **Seeds per cell:** 20 distinct seeds per (guard, scenario, drift_type) cell for the pilot sweep.
- **Materiality Threshold:** Duplicate rate >= 1.0%.
