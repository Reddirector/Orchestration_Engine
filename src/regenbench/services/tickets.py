from typing import Any

import httpx


class TicketsServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def create_ticket(
        self,
        customer_id: str,
        title: str,
        body: str,
        external_ref: str,
        intent_id: str,
        idempotency_key: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/tickets/create"
        headers = {
            "X-Intent-Id": intent_id,
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "customer_id": customer_id,
            "title": title,
            "body": body,
            "external_ref": external_ref,
        }

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
