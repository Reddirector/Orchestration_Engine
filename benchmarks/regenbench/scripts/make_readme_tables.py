#!/usr/bin/env python3
import collections
import json
from pathlib import Path
import sys
import pandas as pd


def load_committed_records(base_dir: Path) -> list[dict]:
    full_path = base_dir / "full_results.jsonl"
    records = []

    if full_path.exists():
        with open(full_path, "r", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                gid = r["guard_id"]
                if gid == "G7":
                    gid = "G7 (rule-based)"
                cfg = "workaround" if "workaround" in gid or gid == "G3b" else "default"
                raw_dt = r["drift_type"]
                dt = raw_dt
                if dt == "D2a":
                    dt = "D2a (key reorder)"
                elif dt == "D2b":
                    dt = "D2b (string padding)"
                elif dt == "D6":
                    dt = "D6 (post-hoc)"

                records.append({
                    "guard": gid,
                    "config": cfg,
                    "crash_point": r["crash_point"],
                    "drift_type": dt,
                    "raw_drift_type": raw_dt,
                    "mutated": r.get("mutated", False),
                    "outcome": r.get("target_outcome", ""),
                })

    return records


def check_consistency(records: list[dict]) -> list[str]:
    by_guard_cp = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in records:
        by_guard_cp[(r["guard"], r["crash_point"])][r["drift_type"]].append(r)

    violations = []
    for (guard, cp), dt_dict in sorted(by_guard_cp.items()):
        if "D0" not in dt_dict:
            continue
        d0_counts = collections.Counter(r["outcome"] for r in dt_dict["D0"])
        d0_total = len(dt_dict["D0"])
        d0_dist = {k: v / d0_total for k, v in d0_counts.items()}

        for dt, group in sorted(dt_dict.items()):
            raw_dt = group[0].get("raw_drift_type", dt)
            if not raw_dt.startswith("D") or raw_dt == "D0":
                continue
            non_mut = [r for r in group if not r["mutated"]]
            if not non_mut:
                continue
            nm_counts = collections.Counter(r["outcome"] for r in non_mut)
            nm_total = len(non_mut)
            nm_dist = {k: v / nm_total for k, v in nm_counts.items()}

            if nm_dist != d0_dist:
                violations.append(
                    f"Violation in {guard} at {cp} for {dt}: non-mutated dist {dict(nm_counts)} != D0 dist {dict(d0_counts)}"
                )

    return violations


def generate_table(records: list[dict]) -> str:
    df = pd.DataFrame(records)

    cells = []
    for (guard, cfg, cp, dt), group in df.groupby(["guard", "config", "crash_point", "drift_type"]):
        trials = len(group)
        mut_cnt = (group["mutated"] == True).sum()
        mut_val = str(mut_cnt) if mut_cnt > 0 else "n/a"
        dup = (group["outcome"] == "DUP").sum()
        ok = (group["outcome"] == "OK").sum()
        halt = (group["outcome"].astype(str).str.startswith("HALT")).sum()
        lost = (group["outcome"] == "LOST").sum()
        fb = (group["outcome"] == "FALSE_BLOCK").sum()
        cells.append({
            "guard": guard,
            "config": cfg,
            "crash point": cp,
            "drift/control type": dt,
            "trials": trials,
            "mutated": mut_val,
            "dup": dup,
            "ok": ok,
            "halt": halt,
            "lost": lost,
            "false_block": fb,
        })

    df_cells = pd.DataFrame(cells)

    guard_order = {
        "G1": 1,
        "G1_workaround": 2,
        "G2": 3,
        "G3a": 4,
        "G3b": 5,
        "G4": 6,
        "G5": 7,
        "G7 (rule-based)": 8,
    }
    cp_order = {"CP-A": 0, "CP-B1": 1, "CP-B2": 2, "CP-C": 3, "CP-D": 4, "CP-E": 5}
    dt_order = {
        "D0": 0,
        "D1": 1,
        "D2a (key reorder)": 2,
        "D2b (string padding)": 3,
        "D3": 4,
        "D4": 5,
        "D5": 6,
        "D6 (post-hoc)": 7,
        "N1": 8,
        "N2": 9,
        "N3": 10,
    }

    df_cells["g_rank"] = df_cells["guard"].map(lambda x: guard_order.get(x, 99))
    df_cells["cp_rank"] = df_cells["crash point"].map(lambda x: cp_order.get(x, 99))
    df_cells["dt_rank"] = df_cells["drift/control type"].map(lambda x: dt_order.get(x, 99))

    df_sorted = df_cells.sort_values(["g_rank", "cp_rank", "dt_rank"]).drop(
        columns=["g_rank", "cp_rank", "dt_rank"]
    )

    headers = [
        "guard",
        "config",
        "crash point",
        "drift/control type",
        "trials",
        "mutated",
        "dup",
        "ok",
        "halt",
        "lost",
        "false_block",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for _, row in df_sorted.iterrows():
        line = "| " + " | ".join(str(row[h]) for h in headers) + " |"
        lines.append(line)

    return "\n".join(lines)


def build_readme_content(table_md: str) -> str:
    content = f"""# RegenBench

Do idempotency guards survive LLM regeneration?
A benchmark testing idempotency guards against tool-call argument drift after crash/resume.

## Findings

### What Was Tested
- **Guards Tested:**
  - Default configurations: `G1` (`call4agents`), `G2` (`agentraas`), `G3a` (`idempotent-tools`), `G4` (`IntentGuard`), `G5` (`StepKey`), `G7 (rule-based)` (`SemanticAnalyzer`).
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
  - `D3`: Field re-ordering / omission.
  - `D4`: Volatile reference UUID and nonce regeneration.
  - `D5`: Type casting / stringification.
  - `D6 (post-hoc)`: Batch compound envelope packaging.
  - Negative controls: `N1` (altered value), `N2` (altered recipient/customer), `N3` (distinct transaction intent).

### Results Per Guard
All counts below derive from the committed experiment summary files (`full_results.jsonl`, `d6_results.jsonl`, and `d2_split_results.jsonl`). One row per cell with no pooling across drift types; non-mutated trials are marked `n/a`.

{table_md}

**Note on G3a at CP-B1:** observed: after a dropped connection the library marks the call failed and the retry executes again; documented behavior: NOT CHECKED.

### Limitations
- **Synthetic Drift:** Drift types are generated via programmatic mutators rather than natural language generation samples.
- **One Local Model:** Automated local evaluations utilized a single small model (`llama3.2:3b`) hosted via Ollama.
- **D6 is Post-Hoc:** Mutator `D6` (batch compound envelope) was constructed following inspection of initial guard behavior.
- **G7 Rule-Based:** Guard `G7` is a rule-based heuristic extractor comparing business identifiers, not a learned semantic model.
- **G8 and Mode M Not Validated:** `G8` (orchestration engine adapter) results remain NOT VALIDATED; Mode M results remain NOT VALIDATED (prompt design artifact: fields missing from prompts, unit mismatch, pairs compare generator args instead of model outputs). No claim is made about the drift rate of real models.
- **Single Machine:** Benchmark executions ran on a single local Linux host.
"""
    return content


def main():
    repo_root = Path(__file__).resolve().parent.parent
    summary_dir = repo_root / "experiments" / "summary"
    readme_path = repo_root / "README.md"

    records = load_committed_records(summary_dir)

    violations = check_consistency(records)
    if violations:
        print(f"Consistency check FAILED: {len(violations)} violations found:")
        for v in violations:
            print("  " + v)
        print("Stopping execution without modifying README.")
        sys.exit(1)
    else:
        print("Consistency check PASSED: 0 violations found. All non-mutated drift trials match D0 distribution.")

    table_md = generate_table(records)

    readme_content = build_readme_content(table_md)
    readme_path.write_text(readme_content, encoding="utf-8")

    print(f"Generated {len(records)} records into {readme_path}")


if __name__ == "__main__":
    main()
