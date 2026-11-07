"""Event-Driven Webhook Ingestion and Reactive Topic Bus.

Provides zero-dependency event publishing, wildcard topic subscriptions, and an HTTP
webhook server to reactively trigger workflows and signals upon receiving cloud webhooks.
"""

from __future__ import annotations

import fnmatch
import http.server
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    """An event message traversing the reactive event bus."""

    topic: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class EventSubscription:
    """Subscription rule mapping an event topic pattern to a handler callback."""

    subscription_id: str
    topic_pattern: str
    callback: Callable[[Event], None]
    filter_fn: Callable[[Event], bool] | None = None

    def matches(self, event: Event) -> bool:
        """Check if an event matches the topic pattern and optional filter predicate."""
        if not fnmatch.fnmatch(event.topic, self.topic_pattern):
            return False
        if self.filter_fn is not None:
            try:
                return bool(self.filter_fn(event))
            except Exception as exc:
                logger.warning("Subscription %s filter_fn raised: %s", self.subscription_id, exc)
                return False
        return True


class EventBus:
    """In-memory thread-safe reactive event bus supporting wildcard topic subscriptions."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, EventSubscription] = {}
        self._lock = threading.Lock()

    def subscribe(
        self,
        topic_pattern: str,
        callback: Callable[[Event], None],
        *,
        filter_fn: Callable[[Event], bool] | None = None,
        subscription_id: str | None = None,
    ) -> str:
        """Register a handler for events matching a topic pattern (supports * wildcards)."""
        sub_id = subscription_id or uuid.uuid4().hex
        sub = EventSubscription(
            subscription_id=sub_id,
            topic_pattern=topic_pattern,
            callback=callback,
            filter_fn=filter_fn,
        )
        with self._lock:
            self._subscriptions[sub_id] = sub
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove an existing subscription."""
        with self._lock:
            return self._subscriptions.pop(subscription_id, None) is not None

    def publish(self, topic: str, payload: dict[str, Any]) -> Event:
        """Publish an event to all matching subscribers synchronously or in threads."""
        event = Event(topic=topic, payload=payload)
        with self._lock:
            subs = list(self._subscriptions.values())

        for sub in subs:
            if sub.matches(event):
                try:
                    sub.callback(event)
                except Exception as exc:
                    logger.exception("Error in event handler %s: %s", sub.subscription_id, exc)

        return event


class WebhookServer:
    """Standard library HTTP server receiving webhook POST requests and publishing them."""

    def __init__(
        self,
        event_bus: EventBus,
        *,
        host: str = "127.0.0.1",
        port: int = 9200,
        secret_token: str | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.host = host
        self.port = port
        self.secret_token = secret_token
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _create_handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        bus = self.event_bus
        expected_secret = self.secret_token

        class WebhookHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass  # Suppress default noisy stdlib access logging

            def do_POST(self) -> None:  # noqa: N802
                # Check Auth Token if configured
                if expected_secret:
                    auth_header = self.headers.get("Authorization", "")
                    custom_header = self.headers.get("X-Webhook-Token", "")
                    token = ""
                    if auth_header.startswith("Bearer "):
                        token = auth_header[7:].strip()
                    elif custom_header:
                        token = custom_header.strip()

                    if token != expected_secret:
                        self.send_response(401)
                        self.end_headers()
                        self.wfile.write(b'{"error": "Unauthorized"}\n')
                        return

                # Parse topic from path: /webhook/<topic>
                path_parts = self.path.strip("/").split("/")
                if len(path_parts) < 2 or path_parts[0] != "webhook":
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b'{"error": "Expected path format /webhook/<topic>"}\n')
                    return

                topic = path_parts[1]
                content_len = int(self.headers.get("Content-Length", 0))
                body_bytes = self.rfile.read(content_len)

                try:
                    payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
                except json.JSONDecodeError:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error": "Invalid JSON body"}\n')
                    return

                event = bus.publish(topic, payload)

                resp_body = json.dumps({"ok": True, "event_id": event.event_id}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(resp_body)

        return WebhookHandler

    def start(self) -> None:
        """Start the webhook server in a background daemon thread."""
        handler_cls = self._create_handler()
        self._server = http.server.HTTPServer((self.host, self.port), handler_cls)
        # Re-read actual assigned port if 0 was passed
        self.port = self._server.server_port

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop and close the webhook server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
