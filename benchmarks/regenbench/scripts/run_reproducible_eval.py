import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from regenbench.core.env import EnvironmentRecord
from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from regenbench.harness.runner import TrialRunner


def run_eval(config_path: Path, output_dir: Path, workers: int = 16):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    runner = TrialRunner()
    env_dict = EnvironmentRecord.capture().to_dict()

    # 1. Regenerate full_results.jsonl
    full_cfg = cfg["full_matrix"]
    tasks_full = []
    guards_core = full_cfg["guards_core"]
    crash_points = full_cfg["crash_points"]
    drifts = full_cfg["drifts"]
    scenarios = full_cfg["scenarios"]
    seeds = list(range(full_cfg["seeds"]))

    # Core matrix
    for cp in crash_points:
        for g in guards_core:
            for d in drifts:
                for sc in scenarios:
                    for s in seeds:
                        tasks_full.append((sc, g, cp, d, s))

    # Negatives
    for n in full_cfg["neg_controls"]:
        for g in guards_core:
            for sc in scenarios:
                for s in seeds:
                    tasks_full.append((sc, g, "CP-B2", n, s))

    # Workarounds
    for g in full_cfg["workaround_guards"]:
        for d in full_cfg["workaround_drifts"]:
            for sc in scenarios:
                for s in seeds:
                    tasks_full.append((sc, g, "CP-B2", d, s))

    def exec_task(item):
        sc, g, cp, d, s = item
        res = runner.run_trial(sc, g, cp, d, seed=s)
        orig_args = ScenarioGenerator.generate(sc, seed=s).target_step.args
        mut_args = DriftMutator.mutate(d, orig_args, seed=s)
        is_mut = DriftMutator.is_mutated(orig_args, mut_args)
        return {
            "run_id": f"eval-{g}-{cp}-{d}-{sc}-{s}",
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
            "orig_args": orig_args,
            "mut_args": mut_args,
            "env": env_dict,
        }

    print(f"Executing {len(tasks_full)} tasks for full_results.jsonl...")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        full_results = list(ex.map(exec_task, tasks_full))
    print(f"Finished full_results in {time.time()-t0:.2f}s")

    full_out = output_dir / "full_results.jsonl"
    full_out.parent.mkdir(parents=True, exist_ok=True)
    with open(full_out, "w") as f:
        for r in full_results:
            f.write(json.dumps(r) + "\n")

    # 2. Regenerate d2_split_results.jsonl
    d2_cfg = cfg["d2_split"]
    tasks_d2 = []
    for g in d2_cfg["guards"]:
        for d in d2_cfg["drifts"]:
            for sc in d2_cfg["scenarios"]:
                for s in range(d2_cfg["seeds"]):
                    tasks_d2.append((sc, g, d2_cfg["crash_point"], d, s))

    print(f"Executing {len(tasks_d2)} tasks for d2_split_results.jsonl...")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        d2_results = list(ex.map(exec_task, tasks_d2))
    print(f"Finished d2_split in {time.time()-t0:.2f}s")

    d2_out = output_dir / "d2_split_results.jsonl"
    with open(d2_out, "w") as f:
        for r in d2_results:
            f.write(json.dumps(r) + "\n")

    print(f"Wrote {len(full_results)} rows to {full_out} and {len(d2_results)} rows to {d2_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/configs/reproducible_eval.yaml")
    parser.add_argument("--output-dir", default="experiments/summary")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    run_eval(Path(args.config), Path(args.output_dir), args.workers)
