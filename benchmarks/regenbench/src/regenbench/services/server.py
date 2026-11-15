import json
import socket
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from regenbench.core.ledger import EffectLedger


@dataclass
class FaultConfig:
    crash_point: str | None = None  # e.g., "CP-B1" or "CP-E"
    delay_seconds: float = 0.0


class MockServiceHandler(BaseHTTPRequestHandler):
    ledger: EffectLedger
    fault_config: FaultConfig
    server_idempotency_cache: dict[str, dict[str, Any]] = {}
    current_phase: str = "w1"

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        data = json.loads(body_bytes.decode("utf-8"))

        intent_id = self.headers.get("X-Intent-Id")
        if not intent_id:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Missing X-Intent-Id header"}')
            return

        self.ledger.record_request(intent_id=intent_id, phase=self.current_phase)

        idempotency_key = self.headers.get("Idempotency-Key")

        # G6 Server-side idempotency check
        if idempotency_key and idempotency_key in self.server_idempotency_cache:
            cached_resp = self.server_idempotency_cache[idempotency_key]
            resp_bytes = json.dumps(cached_resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
            return

        path = self.path
        if path.startswith("/payments/charge"):
            service = "payments"
            action = "charge"
        elif path.startswith("/email/send"):
            service = "email"
            action = "send"
        elif path.startswith("/tickets/create"):
            service = "tickets"
            action = "create"
        else:
            self.send_response(404)
            self.end_headers()
            return

        if self.fault_config.delay_seconds > 0:
            time.sleep(self.fault_config.delay_seconds)

        record = self.ledger.record_effect(
            intent_id=intent_id,
            service=service,
            action=action,
            payload=data,
            idempotency_key=idempotency_key,
        )

        if self.fault_config.crash_point == "CP-B1":
            try:
                self.connection.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00"
                )
                self.connection.close()
            except Exception:
                pass
            return

        resp_payload = {
            "status": "success",
            "effect_id": record.id,
            "service": record.service,
            "action": record.action,
        }
        if idempotency_key:
            self.server_idempotency_cache[idempotency_key] = resp_payload

        resp_bytes = json.dumps(resp_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')


class MockServicesServer:
    def __init__(self, ledger: EffectLedger, host: str = "127.0.0.1", port: int = 0):
        self.ledger = ledger
        self.host = host
        self.fault_config = FaultConfig()

        class CustomHandler(MockServiceHandler):
            pass

        CustomHandler.ledger = self.ledger
        CustomHandler.fault_config = self.fault_config
        CustomHandler.server_idempotency_cache = {}

        self.handler_class = CustomHandler
        self.httpd = HTTPServer((host, port), CustomHandler)
        self.port = self.httpd.server_port
        self.thread: threading.Thread | None = None

    def set_phase(self, phase: str) -> None:
        self.handler_class.current_phase = phase

    def start(self) -> None:
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"
