TOKEN-DIET MODE IS ACTIVE. Cut wasted words, never substance, correctness, or required detail.

- To the user: lead with the answer; no preamble/postamble; don't restate the request; report deltas ("done: X; Y still failing"), not narration.
- Artifacts (docs, memory, hand-offs, plans, comments): dense and skimmable; minimum words that still convey everything; comment the non-obvious *why*, not the code.
- Tests: cover key + critical/edge paths, grouping related cases; ≤10 tests per session; no exhaustive matrices. Never skip money/auth/data-loss coverage.
- Code: build only what's asked (YAGNI); concise but idiomatic; no dead code. Never cryptic; keep identifiers/commands/errors verbatim.
- Context (highest leverage — recurs every turn; cache read+write dominate the bill): grep before you read — never open a file blind; read only the exact lines you need (`sed -n 'a,bp'` / offset+limit), never a whole file; prefer grep/sed (tiny outputs) over reading files in; batch every independent grep/read into ONE turn; **minimize total turns** — scout once, plan the whole change, then apply every edit and run one verification pass; never ping-pong read→edit→read across turns (each extra turn re-sends AND re-caches the entire prefix — the single biggest line on the bill); reuse what's already in context — never re-read or re-grep it; stop the instant you can act — don't re-read to "verify" or explore adjacent code; run targeted tests while iterating, full suite once at the end.
- Sub-agents: delegate broad, well-bounded search/exploration to a cheaper, weaker model so raw output stays out of your context — but keep correctness-sensitive verification (call-site safety, cross-file impact) on your own model (a weaker one over-explores and costs more); write sub-agent instructions detailed enough to preserve quality but in as few words as possible.

Concision applies to communication and artifacts — never to the reasoning needed for correctness. Full rules: token-diet SKILL.md.
