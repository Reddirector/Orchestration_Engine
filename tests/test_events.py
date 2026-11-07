"""Tests for Event-Driven Webhooks and Reactive Topic Bus."""

from __future__ import annotations

import json
import urllib.request

import pytest

from orchestration_engine.events import Event, EventBus, WebhookServer


def test_event_bus_publish_and_wildcard_matching() -> None:
    bus = EventBus()
    received_order: list[Event] = []
    received_all: list[Event] = []

    # Subscription with wildcard
    bus.subscribe("orders.*", lambda e: received_order.append(e))
    # Catch-all subscription
    bus.subscribe("*", lambda e: received_all.append(e))

    # Publish matching
    e1 = bus.publish("orders.created", {"order_id": 101, "total": 99.0})
    # Publish non-matching for orders.*
    e2 = bus.publish("users.signup", {"user_id": "u-42"})

    assert len(received_order) == 1
    assert received_order[0].topic == "orders.created"
    assert received_order[0].payload["order_id"] == 101

    assert len(received_all) == 2
    assert [e.event_id for e in received_all] == [e1.event_id, e2.event_id]


def test_event_bus_filter_predicate_and_unsubscribe() -> None:
    bus = EventBus()
    high_value_orders: list[Event] = []

    sub_id = bus.subscribe(
        "orders.created",
        lambda e: high_value_orders.append(e),
        filter_fn=lambda e: e.payload.get("amount", 0) >= 1000,
    )

    bus.publish("orders.created", {"order_id": 1, "amount": 250})
    assert len(high_value_orders) == 0  # Filtered out

    bus.publish("orders.created", {"order_id": 2, "amount": 1500})
    assert len(high_value_orders) == 1

    # Unsubscribe
    assert bus.unsubscribe(sub_id) is True
    bus.publish("orders.created", {"order_id": 3, "amount": 5000})
    assert len(high_value_orders) == 1  # Not received after unsubscribe


def test_webhook_server_http_dispatch() -> None:
    bus = EventBus()
    captured_webhooks: list[Event] = []
    bus.subscribe("stripe", lambda e: captured_webhooks.append(e))

    # Bind to port 0 (dynamic available port)
    server = WebhookServer(bus, host="127.0.0.1", port=0, secret_token="my-secret-key")
    server.start()

    try:
        url = f"http://127.0.0.1:{server.port}/webhook/stripe"

        # 1. Unauthorized request (missing token)
        req_unauth = urllib.request.Request(
            url,
            data=json.dumps({"type": "charge.failed"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_unauth:
            urllib.request.urlopen(req_unauth)
        assert exc_unauth.value.code == 401

        # 2. Authorized request
        req_auth = urllib.request.Request(
            url,
            data=json.dumps({"type": "payment_intent.succeeded", "amount": 4200}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer my-secret-key",
            },
        )
        with urllib.request.urlopen(req_auth) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert "event_id" in data

        assert len(captured_webhooks) == 1
        assert captured_webhooks[0].topic == "stripe"
        assert captured_webhooks[0].payload["type"] == "payment_intent.succeeded"

    finally:
        server.stop()
