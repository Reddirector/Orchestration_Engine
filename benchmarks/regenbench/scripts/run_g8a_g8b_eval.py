import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from regenbench.harness.runner import TrialRunner


def run_guard_eval(guard_id: str, out_file: Path) -> pd.DataFrame:
    runner = TrialRunner()
    crash_points = ["CP-A", "CP-B1", "CP-B2", "CP-C", "CP-D", "CP-E"]
    drifts = ["D0", "D1", "N1", "N2", "N3"]
    scenarios = ["S1", "S2", "S3"]
    seeds = list(range(10))

    tasks = []
    for cp in crash_points:
        for d in drifts:
            for sc in scenarios:
                for s in seeds:
                    tasks.append((sc, guard_id, cp, d, s))

    print(f"Running {len(tasks)} tasks for {guard_id}...")
    t0 = time.time()

    def exec_task(item):
        sc, g, cp, d, s = item
        res = runner.run_trial(sc, g, cp, d, seed=s)
        orig_args = ScenarioGenerator.generate(sc, seed=s).target_step.args
        mut_args = DriftMutator.mutate(d, orig_args, seed=s)
        is_mut = DriftMutator.is_mutated(orig_args, mut_args)
        return {
            "run_id": f"{g.lower()}_{sc}_{cp}_{d}_{s}",
            "scenario_id": sc,
            "guard_id": g,
            "crash_point": cp,
            "drift_type": d,
            "seed": s,
            "mutated": is_mut,
            "requests_w1": res.requests_w1,
            "requests_w2": res.requests_w2,
            "task_runner_w2": res.task_runner_invocations_w2,
            "target_outcome": res.target_outcome.value,
            "control_outcome": res.control_outcome.value if res.control_outcome else None,
            "halted": res.halted_for_human,
        }

    results = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for r in pool.map(exec_task, tasks):
            results.append(r)

    elapsed = time.time() - t0
    print(f"Finished {guard_id} in {elapsed:.2f}s")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    df = pd.DataFrame(results)
    df["dup"] = (df["target_outcome"] == "DUP").astype(int)
    df["ok"] = (df["target_outcome"] == "OK").astype(int)
    df["lost"] = (df["target_outcome"] == "LOST").astype(int)
    df["halt"] = (df["target_outcome"].isin(["HALT_SAFE", "HALT_STALL"])).astype(int)
    df["false_block"] = (
        (df["drift_type"].isin(["N1", "N2", "N3"]) & (df["target_outcome"] == "FALSE_BLOCK"))
        | (~df["drift_type"].isin(["N1", "N2", "N3"]) & (df["control_outcome"] == "FALSE_BLOCK"))
    ).astype(int)

    # Filter mutated trials only for D1 and N1/N2
    # D0 is non-mutated baseline; N3 is non-mutated negative control
    def keep_row(row):
        if row["drift_type"] in ("D1", "N1", "N2"):
            return bool(row["mutated"])
        return True

    df_filtered = df[df.apply(keep_row, axis=1)].copy()

    summary = (
        df_filtered.groupby(["guard_id", "crash_point", "drift_type"])
        .agg(
            trials=("run_id", "count"),
            mutated=("mutated", "sum"),
            requests_w1=("requests_w1", "sum"),
            requests_w2=("requests_w2", "sum"),
            task_runner_w2=("task_runner_w2", "sum"),
            dup=("dup", "sum"),
            ok=("ok", "sum"),
            lost=("lost", "sum"),
            halt=("halt", "sum"),
            false_block=("false_block", "sum"),
        )
        .reset_index()
    )
    return summary


def main():
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    g8a_out = Path("experiments/summary/g8a_results.jsonl")
    summary_g8a = run_guard_eval("G8a", g8a_out)
    print("\nRAW G8a TABLE (CP-A..E, D0, D1 [mutated only], N1-N3 [mutated only for N1/N2]):")
    print(summary_g8a.to_string(index=False))

    g8b_out = Path("experiments/summary/g8b_results.jsonl")
    summary_g8b = run_guard_eval("G8b", g8b_out)
    print("\nRAW G8b TABLE (CP-A..E, D0, D1 [mutated only], N1-N3 [mutated only for N1/N2]):")
    print(summary_g8b.to_string(index=False))


if __name__ == "__main__":
    main()
