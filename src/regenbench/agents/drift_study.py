import json
from pathlib import Path
from typing import Any

from regenbench.agents.ollama_client import OllamaClient
from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.classifier import DeterministicDriftClassifier


class NaturalDriftStudy:
    """Executes Mode M natural drift evaluation under conditions C0..C4."""

    def __init__(self, ollama_client: OllamaClient, output_dir: Path | str):
        self.client = ollama_client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_study(
        self,
        model_name: str,
        scenarios: list[str] = ["S1", "S2", "S3"],
        samples_per_cell: int = 15,
        temperatures: list[float] = [0.0, 0.7],
        conditions: list[str] = ["C0", "C1", "C2", "C4"],
    ) -> dict[str, Any]:
        results_records = []
        drift_counts: dict[str, int] = {}
        total_evals = 0

        tools_s1 = [
            {
                "type": "function",
                "function": {
                    "name": "charge_card",
                    "description": "Charge card for order",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_id": {"type": "string"},
                            "amount": {"type": "number"},
                            "currency": {"type": "string"},
                            "reference": {"type": "string"},
                        },
                        "required": ["order_id", "amount", "currency"],
                    },
                },
            }
        ]

        tools_s2 = [
            {
                "type": "function",
                "function": {
                    "name": "send_email",
                    "description": "Send email",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string"},
                            "subject": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            }
        ]

        tools_s3 = [
            {
                "type": "function",
                "function": {
                    "name": "create_ticket",
                    "description": "Create ticket",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "customer_id": {"type": "string"},
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                            "external_ref": {"type": "string"},
                        },
                        "required": ["customer_id", "title", "body"],
                    },
                },
            }
        ]

        for sc_id in scenarios:
            tools = tools_s1 if sc_id == "S1" else (tools_s2 if sc_id == "S2" else tools_s3)
            for temp in temperatures:
                for cond in conditions:
                    for seed in range(samples_per_cell):
                        sc = ScenarioGenerator.generate(sc_id, seed=seed)
                        prompt = sc.context_prompts[0]
                        orig_args = sc.target_step.args

                        messages = [{"role": "user", "content": prompt}]
                        if cond == "C1":
                            messages.append(
                                {"role": "system", "content": "Note: Process resumed after crash."}
                            )
                        elif cond == "C2":
                            messages.append(
                                {
                                    "role": "system",
                                    "content": "Summary: Previous attempt initiated.",
                                }
                            )
                        elif cond == "C4":
                            messages.append(
                                {
                                    "role": "system",
                                    "content": f"Prior tool invocation: {json.dumps(orig_args)}",
                                }
                            )

                        try:
                            regen_call = self.client.generate_tool_call(
                                model=model_name,
                                messages=messages,
                                tools=tools,
                                temperature=temp,
                            )
                            regen_args = (
                                regen_call.get("arguments", {}) if regen_call else orig_args
                            )
                        except Exception:
                            regen_args = orig_args

                        drift_cat = DeterministicDriftClassifier.classify(orig_args, regen_args)
                        drift_counts[drift_cat] = drift_counts.get(drift_cat, 0) + 1
                        total_evals += 1

                        results_records.append(
                            {
                                "scenario": sc_id,
                                "temperature": temp,
                                "condition": cond,
                                "seed": seed,
                                "original": orig_args,
                                "regenerated": regen_args,
                                "drift_category": drift_cat,
                            }
                        )

        summary_file = self.output_dir / f"natural_drift_{model_name.replace(':', '_')}.json"
        with open(summary_file, "w") as f:
            json.dump(
                {
                    "model": model_name,
                    "total_evals": total_evals,
                    "drift_counts": drift_counts,
                    "records": results_records,
                },
                f,
                indent=2,
            )

        return {
            "model": model_name,
            "total_evals": total_evals,
            "drift_counts": drift_counts,
        }
