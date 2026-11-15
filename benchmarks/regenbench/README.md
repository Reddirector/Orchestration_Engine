# RegenBench

Do idempotency guards survive LLM regeneration?
A benchmark testing idempotency guards against tool-call argument drift after crash/resume.

## Findings

### What Was Tested
- **Guards Tested:**
  - Default configurations: `G0` (None), `G1` (`call4agents`), `G2` (`agentraas`), `G3a` (`idempotent-tools`), `G4` (`IntentGuard`), `G5` (`StepKey`), `G7 (rule-based)` (`SemanticAnalyzer`).
  - Workaround configurations: `G1_workaround` (explicit business identifier key on `call4agents`), `G3b` (explicit business identifier key on `idempotent-tools`).
- **Crash Points Evaluated:**
  - `CP-A`: Crash prior to downstream service execution.
  - `CP-B1`: Crash during downstream service execution / exception.
  - `CP-B2`: Crash immediately post-commit prior to returning results to worker.
  - `CP-C`: Downstream network drop / connection reset.
  - `CP-D`: Post-acknowledgment worker process termination.
  - `CP-E`: Completion after full state flush.
- **Drift Dimensions:**
  - `D0`: Exact argument replay.
  - `D1`: Numeric format and scale variation.
  - `D2`: Structural noise and metadata injection (evaluated in split tests `D2a` and `D2b`).
  - `D3`: Free-text rephrasing and formatting adjustments.
  - `D4`: Volatile reference UUID and nonce regeneration.
  - `D5`: Header and casing aliases.
  - `D6`: Batch compound envelope packaging.
  - Negative controls: `N1` (altered value), `N2` (altered recipient/customer), `N3` (distinct transaction intent).

### Results Per Guard
All counts below reflect mutated trials only (`mutated == True`), derived directly from the committed experiment summary files (`full_results.jsonl`, `d6_results.jsonl`, and `d2_split_results.jsonl`).

#### Full Matrix (Committed `full_results.jsonl`, Mutated Trials Only: 660 Trials)
| Guard | Config | Crash Point | Trials | DUP | OK | HALT | FALSE_BLOCK |
|---|---|---|---|---|---|---|---|
| `G0` | Default | CP-A | 10 | 0 | 10 | 0 | 0 |
| `G0` | Default | CP-B1 | 10 | 10 | 0 | 0 | 0 |
| `G0` | Default | CP-B2 | 70 | 10 | 60 | 0 | 0 |
| `G0` | Default | CP-C | 10 | 10 | 0 | 0 | 0 |
| `G0` | Default | CP-D | 10 | 10 | 0 | 0 | 0 |
| `G0` | Default | CP-E | 10 | 10 | 0 | 0 | 0 |
| `G1` | Default | CP-A | 10 | 0 | 10 | 0 | 0 |
| `G1` | Default | CP-B1 | 10 | 10 | 0 | 0 | 0 |
| `G1` | Default | CP-B2 | 70 | 10 | 60 | 0 | 0 |
| `G1` | Default | CP-C | 10 | 10 | 0 | 0 | 0 |
| `G1` | Default | CP-D | 10 | 10 | 0 | 0 | 0 |
| `G1` | Default | CP-E | 10 | 10 | 0 | 0 | 0 |
| `G1_workaround` | Workaround | CP-B2 | 30 | 0 | 30 | 0 | 0 |
| `G2` | Default | CP-A | 10 | 0 | 10 | 0 | 0 |
| `G2` | Default | CP-B1 | 10 | 10 | 0 | 0 | 0 |
| `G2` | Default | CP-B2 | 70 | 10 | 60 | 0 | 0 |
| `G2` | Default | CP-C | 10 | 10 | 0 | 0 | 0 |
| `G2` | Default | CP-D | 10 | 10 | 0 | 0 | 0 |
| `G2` | Default | CP-E | 10 | 10 | 0 | 0 | 0 |
| `G3a` | Default | CP-A | 10 | 0 | 10 | 0 | 0 |
| `G3a` | Default | CP-B1 | 10 | 10 | 0 | 0 | 0 |
| `G3a` | Default | CP-B2 | 70 | 10 | 60 | 0 | 0 |
| `G3a` | Default | CP-C | 10 | 10 | 0 | 0 | 0 |
| `G3a` | Default | CP-D | 10 | 10 | 0 | 0 | 0 |
| `G3a` | Default | CP-E | 10 | 10 | 0 | 0 | 0 |
| `G3b` | Workaround | CP-B2 | 30 | 0 | 30 | 0 | 0 |
| `G5` | Default | CP-A | 10 | 0 | 0 | 0 | 0 |
| `G5` | Default | CP-B1 | 10 | 0 | 10 | 0 | 0 |
| `G5` | Default | CP-B2 | 70 | 0 | 10 | 0 | 60 |
| `G5` | Default | CP-C | 10 | 0 | 10 | 0 | 0 |
| `G5` | Default | CP-D | 10 | 0 | 10 | 0 | 0 |
| `G5` | Default | CP-E | 10 | 0 | 10 | 0 | 0 |

#### Post-Hoc Stress Trials (Committed `d6_results.jsonl`, Mutated Trials Only: 180 Trials)
| Guard | Config | Crash Point | Trials | DUP | OK | HALT | FALSE_BLOCK |
|---|---|---|---|---|---|---|---|
| `G1` | Default | CP-B2 | 30 | 30 | 0 | 0 | 0 |
| `G2` | Default | CP-B2 | 30 | 30 | 0 | 0 | 0 |
| `G3a` | Default | CP-B2 | 30 | 30 | 0 | 0 | 0 |
| `G4` | Default | CP-B2 | 30 | 0 | 30 | 0 | 0 |
| `G5` | Default | CP-B2 | 30 | 0 | 30 | 0 | 0 |
| `G7 (rule-based)` | Default | CP-B2 | 30 | 0 | 30 | 0 | 0 |

#### Structural Noise Trials (Committed `d2_split_results.jsonl`, Mutated Trials Only: 240 Trials)
| Guard | Config | Crash Point | Trials | DUP | OK | HALT | FALSE_BLOCK |
|---|---|---|---|---|---|---|---|
| `G0` | Default | CP-B2 | 60 | 60 | 0 | 0 | 0 |
| `G1` | Default | CP-B2 | 60 | 30 | 30 | 0 | 0 |
| `G2` | Default | CP-B2 | 60 | 30 | 30 | 0 | 0 |
| `G3a` | Default | CP-B2 | 60 | 30 | 30 | 0 | 0 |

### Limitations
- **Synthetic Drift:** Drift types `D1` through `D6` are generated via programmatic mutators rather than natural language generation samples.
- **One Local Model:** Automated local evaluations utilized a single small model (`llama3.2:3b`) hosted via Ollama.
- **D6 is Post-Hoc:** Mutator `D6` (batch compound envelope) was constructed following inspection of initial guard behavior.
- **G7 Rule-Based:** Guard `G7` is a rule-based heuristic extractor comparing business identifiers, not a learned semantic model.
- **G8 and Mode M Not Validated:** `G8` (orchestration engine adapter) results remain NOT VALIDATED; Mode M results remain NOT VALIDATED (prompt design artifact: fields missing from prompts, unit mismatch, pairs compare generator args instead of model outputs). No claim is made about the drift rate of real models.
- **Single Machine:** Benchmark executions ran on a single local Linux host.
