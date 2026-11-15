import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from regenbench.harness.runner import TrialRunner


def main():
    runner = TrialRunner()
    crash_points = ["CP-A", "CP-B1", "CP-B2", "CP-C", "CP-D", "CP-E"]
    drifts = ["D0", "D1", "D2", "D3", "D4", "D5", "N1", "N2", "N3"]
    scenarios = ["S1", "S2", "S3"]
    seeds = list(range(10))

    tasks = []
    for cp in crash_points:
        for d in drifts:
            for sc in scenarios:
                for s in seeds:
                    tasks.append((sc, "G8", cp, d, s))

    print(f"Total G8 tasks to run: {len(tasks)}")
    t0 = time.time()

    def exec_task(item):
        sc, g, cp, d, s = item
        res = runner.run_trial(sc, g, cp, d, seed=s)
        orig_args = ScenarioGenerator.generate(sc, seed=s).target_step.args
        mut_args = DriftMutator.mutate(d, orig_args, seed=s)
        is_mut = DriftMutator.is_mutated(orig_args, mut_args)
        return {
            "run_id": f"eval_G8_{sc}_{cp}_{d}_{s}",
            "scenario_id": sc,
            "guard_id": g,
            "crash_point": cp,
            "drift_type": d,
            "seed": s,
            "target_outcome": res.target_outcome.value,
            "control_outcome": res.control_outcome.value if res.control_outcome else None,
            "halted": res.halted_for_human,
            "mutated": is_mut,
        }

    results = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for r in pool.map(exec_task, tasks):
            results.append(r)

    elapsed = time.time() - t0
    print(f"Finished {len(results)} G8 tasks in {elapsed:.2f}s")

    out_file = Path("experiments/summary/g8_results.jsonl")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    # Generate summary dataframe
    df = pd.DataFrame(results)
    
    # Map outcomes
    df["dup"] = (df["target_outcome"] == "DUP").astype(int)
    df["ok"] = (df["target_outcome"] == "OK").astype(int)
    df["lost"] = (df["target_outcome"] == "LOST").astype(int)
    df["halt"] = (df["target_outcome"].isin(["HALT_SAFE", "HALT_STALL"])).astype(int)
    df["false_block"] = (
        (df["drift_type"].isin(["N1", "N2", "N3"]) & (df["target_outcome"] == "FALSE_BLOCK"))
        | (~df["drift_type"].isin(["N1", "N2", "N3"]) & (df["control_outcome"] == "FALSE_BLOCK"))
    ).astype(int)

    summary = (
        df.groupby(["guard_id", "crash_point", "drift_type"])
        .agg(
            trials=("run_id", "count"),
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
    print("\nRAW G8 SUMMARY TABLE:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
