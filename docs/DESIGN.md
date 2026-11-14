# RegenBench: Do idempotency guards survive LLM regeneration?

Design document and master prompt for a coding agent.
Working title: **RegenBench**. Status: design, nothing built yet. Every number in this file that is not marked "measured" is a plan or an estimate.

---

## 0. TL;DR

- **Problem.** When an AI agent crashes or retries and then re-issues a side-effecting tool call (payment, email, ticket), the re-issued call can differ slightly from the original. Most "once-only" guards key on the exact arguments, so a slightly different call looks like a new action and the effect happens twice.
- **What we do.** Build a reproducible benchmark that crashes agents at controlled points, makes the call come back drifted, and counts real duplicate effects in a ground-truth ledger. Run existing guards through it. Then test a reference fix (intent keys plus reconcile-before-retry).
- **Why it can matter.** It measures a limit that the closest tool already documents but nobody has quantified, and it gives guard authors a test they can adopt.
- **Honest risk.** If real models rarely drift, the result is "exact-argument keying is fine". That is still a publishable negative result, and the kill gates below say when to stop.

---

## 1. Problem and evidence

Agents are getting write access to money, email and infrastructure. Frameworks retry and resume. A resumed node re-runs from its start, so any tool call inside it can fire again.

Evidence already published (verify each before citing in the final report):

| Source | What it shows |
|---|---|
| ACRFence, arXiv 2603.20625 | Agents re-synthesize subtly different requests after a restore, so servers treat them as new. Survey table of side-effect issues across 12 agent frameworks. |
| Atomix, arXiv 2602.14849 | Transactional tool use for agent workflows. Does not claim full crash-safe exactly-once. |
| Cordon, arXiv 2606.17573 | Semantic transactions for tool-using agents. Resume evaluated on a small number of deterministic trajectories. |
| Khan, arXiv 2606.17182 | Formalizes concurrency anomalies in TLA+ under deterministic-generation semantics, the replay assumption that regeneration breaks. |
| call4agents (PyPI) | Once-only per run, tool and exact arguments. Its own docs say a model rewriting arguments on retry (10 becomes 10.00) counts as a new action. |
| agentraas, idempotent-tools (PyPI) | Same-arguments keying. |
| ACRFence proof of concept (read in full) | Claude Code with Qwen3-32B: 10 of 10 checkpoint-restore trials duplicated a payment after the model regenerated a reference UUID; 0 of 10 without restore. No implementation of its own mitigation. |
| DFAH, arXiv 2601.15322 | Measures action, signature and decision determinism over 4,700+ runs and 7 models, with an open-source harness. Small models were more deterministic than frontier models. Not about guards. |
| ReliabilityBench, arXiv 2601.06112 | Fault injection plus task perturbation, correctness by end-state equivalence. Not about guards or duplicate effects. |
| Bide, agentraas-chaos, call4agents crashtest | Crash-injection benchmarks and testers already exist (not about drift). Our novelty is the drift dimension and the cross-guard measurement. |

---

## 2. Research questions, hypotheses, kill gates

**RQ1 (guards).** For each guard, what are the duplicate-effect rate and the false-block rate per drift type and crash point?
**RQ2 (natural drift).** How often do real local models regenerate a tool call that differs in bytes but not in intent, by model, temperature and resume context?
**RQ3 (fix).** Do intent keys plus reconcile-before-retry reduce duplicates compared with exact-argument keys, and at what false-block, halt and latency cost?

**Hypotheses:**
- H1: at least one exact-argument guard has a duplicate rate whose lower 95% confidence bound is above 0 on at least one of the drift types D1 to D5.
- H2: natural drift of type D1 to D5 occurs at 0.5% or more for at least one model and context condition.
- H3: IntentKey reduces duplicates versus exact-argument keys on D1 to D5, with a false-block rate on negative controls N1 and N2 below 1%.

| Gate | Condition | Action |
|---|---|---|
| G0 | A published benchmark of regeneration drift against guards exists | Replicate or extend it. Do not build a duplicate. |
| G1 | After the synthetic pilot, every guard **in its default configuration** has an upper 95% bound under 1% duplicates on D1 to D5 (workaround configurations are reported separately and never decide this gate; only the third-party guards G1, G2 and G3a decide it) | Write a short negative-result note. Skip IntentGuard. |
| G2 | Natural drift of D1 to D5 is under 0.5% for every local model and condition, **and** the capped frontier-model check (section 6) also shows under 0.5% | Report limited real-world impact. |

---

## 5. Experimental design

### 5.1 Drift taxonomy
- D0: None (control)
- D1: Numeric format
- D2: Structure noise
- D3: Free-text paraphrase
- D4: Volatile fields
- D5: Encoding aliases
- D6: Structural (stretch)
- N1: Negative control (same order, different amount - must execute)
- N2: Negative control (same amount, different recipient - must execute)
- N3: Ambiguous control (explicit second identical request)

### 5.2 Crash points
- CP-A: Guard recorded intent, service not yet called
- CP-B: Service committed, response lost or worker killed before it arrives (CP-B1 service side closes socket; CP-B2 worker side hard exit)
- CP-C: Response received, guard has not recorded the result
- CP-D: Guard recorded the result, agent checkpoint not yet saved
- CP-E: No crash: client timeout while the server commits slowly, then retry

### 5.4 Scenarios
- S1 payments: `charge_card(order_id, amount, currency, reference)` -> intent: order_id, amount in minor units, currency
- S2 email: `send_email(to, subject, body)` -> intent: recipient plus purpose
- S3 tickets: `create_ticket(customer_id, title, body, external_ref)` -> intent: customer_id plus category

### 5.5 Outcome classification
- Target intent: count commits
  - commits >= 2: DUP
  - commits == 1 and halted == False: OK
  - commits == 1 and halted == True: HALT-SAFE
  - commits == 0 and halted == True: HALT-STALL
  - commits == 0 and halted == False: LOST
- Control intent:
  - committed == True: OK
  - committed == False: FALSE_BLOCK
