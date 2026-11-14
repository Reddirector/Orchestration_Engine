import json
from pathlib import Path
from typing import Any
import yaml
from regenbench.analysis.stats import wilson_score_interval
from regenbench.harness.runner import TrialRunner


class MatrixRunner:
    """Runs a matrix of trials specified in a YAML config and produces summary tables."""

    def __init__(self, config_path: Path | str, output_dir: Path | str):
        self.config_path = Path(config_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_results_file = self.output_dir / "pilot_results.jsonl"

    def run(self) -> dict[str, Any]:
        with open(self.config_path) as f:
            cfg = yaml.safe_load(f)

        guards = cfg["guards"]
        scenarios = cfg["scenarios"]
        drift_types = cfg["drift_types"]
        crash_point = cfg.get("crash_point", "CP-B2")
        num_seeds = cfg.get("seeds", 20)

        runner = TrialRunner(results_path=self.raw_results_file)

        # Aggregate stats: key = (guard, drift_type) -> list of results
        cell_stats: dict[tuple[str, str], dict[str, int]] = {}

        total_trials = len(guards) * len(scenarios) * len(drift_types) * num_seeds
        current = 0

        for guard in guards:
            for drift in drift_types:
                cell_key = (guard, drift)
                if cell_key not in cell_stats:
                    cell_stats[cell_key] = {"trials": 0, "dup": 0, "ok": 0, "halt": 0, "lost": 0, "false_block": 0}

                for sc in scenarios:
                    for seed in range(num_seeds):
                        current += 1
                        res = runner.run_trial(
                            scenario_id=sc,
                            guard_id=guard,
                            crash_point=crash_point,
                            drift_type=drift,
                            seed=seed,
                        )
                        cell_stats[cell_key]["trials"] += 1
                        if res.target_outcome.value == "DUP":
                            cell_stats[cell_key]["dup"] += 1
                        elif res.target_outcome.value in ("OK", "HALT-SAFE", "HALT-STALL"):
                            cell_stats[cell_key]["ok"] += 1
                        elif res.target_outcome.value == "LOST":
                            cell_stats[cell_key]["lost"] += 1

                        if res.control_outcome and res.control_outcome.value == "FALSE_BLOCK":
                            cell_stats[cell_key]["false_block"] += 1

        # Build summary report
        summary_rows = []
        for (g, d), counts in cell_stats.items():
            n = counts["trials"]
            dups = counts["dup"]
            leak_rate = dups / n if n > 0 else 0.0
            ci_low, ci_high = wilson_score_interval(dups, n)
            summary_rows.append({
                "guard": g,
                "drift_type": d,
                "trials": n,
                "dup_count": dups,
                "leak_rate": round(leak_rate, 4),
                "ci_95_low": round(ci_low, 4),
                "ci_95_high": round(ci_high, 4),
            })

        summary_path = self.output_dir / "pilot_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary_rows, f, indent=2)

        return {"summary": summary_rows, "raw_file": str(self.raw_results_file)}
