import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from regenbench.core.env import EnvironmentRecord
from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from regenbench.harness.runner import TrialRunner


def run_eval(config_path: Path, output_dir: Path, workers: int = 16):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    runner = TrialRunner()
    env_dict = EnvironmentRecord.capture().to_dict()

    m_cfg = cfg.get("eval_matrix", cfg.get("full_matrix", {}))
    scenarios = m_cfg.get("scenarios", ["S1", "S2", "S3"])
    seeds = list(range(m_cfg.get("seeds", 10)))

    tasks = []

    # 1. Core guards across crash points and core drifts
    core_guards = m_cfg.get("core_guards", m_cfg.get("guards_core", []))
    crash_points = m_cfg.get("crash_points", [])
    core_drifts = m_cfg.get("core_drifts", m_cfg.get("drifts", []))

    for cp in crash_points:
        for g in core_guards:
            for d in core_drifts:
                for sc in scenarios:
                    for s in seeds:
                        tasks.append((sc, g, cp, d, s))

    # 2. CP-B2 specific drifts
    cp_b2_drifts = m_cfg.get("cp_b2_drifts", [])
    for g in core_guards:
        for d in cp_b2_drifts:
            for sc in scenarios:
                for s in seeds:
                    tasks.append((sc, g, "CP-B2", d, s))

    # 3. CP-B2 negative controls
    cp_b2_controls = m_cfg.get("cp_b2_controls", m_cfg.get("neg_controls", []))
    for g in core_guards:
        for n in cp_b2_controls:
            for sc in scenarios:
                for s in seeds:
                    tasks.append((sc, g, "CP-B2", n, s))

    # 4. Workaround guards at CP-B2
    workaround_guards = m_cfg.get("workaround_guards", [])
    workaround_drifts = m_cfg.get("workaround_drifts", [])
    for g in workaround_guards:
        for d in workaround_drifts:
            for sc in scenarios:
                for s in seeds:
                    tasks.append((sc, g, "CP-B2", d, s))

    print(f"Total tasks to execute: {len(tasks)}")

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
            "requests_w1": res.requests_w1,
            "requests_w2": res.requests_w2,
            "task_runner_invocations_w2": res.task_runner_invocations_w2,
            "halted": res.halted_for_human,
            "orig_args": orig_args,
            "mut_args": mut_args,
            "env": env_dict,
        }

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        all_results = list(ex.map(exec_task, tasks))
    elapsed = time.time() - t0
    print(f"Finished execution of {len(all_results)} tasks in {elapsed:.2f}s")

    output_dir.mkdir(parents=True, exist_ok=True)
    full_out = output_dir / "full_results.jsonl"
    with open(full_out, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r) + "\n")

    # Also partition d2_split and d6 subsets for reference
    d2_subset = [r for r in all_results if r["drift_type"] in ("D2a", "D2b")]
    d2_out = output_dir / "d2_split_results.jsonl"
    with open(d2_out, "w", encoding="utf-8") as f:
        for r in d2_subset:
            f.write(json.dumps(r) + "\n")

    d6_subset = [r for r in all_results if r["drift_type"] == "D6"]
    d6_out = output_dir / "d6_results.jsonl"
    with open(d6_out, "w", encoding="utf-8") as f:
        for r in d6_subset:
            f.write(json.dumps(r) + "\n")

    print(f"Wrote {len(all_results)} rows to {full_out}")
    print(f"Wrote {len(d2_subset)} rows to {d2_out}")
    print(f"Wrote {len(d6_subset)} rows to {d6_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/configs/reproducible_eval.yaml")
    parser.add_argument("--output-dir", default="experiments/summary")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    run_eval(Path(args.config), Path(args.output_dir), args.workers)
