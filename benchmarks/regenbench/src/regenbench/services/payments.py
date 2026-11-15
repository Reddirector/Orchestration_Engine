from typing import Any

import httpx


class PaymentsServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def charge_card(
        self,
        order_id: str,
        amount: float | str,
        currency: str,
        reference: str,
        intent_id: str,
        idempotency_key: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/payments/charge"
        headers = {
            "X-Intent-Id": intent_id,
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "order_id": order_id,
            "amount": amount,
            "currency": currency,
            "reference": reference,
        }

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
