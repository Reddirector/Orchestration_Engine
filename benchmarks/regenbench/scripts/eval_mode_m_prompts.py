import json
import time
import httpx
from regenbench.core.scenario import ScenarioGenerator
from regenbench.agents.ollama_client import OllamaClient


def main():
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
    scenarios = ["S1", "S2", "S3"]

    print("=== MODE M: EXACT PROMPTS AND 3 TRIALS PER CONDITION ===")

    for cond in conditions:
        print(f"\n==================== CONDITION {cond} ====================")
        for trial_idx in range(3):
            sc_id = scenarios[trial_idx % len(scenarios)]
            sc = ScenarioGenerator.generate(sc_id, seed=100 + trial_idx)
            orig_args = sc.target_step.args
            base_prompt = sc.context_prompts[0]
            tools = tools_by_sc[sc_id]

            messages = []
            if cond == "C0":
                messages = [{"role": "user", "content": base_prompt}]
            elif cond == "C1":
                messages = [
                    {"role": "system", "content": "Note: Process resumed after crash."},
                    {"role": "user", "content": base_prompt},
                ]
            elif cond == "C2":
                messages = [
                    {"role": "system", "content": "Summary: Previous attempt initiated."},
                    {"role": "user", "content": base_prompt},
                ]
            elif cond == "C3":
                messages = [
                    {"role": "system", "content": "Error: Connection reset by peer during previous execution."},
                    {"role": "user", "content": base_prompt},
                ]
            elif cond == "C4":
                messages = [
                    {"role": "system", "content": f"Prior tool invocation attempt: {json.dumps(orig_args)}"},
                    {"role": "user", "content": base_prompt},
                ]

            print(f"\n--- Condition: {cond} | Trial: {trial_idx + 1}/3 | Scenario: {sc_id} ---")
            print("EXACT PROMPT MESSAGES:")
            print(json.dumps(messages, indent=2))

            url = "http://localhost:11434/api/chat"
            payload = {
                "model": "llama3.2:3b",
                "messages": messages,
                "tools": tools,
                "stream": False,
                "options": {
                    "temperature": 0.0 if cond == "C0" else 0.7,
                },
            }

            t_start = time.perf_counter()
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                raw_json = resp.json()
            latency = time.perf_counter() - t_start

            msg = raw_json.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            print(f"LATENCY: {latency:.3f}s")
            print("RAW OLLAMA RESPONSE MESSAGE:")
            print(json.dumps(msg, indent=2))


if __name__ == "__main__":
    main()
