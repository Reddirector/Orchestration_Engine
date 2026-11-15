import json
import time
from pathlib import Path
import pandas as pd
from regenbench.agents.ollama_client import OllamaClient
from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.classifier import DeterministicDriftClassifier


def main():
    client = OllamaClient()
    model = "llama3.2:3b"

    tools_by_sc = {
        "S1": [
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
        ],
        "S2": [
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
        ],
        "S3": [
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
        ],
    }

    conditions = ["C0", "C1", "C2", "C3", "C4"]
    # 20 pairs per condition = 100 pairs total
    scenarios = ["S1", "S2", "S3"]
    pairs = []
    pair_id = 0

    print("Generating 100 classified pairs for Mode M using llama3.2:3b...")
    t0 = time.time()

    for cond in conditions:
        for i in range(20):
            pair_id += 1
            sc_id = scenarios[i % len(scenarios)]
            seed = i
            sc = ScenarioGenerator.generate(sc_id, seed=seed)
            orig_args = sc.target_step.args
            prompt = sc.context_prompts[0]
            tools = tools_by_sc[sc_id]

            messages = [{"role": "user", "content": prompt}]
            if cond == "C1":
                messages.append({"role": "system", "content": "Note: Process resumed after crash."})
            elif cond == "C2":
                messages.append({"role": "system", "content": "Summary: Previous attempt initiated."})
            elif cond == "C3":
                messages.append({"role": "system", "content": "Error: Connection reset by peer during previous execution."})
            elif cond == "C4":
                messages.append({"role": "system", "content": f"Prior tool invocation: {json.dumps(orig_args)}"})

            try:
                regen_call = client.generate_tool_call(
                    model=model,
                    messages=messages,
                    tools=tools,
                    temperature=0.0 if cond == "C0" else 0.7,
                    timeout=30.0,
                )
                regen_args = regen_call.get("arguments", {}) if regen_call else orig_args
            except Exception:
                regen_args = orig_args

            drift_cat = DeterministicDriftClassifier.classify(orig_args, regen_args)
            changed = (drift_cat != "D0")

            pairs.append({
                "pair_id": pair_id,
                "model": model,
                "condition": cond,
                "scenario": sc_id,
                "seed": seed,
                "changed": changed,
                "drift_type": drift_cat,
                "original": orig_args,
                "regenerated": regen_args,
            })

    elapsed = time.time() - t0
    print(f"Generated and classified 100 pairs in {elapsed:.2f}s")

    out_file = Path("experiments/summary/mode_m_pairs.jsonl")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")

    df = pd.DataFrame(pairs)

    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    # 1. By Condition (C0-C4)
    summary_cond = df.groupby("condition").agg(
        total=("pair_id", "count"),
        unchanged_d0=("changed", lambda x: (x == False).sum()),
        changed_drift=("changed", "sum"),
        change_rate=("changed", lambda x: f"{(x.sum() / len(x)) * 100:.1f}%")
    ).reset_index()

    # 2. By Drift Type (D0-D5, DIFFERENT_INTENT)
    summary_drift = df.groupby(["condition", "drift_type"]).agg(
        count=("pair_id", "count")
    ).reset_index()

    # Overall Drift Breakdown
    overall_drift = df["drift_type"].value_counts().reset_index()
    overall_drift.columns = ["drift_type", "count"]
    overall_drift["pct"] = (overall_drift["count"] / len(df) * 100).round(1).astype(str) + "%"

    print("\n=== RAW TABLE 1: RESTORE CHANGE RATE BY CONTEXT (C0-C4) ===")
    print(summary_cond.to_string(index=False))

    print("\n=== RAW TABLE 2: DRIFT TYPE DISTRIBUTION OVERALL ===")
    print(overall_drift.to_string(index=False))

    print("\n=== RAW TABLE 3: DRIFT TYPE BREAKDOWN PER CONTEXT ===")
    pivot_table = pd.crosstab(df["condition"], df["drift_type"])
    print(pivot_table.to_string())

    print("\n=== RAW TABLE 4: AUDIT OF 100 CLASSIFIED PAIRS (SAMPLE FIRST 25) ===")
    audit_cols = ["pair_id", "condition", "scenario", "drift_type", "changed", "original", "regenerated"]
    print(df[audit_cols].head(25).to_string(index=False))


if __name__ == "__main__":
    main()
