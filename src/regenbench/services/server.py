from dataclasses import dataclass
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from pathlib import Path
import socket
import threading
import time
from typing import Any, Callable, Optional
from regenbench.core.ledger import EffectLedger


@dataclass
class FaultConfig:
    crash_point: Optional[str] = None  # e.g., "CP-B1" or "CP-E"
    delay_seconds: float = 0.0


class MockServiceHandler(BaseHTTPRequestHandler):
    ledger: EffectLedger
    fault_config: FaultConfig

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard logging to keep test output clean
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

        idempotency_key = self.headers.get("Idempotency-Key")

        # Determine path and service
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

        # Pre-effect delay or fault if any
        if self.fault_config.delay_seconds > 0:
            time.sleep(self.fault_config.delay_seconds)

        # Commit effect to append-only ledger
        record = self.ledger.record_effect(
            intent_id=intent_id,
            service=service,
            action=action,
            payload=data,
            idempotency_key=idempotency_key,
        )

        # Fault Hook: CP-B1: Commit effect, then abruptly close socket without sending reply
        if self.fault_config.crash_point == "CP-B1":
            # Force abrupt RST/close on the socket
            try:
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b'\x01\x00\x00\x00\x00\x00\x00\x00')
                self.connection.close()
            except Exception:
                pass
            return

        # Normal response: strictly exclude any intent_id to prevent ground-truth contamination
        resp_payload = {
            "status": "success",
            "effect_id": record.id,
            "service": record.service,
            "action": record.action,
        }
        resp_bytes = json.dumps(resp_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)

    def do_GET(self) -> None:
        # Reconcile lookup endpoints
        path = self.path
        if path.startswith("/payments/lookup"):
            # Lookup by reference or idempotency_key
            pass
        elif path.startswith("/tickets/lookup"):
            pass
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

        self.httpd = HTTPServer((host, port), CustomHandler)
        self.port = self.httpd.server_port
        self.thread: Optional[threading.Thread] = None

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
