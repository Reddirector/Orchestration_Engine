import copy
import json
import random
from typing import Any


class DriftMutator:
    """Applies controlled synthetic mutations (D0-D5) and negative controls (N1-N3)."""

    @staticmethod
    def is_mutated(orig: dict[str, Any], mutated: dict[str, Any]) -> bool:
        """Determines whether arguments changed using stable JSON serialization and key ordering."""
        if list(orig.keys()) != list(mutated.keys()):
            return True
        return json.dumps(orig, sort_keys=True) != json.dumps(mutated, sort_keys=True)

    @classmethod
    def mutate(cls, drift_id: str, args: dict[str, Any], seed: int = 42) -> dict[str, Any]:
        rng = random.Random(seed)
        res = copy.deepcopy(args)

        if drift_id == "D0":
            return res

        elif drift_id == "D1":  # Numeric format
            for k in ["amount", "price", "cents"]:
                if k in res:
                    val = res[k]
                    if isinstance(val, (int, float)):
                        variant = rng.choice(["float", "str_cents", "dollar_str", "int_str"])
                        if variant == "float":
                            res[k] = float(val)
                        elif variant == "str_cents":
                            res[k] = f"{val:.2f}"
                        elif variant == "dollar_str":
                            res[k] = f"${int(val)}"
                        else:
                            res[k] = str(val)
            return res

        elif drift_id == "D2":  # Structure noise
            # Extra optional field with default value, or reordered keys
            res["_metadata"] = {"client_retry": True, "trace_hop": rng.randint(1, 5)}
            return res

        elif drift_id == "D2a":  # Key reorder only
            keys = list(res.keys())
            if len(keys) > 1:
                keys = list(reversed(keys))
            return {k: res[k] for k in keys}

        elif drift_id == "D2b":  # Whitespace only
            for text_key in ["subject", "body", "title", "reference"]:
                if text_key in res and isinstance(res[text_key], str):
                    res[text_key] = f"  {res[text_key]}  "
            return res

        elif drift_id == "D3":  # Free-text paraphrase
            paraphrases = [
                ("Invoice", "Billing statement"),
                ("Please find attached", "Attached is your document"),
                ("Your invoice", "Your bill"),
                ("Help", "Assistance requested"),
                ("Urgent", "Immediate attention needed"),
            ]
            for text_key in ["subject", "body", "title"]:
                if text_key in res and isinstance(res[text_key], str):
                    for orig, para in paraphrases:
                        if orig.lower() in res[text_key].lower():
                            res[text_key] = res[text_key].replace(orig, para)
                    # If unchanged, append polite greeting/sign-off
                    if res[text_key] == args[text_key]:
                        res[text_key] = f"{res[text_key]} (re-issued)"
            return res

        elif drift_id == "D4":  # Volatile fields (regenerated reference UUID / nonce)
            for ref_key in ["reference", "external_ref", "nonce", "uuid"]:
                if ref_key in res:
                    res[ref_key] = f"ref-regen-{rng.randint(100000, 999999)}"
            return res

        elif drift_id == "D5":  # Encoding aliases (email case, casing)
            for email_key in ["to", "email", "recipient"]:
                if email_key in res and isinstance(res[email_key], str):
                    s = res[email_key]
                    if "@" in s:
                        user, domain = s.split("@", 1)
                        res[email_key] = f"{user.upper()}@{domain.lower()}"
            return res

        elif drift_id == "N1":  # Negative control: Different amount
            for k in ["amount", "price", "cents"]:
                if k in res and isinstance(res[k], (int, float)):
                    res[k] = res[k] + rng.randint(1, 50)
            return res

        elif drift_id == "N2":  # Negative control: Different recipient
            for email_key in ["to", "email", "recipient"]:
                if email_key in res and isinstance(res[email_key], str):
                    res[email_key] = f"different_user_{rng.randint(100, 999)}@example.com"
            return res

        elif drift_id == "N3":  # Negative control: Ambiguous explicit repeat (identical payload)
            return res

        else:
            raise ValueError(f"Unknown drift or negative control ID: {drift_id}")
