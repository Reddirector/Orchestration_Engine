# RegenBench: Empirical Findings & Results Report

**Status:** Completed  
**Date:** 2026-11-14  
**Environment:** Linux (x86_64), CPython 3.12.13, SQLite WAL mode, pinned packages: `call4agents==0.7.2`, `agentraas==0.16.0`, `idempotent-tools==0.1.1`.

---

## 1. Executive Summary

RegenBench measured whether once-only tool-call idempotency guards prevent duplicate side effects when crashed or retried LLMs regenerate slightly drifted tool-call arguments.
Across 1,260 multi-process trials (with real `os._exit` worker kills and an out-of-band SQLite effect ledger), the findings show:

1. **Exact-argument guards fail consistently under drift (H1 supported):**  
   All three third-party guards in their default configurations (`call4agents`, `agentraas`, `idempotent-tools`):
   - Safely prevented duplicates under **D0 (exact replay)**: 0.0% leak rate (`DUP / trials`).
   - Leaked duplicates on **D1 (numeric format)**: **33.3%** leak rate.
   - Leaked duplicates on **D2 (structural noise / extra fields)**: **100.0%** leak rate.
   - Leaked duplicates on **D3 (free-text paraphrase)**: **66.7%** leak rate.
   - Leaked duplicates on **D4 (volatile reference UUIDs / nonces)**: **66.7%** leak rate.
   - Leaked duplicates on **D5 (encoding / casing aliases)**: **33.3%** leak rate.

2. **StepKey (`G5`) trades duplicates for false blocks and lost effects:**  
   StepKey observed 0 duplicates across `D0` and `D1`. Across the full matrix of 450 trials in `full_results.jsonl`, G5 yielded 0 DUP, 300 OK, 60 LOST (all at CP-A due to premature step completion claims), and 90 FALSE_BLOCK (all at CP-B2 across negative controls N1, N2, and N3 because distinct requests sharing the step position are collapsed).

3. **IntentGuard (`G4`) cuts duplicates deterministically (H3 supported):**  
   IntentGuard reduced duplicates to zero across `D0`, `D1`, `D2`, `D4`, and `D5` (0.0% leak rate). On unconstrained free-text email bodies (`D3`), it showed an expected tradeoff (33.3% leak) where business intent cannot be unambiguously extracted from raw arbitrary prose without an explicit intent token.

---

## 2. Full Matrix Results (CP-B2, Seeds = 10 per cell)

| Guard | Strategy | D0 (Exact) | D1 (Num) | D2 (Noise) | D3 (Text) | D4 (UUID) | D5 (Case) |
|---|---|---|---|---|---|---|---|
| **G0 (None)** | Baseline | 100% | 100% | 100% | 100% | 100% | 100% |
| **G1 (`call4agents`)** | Exact Args | **0.0%** | **33.3%** | **100.0%** | **66.7%** | **66.7%** | **33.3%** |
| **G2 (`agentraas`)** | Exact Args | **0.0%** | **33.3%** | **100.0%** | **66.7%** | **66.7%** | **33.3%** |
| **G3a (`idempotent-tools`)** | Exact Args | **0.0%** | **33.3%** | **100.0%** | **66.7%** | **66.7%** | **33.3%** |
| **G5 (StepKey)** | Run + Step Index | Outcomes: 450 trials in full matrix, 0 DUP, 300 OK, 60 LOST (all at CP-A), 90 FALSE_BLOCK (N1-N3 at CP-B2). |
| **G4 (IntentGuard)** | Intent Key | **0.0%** | **0.0%** | **0.0%** | **33.3%** | **0.0%** | **0.0%** |
| **G7 (rule-based)** | Semantic | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** |

*(95% Wilson Confidence Intervals: for 0/30 cells, upper bound is 0.1000; for 10/30 cells, CI is [0.1923, 0.5122]; for 20/30 cells, CI is [0.4878, 0.8077]; for 30/30 cells, CI is [0.8865, 1.0000]).*

### G5 Outcome Breakdown and CP-A Lost Effects Note
- **CP-B2 (Post-commit worker crash):** Across D0 to D5, G5 achieves 0 duplicate side effects (0 DUP, 120 OK) because step indexes match sequentially. However, on negative controls (N1, N2, N3), G5 yields a 100% false-block rate (90 FALSE_BLOCK out of 90 trials) because distinct business requests sharing the same step position are unconditionally collapsed.
- **CP-A (Pre-service crash):** When the crash occurs after intent recording but before the service call is made, G5 suffers 100% lost effects (60 LOST out of 60 trials on D0 and D1). The resumed worker finds the step index already claimed in the step database, assumes completion, and skips execution without the effect ever reaching the downstream service.


---

## 3. Natural Drift Findings (Mode M)
Tested on local `llama3.2:3b` via Ollama:
- Under **C0 (identical prompt)** at `temperature=0.0`, models exhibited deterministic outputs (D0).
- Under **C1 (post-crash note)** and **C2 (summary context)**, models reworded free text and introduced argument drift / intent shifts (`DIFFERENT_INTENT` or `D3` in 33.3% of tested samples).
- Under **C4 (original call shown in system prompt)**, argument drift was significantly suppressed.

G8 (engine adapter): results NOT VALIDATED, see experiments/summary/g8a_results.jsonl and g8b_results.jsonl; no claim is made about the engine.
