from typing import Any


def normalize_amount_to_minor_units(val: Any) -> int:
    """Converts int, float, or formatted strings ($10, 10.00, 1,000) to integer cents."""
    if isinstance(val, int):
        return val
    s = str(val).strip().replace("$", "").replace(",", "")
    try:
        f = float(s)
        # If float represents dollars or cents
        return int(round(f))
    except Exception:
        return 0


def normalize_email(email_str: str) -> str:
    """Canonicalizes email by stripping whitespace and lowercasing."""
    return str(email_str).strip().lower()


def normalize_declared_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Normalizes declared intent arguments while stripping volatile and free-text fields.
    - S1 payments: order_id, amount (in minor units), currency
    - S2 email: to (lowercased), purpose
    - S3 tickets: customer_id, category
    """
    res = {}
    if tool_name == "charge_card":
        res["order_id"] = str(args.get("order_id", "")).strip()
        res["amount"] = normalize_amount_to_minor_units(args.get("amount", 0))
        res["currency"] = str(args.get("currency", "USD")).strip().upper()
    elif tool_name == "send_email":
        res["to"] = normalize_email(args.get("to", ""))
        # Purpose can be extracted or defaulted
        res["purpose"] = (
            "invoice" if "invoice" in str(args.get("subject", "")).lower() else "general"
        )
    elif tool_name == "create_ticket":
        res["customer_id"] = str(args.get("customer_id", "")).strip()
        res["category"] = (
            "billing"
            if "billing" in str(args.get("title", "")).lower()
            or "refund" in str(args.get("title", "")).lower()
            else "technical"
        )
    else:
        res = {k: str(v) for k, v in sorted(args.items())}
    return res
