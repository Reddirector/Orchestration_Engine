# RegenBench Phase 0: Prior Art (corrected)

Date: 2026-11-12. Status: **provisional**. Replaces the earlier PRIOR_ART.md produced by the coding agent, whose claims were unsupported (see section 6).
Labels: **[read]** = I read the source text in this session. **[snippet]** = search-result excerpt only. **[not checked]** = not looked at.

---

## 1. Closest prior work

### 1.1 ACRFence, arXiv 2603.20625 **[read, full text]**

- Title: "ACRFence: Preventing Semantic Rollback Attacks in Agent Checkpoint-Restore". UC Santa Cruz and UConn. v1 dated 21 Mar 2026. Four pages.
- Claim: retry-safety advice assumes a retried call is identical to the original; LLM agents re-synthesize subtly different requests after restore, so servers treat them as new (duplicate payments, reused credentials). Names two attack classes: Action Replay and Authority Resurrection. It has **no** D0 to D5 taxonomy; that is ours.
- Evidence: proof of concept with Claude Code CLI and Qwen3-32B against simulated MCP services. 10 of 10 checkpoint-restore trials produced duplicate commits; 0 of 10 without restore. The drift that caused it was a regenerated reference UUID (our D4). Stateless token reuse succeeded 2 of 2.
- Survey table of side-effect issues across 12 agent frameworks (LangGraph 8+, CrewAI 5, Claude Code 5, and others). Secondary evidence; the underlying issue threads were not opened.
- Mitigation proposed: an interposing proxy plus a lightweight analyzer LLM that decides whether a post-restore call is semantically equivalent (replay), different (block, require fork), or credential reuse. **Closest prior art for our IntentGuard fix.**
- Stated limits: no implementation of ACRFence itself; analyzer accuracy and overhead, more models and larger-scale experiments are listed as future work. This supports our gap.
- Also cites: arXiv 2408.04667, 2601.06118, 2506.09501 (sources of LLM nondeterminism, even at temperature 0).

### 1.2 call4agents (PyPI, GitHub salahmakboul/call4agents) **[read, README as cached for 0.1.0]**

- Once-only actions keyed per (run, tool, exact arguments); approvals bound to exact arguments (a "yes" to one call cannot run a changed call); idempotency keys for outside APIs; record, replay, diff; `EffectInDoubt`, `reconcile=`, `idempotent_for=`; a `prove` command that re-inserts bugs to check a guard.
- **Documented limit (exact point that matters):** if the model rewrites arguments on a retry (its example: 10 becomes 10.00), the call is treated as a new action; the user must pass a manual `c4a_key=`.
- Its own tests: a 12-process random-kill test with a payment API that drops answers (0 double charges versus 244 of 300 without the kit); a framework table (LangGraph, Pydantic AI, OpenAI Agents SDK); an approval case where the model is asked again after restart and says 12 instead of 10 (refused). None of these vary arguments for the once-only path as far as the README shows.
- Versions: sources disagree. PyPI RSS snapshot lists 0.1.0 to 0.5.0 (latest dated Oct 25, 2026). The cached project page showed 0.1.0. I saw a later page earlier in this session listing releases up to 0.7.1 (Nov 11); not re-fetched. **Resolve by running `pip index versions call4agents` on a networked machine.**

### 1.3 DFAH, "Replayable Financial Agents", arXiv 2601.15322 **[snippet, several mirrors; abstract and v2 text excerpts]**

- IBM; ICLR 2026 FinAI Workshop. Defines action, signature (identical tool calls with identical arguments) and decision determinism for tool-using agents. 4,700+ runs, 7 models from 4 providers, 3 financial benchmarks of 50 cases each. Open-source harness (github ibm-client-engineering/output-drift-financial-llms) with an Ollama option.
- Reported finding: small models reach near-perfect determinism through pattern matching, while frontier models use more varied tool paths and show lower determinism.
- Overlap: partly pre-empts RQ2 (natural drift). Not about guards, crashes or side effects.
- **Implication:** small local models may under-estimate drift relative to production models.

### 1.4 ReliabilityBench, arXiv 2601.06112 **[snippet]**

- Reliability surface R(k, epsilon, lambda): repeated-run consistency, semantically equivalent task perturbations, and fault injection (timeouts, rate limits, partial responses, schema drift) in a chaos-engineering style. Two models, ReAct and Reflexion, four domains, 1,280 episodes. Correctness by end-state equivalence rather than text similarity.
- Overlap: validates a ledger-based end-state oracle and fault injection as method. Not about guards or duplicate effects.

### 1.5 Other leads seen earlier (snippet only)

- Atomix (2602.14849), Cordon (2606.17573), Khan TLA+ concurrency anomalies (2606.17182), TraceFix (2605.07935), MemTX (2607.23929).

---

## 2. Guards: what is and is not established

| Guard | Established | Not established |
|---|---|---|
| call4agents | Section 1.2 | Versions after 0.5.0 (changelog not read); GitHub issues not read |
| agentraas | Earlier snippet: same-arguments exactly-once plus a chaos tester | Everything else; the earlier agent's claims (Redis, rejection of mismatched arguments, "issue threads") have no source |
| idempotent-tools | Earlier snippet: hash of function name and arguments; optional context | Version and behavior beyond the snippet |
| Others (keelstack guard, CTRLRun, agent-ledger, Temporal integrations) | Names only | Not checked |

---

## 3. Searches run

Run by me this session, with outcomes: ACRFence full text (read); call4agents PyPI page (read); call4agents release RSS (snippet); DFAH arXiv and mirrors (snippet); ReliabilityBench arXiv and mirrors (snippet). Earlier in the session: guard-ecosystem searches that surfaced call4agents, agentraas, idempotent-tools, practitioner posts.

**Still to run (not done):** at least three more distinct benchmark queries on guard behavior under regenerated arguments; agentraas and idempotent-tools docs and issues; GitHub issue search in each guard repo for "arguments differ", "rewrite", "regenerate"; the changelog of the latest call4agents release.

---

## 4. Gate 0 (provisional)

**Recommendation: build, with repositioning.** In my checks, no maintained benchmark measures per-guard duplicate-effect rates under regenerated arguments, and the closest paper states it has no implementation and lists larger-scale evaluation as future work. This is absence in a limited search, not proof.

Repositioning required:

1. **IntentGuard is not novel as a concept.** ACRFence proposes semantic comparison at the tool boundary. Position ours as a deterministic, schema-declared alternative, and add an ACRFence-style analyzer as a baseline guard (G7), since no implementation exists.
2. **RQ2 is partly covered** by DFAH. Our addition must be: drift classified by type, conditioned on post-restore context, and linked to guard leakage.
3. **Gate 2 must not rest on small local models alone.** DFAH suggests they may drift less than frontier models. Include a capped frontier-model check before concluding "drift is rare".
4. **Test every guard in default and documented-workaround configurations** (for example `c4a_key`, idempotent-tools `context=`), or the benchmark is a strawman.
5. D4 (volatile fields) is already demonstrated in the wild by ACRFence; keep it a primary synthetic category.

---

## 5. Open risks

- Scoop risk: call4agents releases frequently.
- Absence-of-evidence risk: Section 3's remaining searches could still find a closer benchmark.

---

## 6. Why the earlier PRIOR_ART.md was rejected

Unsupported claims marked as verified (an "Issue #?" placeholder, invented benchmark names, and the Redis claim); a quote that mixed up approvals with once-only actions; a "D0 to D5 taxonomy" wrongly attributed to ACRFence; conflicting version claims without evidence; no links; and, on the second attempt, the file content was unchanged while the chat summary described sections that were not in it.
