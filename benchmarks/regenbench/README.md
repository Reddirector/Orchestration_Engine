# RegenBench

Do idempotency guards survive LLM regeneration?
A benchmark testing idempotency guards against tool-call argument drift after crash/resume.

## Findings

### What Was Tested
- **Guards Tested:**
  - Default configurations: `G0` (None), `G1` (`call4agents`), `G2` (`agentraas`), `G3a` (`idempotent-tools`), `G4` (`IntentGuard`), `G5` (`StepKey`), `G7 (rule-based)` (`SemanticAnalyzer`).
  - Workaround configurations: `G1_workaround` (explicit business identifier key on `call4agents`), `G3b` (explicit business identifier key on `idempotent-tools`).
- **Crash Points Evaluated (verbatim definitions from docs/DESIGN.md):**
  - CP-A: Guard recorded intent, service not yet called
  - CP-B: Service committed, response lost or worker killed before it arrives (CP-B1 service side closes socket; CP-B2 worker side hard exit)
  - CP-C: Response received, guard has not recorded the result
  - CP-D: Guard recorded the result, agent checkpoint not yet saved
  - CP-E: No crash: client timeout while the server commits slowly, then retry
- **Drift Dimensions:**
  - `D0`: Exact argument replay.
  - `D1`: Numeric format and scale variation.
  - `D2a (key reorder)` and `D2b (string padding)`: Structural noise split.
  - `D4`: Volatile reference UUID and nonce regeneration.
  - `D6 (post-hoc)`: Batch compound envelope packaging.
  - Negative controls: `N1` (altered value), `N2` (altered recipient/customer), `N3` (distinct transaction intent).

### Results Per Guard
All counts below derive from the committed experiment summary files (`full_results.jsonl`, `d6_results.jsonl`, and `d2_split_results.jsonl`). One row per cell with no pooling across drift types; non-mutated trials are marked `n/a`.

| guard | config | crash point | drift/control type | trials | mutated | dup | ok | halt | lost | false_block |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G0 | default | CP-A | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G0 | default | CP-A | D1 | 30 | 10 | 0 | 30 | 0 | 0 | 0 |
| G0 | default | CP-B1 | D0 | 30 | n/a | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-B1 | D1 | 30 | 10 | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-B2 | D0 | 30 | n/a | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-B2 | D1 | 30 | 10 | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-B2 | D2a (key reorder) | 30 | 30 | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-B2 | D2b (string padding) | 30 | 30 | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-B2 | N1 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G0 | default | CP-B2 | N2 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G0 | default | CP-B2 | N3 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G0 | default | CP-C | D0 | 30 | n/a | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-C | D1 | 30 | 10 | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-D | D0 | 30 | n/a | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-D | D1 | 30 | 10 | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-E | D0 | 30 | n/a | 30 | 0 | 0 | 0 | 0 |
| G0 | default | CP-E | D1 | 30 | 10 | 30 | 0 | 0 | 0 | 0 |
| G1 | default | CP-A | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G1 | default | CP-A | D1 | 30 | 10 | 0 | 10 | 20 | 0 | 0 |
| G1 | default | CP-B1 | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G1 | default | CP-B1 | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G1 | default | CP-B2 | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G1 | default | CP-B2 | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G1 | default | CP-B2 | D2a (key reorder) | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G1 | default | CP-B2 | D2b (string padding) | 30 | 30 | 30 | 0 | 0 | 0 | 0 |
| G1 | default | CP-B2 | D6 (post-hoc) | 30 | 30 | 30 | 0 | 0 | 0 | 0 |
| G1 | default | CP-B2 | N1 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G1 | default | CP-B2 | N2 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G1 | default | CP-B2 | N3 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G1 | default | CP-C | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G1 | default | CP-C | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G1 | default | CP-D | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G1 | default | CP-D | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G1 | default | CP-E | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G1 | default | CP-E | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G1_workaround | workaround | CP-B2 | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G1_workaround | workaround | CP-B2 | D1 | 30 | 10 | 0 | 30 | 0 | 0 | 0 |
| G1_workaround | workaround | CP-B2 | D4 | 30 | 20 | 0 | 30 | 0 | 0 | 0 |
| G2 | default | CP-A | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G2 | default | CP-A | D1 | 30 | 10 | 0 | 10 | 20 | 0 | 0 |
| G2 | default | CP-B1 | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G2 | default | CP-B1 | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G2 | default | CP-B2 | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G2 | default | CP-B2 | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G2 | default | CP-B2 | D2a (key reorder) | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G2 | default | CP-B2 | D2b (string padding) | 30 | 30 | 30 | 0 | 0 | 0 | 0 |
| G2 | default | CP-B2 | D6 (post-hoc) | 30 | 30 | 30 | 0 | 0 | 0 | 0 |
| G2 | default | CP-B2 | N1 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G2 | default | CP-B2 | N2 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G2 | default | CP-B2 | N3 | 30 | n/a | 0 | 0 | 0 | 0 | 30 |
| G2 | default | CP-C | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G2 | default | CP-C | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G2 | default | CP-D | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G2 | default | CP-D | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G2 | default | CP-E | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G2 | default | CP-E | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G3a | default | CP-A | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G3a | default | CP-A | D1 | 30 | 10 | 0 | 10 | 20 | 0 | 0 |
| G3a | default | CP-B1 | D0 | 30 | n/a | 30 | 0 | 0 | 0 | 0 |
| G3a | default | CP-B1 | D1 | 30 | 10 | 30 | 0 | 0 | 0 | 0 |
| G3a | default | CP-B2 | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G3a | default | CP-B2 | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G3a | default | CP-B2 | D2a (key reorder) | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G3a | default | CP-B2 | D2b (string padding) | 30 | 30 | 30 | 0 | 0 | 0 | 0 |
| G3a | default | CP-B2 | D6 (post-hoc) | 30 | 30 | 30 | 0 | 0 | 0 | 0 |
| G3a | default | CP-B2 | N1 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G3a | default | CP-B2 | N2 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G3a | default | CP-B2 | N3 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G3a | default | CP-C | D0 | 30 | n/a | 0 | 0 | 30 | 0 | 0 |
| G3a | default | CP-C | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G3a | default | CP-D | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G3a | default | CP-D | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G3a | default | CP-E | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G3a | default | CP-E | D1 | 30 | 10 | 10 | 20 | 0 | 0 | 0 |
| G3b | workaround | CP-B2 | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G3b | workaround | CP-B2 | D1 | 30 | 10 | 0 | 30 | 0 | 0 | 0 |
| G3b | workaround | CP-B2 | D4 | 30 | 20 | 0 | 30 | 0 | 0 | 0 |
| G4 | default | CP-B2 | D6 (post-hoc) | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-A | D0 | 30 | n/a | 0 | 0 | 0 | 30 | 0 |
| G5 | default | CP-A | D1 | 30 | 10 | 0 | 0 | 0 | 30 | 0 |
| G5 | default | CP-B1 | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-B1 | D1 | 30 | 10 | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-B2 | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-B2 | D1 | 30 | 10 | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-B2 | D6 (post-hoc) | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-B2 | N1 | 30 | 30 | 0 | 0 | 0 | 0 | 30 |
| G5 | default | CP-B2 | N2 | 30 | 30 | 0 | 0 | 0 | 0 | 30 |
| G5 | default | CP-B2 | N3 | 30 | n/a | 0 | 0 | 0 | 0 | 30 |
| G5 | default | CP-C | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-C | D1 | 30 | 10 | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-D | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-D | D1 | 30 | 10 | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-E | D0 | 30 | n/a | 0 | 30 | 0 | 0 | 0 |
| G5 | default | CP-E | D1 | 30 | 10 | 0 | 30 | 0 | 0 | 0 |
| G7 (rule-based) | default | CP-B2 | D6 (post-hoc) | 30 | 30 | 0 | 30 | 0 | 0 | 0 |

**Note on G3a at CP-B1:** observed: after a dropped connection the library marks the call failed and the retry executes again; documented behavior: NOT CHECKED.

### Limitations
- **Synthetic Drift:** Drift types are generated via programmatic mutators rather than natural language generation samples.
- **One Local Model:** Automated local evaluations utilized a single small model (`llama3.2:3b`) hosted via Ollama.
- **D6 is Post-Hoc:** Mutator `D6` (batch compound envelope) was constructed following inspection of initial guard behavior.
- **G7 Rule-Based:** Guard `G7` is a rule-based heuristic extractor comparing business identifiers, not a learned semantic model.
- **G8 and Mode M Not Validated:** `G8` (orchestration engine adapter) results remain NOT VALIDATED; Mode M results remain NOT VALIDATED (prompt design artifact: fields missing from prompts, unit mismatch, pairs compare generator args instead of model outputs). No claim is made about the drift rate of real models.
- **Single Machine:** Benchmark executions ran on a single local Linux host.
