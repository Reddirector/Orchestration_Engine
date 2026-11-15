from typing import Any

import httpx


class EmailServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        intent_id: str,
        idempotency_key: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/email/send"
        headers = {
            "X-Intent-Id": intent_id,
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "to": to,
            "subject": subject,
            "body": body,
        }

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
