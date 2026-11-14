import json
from typing import Any, Optional
import httpx


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    def generate_tool_call(
        self,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        temperature: float = 0.0,
        timeout: float = 30.0,
    ) -> Optional[dict[str, Any]]:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            message = data.get("message", {})
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                return tool_calls[0].get("function", {})
            return None
