import copy
import random
from typing import Any


class HeldOutMutator:
    """
    Held-out mutators: D6 (structural/batch/compound) plus 3 new variants per D1-D5,
    written independently of guard implementations.
    """

    @classmethod
    def mutate(cls, drift_id: str, args: dict[str, Any], seed: int = 42) -> dict[str, Any]:
        rng = random.Random(seed)
        res = copy.deepcopy(args)

        if drift_id == "D6":
            # D6 Structural: wraps payload into a batch / compound envelope
            return {
                "batch": [res],
                "operation": "bulk_commit",
                "count": 1,
            }

        elif drift_id == "D1_new_scientific":
            # D1 Variant A: Scientific notation (1000 -> 1e3 or 1.0e3)
            for k in ["amount", "price", "cents"]:
                if k in res and isinstance(res[k], (int, float)):
                    res[k] = f"{float(res[k]):.1e}"
            return res

        elif drift_id == "D1_new_fraction":
            # D1 Variant B: Explicit fractional string (1000 -> "1000/1")
            for k in ["amount", "price", "cents"]:
                if k in res and isinstance(res[k], (int, float)):
                    res[k] = f"{int(res[k])}/1"
            return res

        elif drift_id == "D1_new_leading_zeros":
            # D1 Variant C: Leading zeros ("0001000")
            for k in ["amount", "price", "cents"]:
                if k in res and isinstance(res[k], (int, float)):
                    res[k] = f"{int(res[k]):08d}"
            return res

        elif drift_id == "D2_new_headers_dict":
            # D2 Variant A: Client transport envelope
            res["client_headers"] = {"user-agent": "AgentRuntime/2.1", "session": f"sess-{rng.randint(100, 999)}"}
            return res

        elif drift_id == "D2_new_null_fields":
            # D2 Variant B: Explicit null/None optional parameters
            res["notes"] = None
            res["tag"] = None
            return res

        elif drift_id == "D2_new_nested_context":
            # D2 Variant C: Nested execution context wrapper
            res["context"] = {"execution_mode": "async", "retry_count": 1}
            return res

        elif drift_id == "D3_new_formal":
            # D3 Variant A: Highly formal rephrase
            for text_key in ["subject", "body", "title"]:
                if text_key in res and isinstance(res[text_key], str):
                    res[text_key] = f"Official Correspondence regarding: {res[text_key]}"
            return res

        elif drift_id == "D3_new_terse":
            # D3 Variant B: Extremely terse rephrase
            for text_key in ["subject", "body", "title"]:
                if text_key in res and isinstance(res[text_key], str):
                    res[text_key] = res[text_key][:10]
            return res

        elif drift_id == "D3_new_conversational":
            # D3 Variant C: Conversational intro
            for text_key in ["subject", "body", "title"]:
                if text_key in res and isinstance(res[text_key], str):
                    res[text_key] = f"Hi there! Following up on {res[text_key]}"
            return res

        elif drift_id == "D4_new_timestamp_iso":
            # D4 Variant A: Added ISO execution timestamp
            res["executed_at"] = "2026-11-15T09:15:00.123456Z"
            return res

        elif drift_id == "D4_new_nonce_hex":
            # D4 Variant B: Dynamic hex nonce
            res["nonce"] = f"0x{rng.randint(0x100000, 0xFFFFFF):06x}"
            return res

        elif drift_id == "D4_new_trace_id":
            # D4 Variant C: OpenTelemetry traceparent format
            res["traceparent"] = f"00-{rng.randint(100000, 999999)}-01"
            return res

        elif drift_id == "D5_new_url_encoding":
            # D5 Variant A: URL-encoded characters in email
            for email_key in ["to", "email", "recipient"]:
                if email_key in res and isinstance(res[email_key], str) and "@" in res[email_key]:
                    u, d = res[email_key].split("@", 1)
                    res[email_key] = f"{u}%40{d}"
            return res

        elif drift_id == "D5_new_plus_tagging":
            # D5 Variant B: Sub-address / plus-tag alias
            for email_key in ["to", "email", "recipient"]:
                if email_key in res and isinstance(res[email_key], str) and "@" in res[email_key]:
                    u, d = res[email_key].split("@", 1)
                    res[email_key] = f"{u}+service@{d}"
            return res

        elif drift_id == "D5_new_trailing_period":
            # D5 Variant C: Fully qualified domain with trailing period
            for email_key in ["to", "email", "recipient"]:
                if email_key in res and isinstance(res[email_key], str) and "@" in res[email_key]:
                    u, d = res[email_key].split("@", 1)
                    res[email_key] = f"{u}@{d}."
            return res

        else:
            raise ValueError(f"Unknown heldout drift id: {drift_id}")
