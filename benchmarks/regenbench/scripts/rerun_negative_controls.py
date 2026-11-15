import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from regenbench.harness.runner import TrialRunner


def main():
    summary_dir = Path("experiments/summary")
    full_results_path = summary_dir / "full_results.jsonl"
    archive_path = summary_dir / "archive_invalid_old_n_results.jsonl"

    # 1. Archive old N rows
    old_n_rows = []
    kept_rows = []
    if full_results_path.exists():
        with open(full_results_path) as f:
            for line in f:
                d = json.loads(line)
                if d.get("drift_type") in ("N1", "N2", "N3"):
                    old_n_rows.append(d)
                else:
                    kept_rows.append(d)

        with open(archive_path, "a") as f:
            for r in old_n_rows:
                f.write(json.dumps(r) + "\n")

    # 2. Re-run N1, N2, N3 for G0, G1, G2, G3a, G5 at CP-B2
    guards = ["G0", "G1", "G2", "G3a", "G5"]
    drifts = ["N1", "N2", "N3"]
    scenarios = ["S1", "S2", "S3"]
    seeds = list(range(10))

    tasks = []
    for g in guards:
        for d in drifts:
            for sc in scenarios:
                for s in seeds:
                    tasks.append((sc, g, "CP-B2", d, s))

    print(f"Total N tasks to re-run: {len(tasks)}")
    runner = TrialRunner()
    t0 = time.time()

    def exec_task(item):
        sc, g, cp, d, s = item
        res = runner.run_trial(sc, g, cp, d, seed=s)
        orig_args = ScenarioGenerator.generate(sc, seed=s).target_step.args
        mut_args = DriftMutator.mutate(d, orig_args, seed=s)
        is_mut = DriftMutator.is_mutated(orig_args, mut_args)
        return {
            "run_id": f"full-{g}-{cp}-{d}-{sc}-{s}",
            "scenario_id": sc,
            "guard_id": g,
            "crash_point": cp,
            "drift_type": d,
            "seed": s,
            "mutated": is_mut,
            "target_outcome": res.target_outcome.value,
            "control_outcome": res.control_outcome.value if res.control_outcome else None,
            "target_commits": res.target_commits,
            "control_commits": res.control_commits,
            "halted": res.halted_for_human,
            "requests_w1": res.requests_w1,
            "requests_w2": res.requests_w2,
            "task_runner_invocations_w2": res.task_runner_invocations_w2,
            "orig_args": orig_args,
            "mut_args": mut_args,
        }

    new_results = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for r in pool.map(exec_task, tasks):
            new_results.append(r)

    print(f"Finished {len(new_results)} tasks in {time.time() - t0:.2f}s")

    # Rewrite full_results.jsonl with kept + new results
    with open(full_results_path, "w") as f:
        for r in kept_rows + new_results:
            f.write(json.dumps(r) + "\n")

    # Build summary
    df = pd.DataFrame(new_results)
    df["dup"] = (df["target_outcome"] == "DUP").astype(int)
    df["ok"] = (df["target_outcome"] == "OK").astype(int)
    df["lost"] = (df["target_outcome"] == "LOST").astype(int)
    df["halt"] = (df["target_outcome"].isin(["HALT_SAFE", "HALT_STALL"])).astype(int)
    df["false_block"] = (df["target_outcome"] == "FALSE_BLOCK").astype(int)

    # N1 and N2 (mutated trials only)
    df_n1_n2 = df[df["drift_type"].isin(["N1", "N2"]) & df["mutated"]].copy()
    summary_n1_n2 = (
        df_n1_n2.groupby(["guard_id", "drift_type"])
        .agg(
            trials=("run_id", "count"),
            mutated=("mutated", "sum"),
            dup=("dup", "sum"),
            ok=("ok", "sum"),
            lost=("lost", "sum"),
            halt=("halt", "sum"),
            false_block=("false_block", "sum"),
        )
        .reset_index()
    )

    # N3 reported separately (identical args, new intent)
    df_n3 = df[df["drift_type"] == "N3"].copy()
    summary_n3 = (
        df_n3.groupby(["guard_id", "drift_type"])
        .agg(
            trials=("run_id", "count"),
            mutated=("mutated", "sum"),
            dup=("dup", "sum"),
            ok=("ok", "sum"),
            lost=("lost", "sum"),
            halt=("halt", "sum"),
            false_block=("false_block", "sum"),
        )
        .reset_index()
    )

    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    print("\nRAW RE-RUN TABLE: N1 & N2 (MUTATED TRIALS ONLY):")
    print(summary_n1_n2.to_string(index=False))

    print("\nRAW RE-RUN TABLE: N3 REPORTED SEPARATELY (IDENTICAL ARGS, NEW INTENT):")
    print(summary_n3.to_string(index=False))


if __name__ == "__main__":
    main()
