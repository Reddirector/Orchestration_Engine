from typing import Any

from regenbench.drift.taxonomy import DriftType


class DeterministicDriftClassifier:
    """Classifies pair of (original_call, regenerated_call) into D0..D5 or DIFFERENT_INTENT."""

    @classmethod
    def classify(cls, orig: dict[str, Any], regen: dict[str, Any]) -> str:
        # Check strict type and value equality
        is_exact = True
        if set(orig.keys()) != set(regen.keys()):
            is_exact = False
        else:
            for k in orig:
                if type(orig[k]) is not type(regen[k]) or orig[k] != regen[k]:
                    is_exact = False
                    break

        if is_exact:
            return DriftType.D0.value

        # Check for different intent initially (N1: different amount, N2: different recipient)
        # S1 check
        if "order_id" in orig:
            if orig.get("order_id") != regen.get("order_id"):
                return "DIFFERENT_INTENT"
            orig_amt = orig.get("amount")
            regen_amt = regen.get("amount")
            if orig_amt is not None and regen_amt is not None:
                try:
                    clean_orig = float(str(orig_amt).replace("$", "").replace(",", ""))
                    clean_regen = float(str(regen_amt).replace("$", "").replace(",", ""))
                    if abs(clean_orig - clean_regen) > 1e-4:
                        return "DIFFERENT_INTENT"
                    if (type(orig_amt) is not type(regen_amt)) or (str(orig_amt) != str(regen_amt)):
                        return DriftType.D1.value
                except Exception:
                    pass

            if orig.get("currency") != regen.get("currency"):
                return "DIFFERENT_INTENT"

            if orig.get("reference") != regen.get("reference"):
                return DriftType.D4.value

        # S2 check
        if "to" in orig:
            orig_to = str(orig.get("to", "")).strip()
            regen_to = str(regen.get("to", "")).strip()
            if orig_to.lower() != regen_to.lower():
                return "DIFFERENT_INTENT"
            if orig_to != regen_to and orig_to.lower() == regen_to.lower():
                return DriftType.D5.value

            if orig.get("subject") != regen.get("subject") or orig.get("body") != regen.get("body"):
                return DriftType.D3.value

        # S3 check
        if "customer_id" in orig:
            if orig.get("customer_id") != regen.get("customer_id"):
                return "DIFFERENT_INTENT"
            if orig.get("external_ref") != regen.get("external_ref"):
                return DriftType.D4.value
            if orig.get("title") != regen.get("title") or orig.get("body") != regen.get("body"):
                return DriftType.D3.value

        # Check for structural noise (D2: extra keys or metadata)
        if set(orig.keys()) != set(regen.keys()):
            return DriftType.D2.value

        return DriftType.D2.value
