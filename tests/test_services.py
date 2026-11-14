import pytest
from pathlib import Path
import httpx
from regenbench.core.ledger import EffectLedger
from regenbench.services.server import MockServicesServer
from regenbench.services.payments import PaymentsServiceClient
from regenbench.services.email import EmailServiceClient
from regenbench.services.tickets import TicketsServiceClient


@pytest.fixture
def test_server(tmp_path: Path):
    ledger = EffectLedger(tmp_path / "ledger.db")
    server = MockServicesServer(ledger=ledger)
    server.start()
    yield server, ledger
    server.stop()


def test_services_commit_effects(test_server):
    server, ledger = test_server
    base_url = server.base_url

    # Payments
    pay_client = PaymentsServiceClient(base_url)
    res_pay = pay_client.charge_card(
        order_id="ord_123",
        amount=1000,
        currency="USD",
        reference="ref_1",
        intent_id="intent-pay-1",
        idempotency_key="ik-pay-1",
    )
    assert res_pay["status"] == "success"

    # Email
    email_client = EmailServiceClient(base_url)
    res_email = email_client.send_email(
        to="user@example.com",
        subject="Invoice",
        body="Attached",
        intent_id="intent-email-1",
    )
    assert res_email["status"] == "success"

    # Tickets
    ticket_client = TicketsServiceClient(base_url)
    res_ticket = ticket_client.create_ticket(
        customer_id="cust_1",
        title="Help",
        body="Urgent",
        external_ref="ext_1",
        intent_id="intent-ticket-1",
    )
    assert res_ticket["status"] == "success"

    assert ledger.count_effects("intent-pay-1") == 1
    assert ledger.count_effects("intent-email-1") == 1
    assert ledger.count_effects("intent-ticket-1") == 1


def test_cp_b1_fault_abrupt_disconnect(test_server):
    server, ledger = test_server
    base_url = server.base_url

    # Set fault hook to CP-B1: commit effect then close socket
    server.fault_config.crash_point = "CP-B1"

    pay_client = PaymentsServiceClient(base_url)
    with pytest.raises((httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError)):
        pay_client.charge_card(
            order_id="ord_fail",
            amount=5000,
            currency="USD",
            reference="ref_fail",
            intent_id="intent-pay-fail",
            timeout=2.0,
        )

    # Even though client saw protocol/connection failure, the server committed the effect!
    assert ledger.count_effects("intent-pay-fail") == 1


def test_no_intent_id_in_response_bodies(test_server):
    server, ledger = test_server
    base_url = server.base_url

    def contains_key_recursive(d, key):
        if isinstance(d, dict):
            if key in d:
                return True
            return any(contains_key_recursive(v, key) for v in d.values())
        elif isinstance(d, list):
            return any(contains_key_recursive(item, key) for item in d)
        return False

    pay_client = PaymentsServiceClient(base_url)
    res_pay = pay_client.charge_card("ord_1", 100, "USD", "ref_1", "intent-pay-clean")
    assert not contains_key_recursive(res_pay, "intent_id")

    email_client = EmailServiceClient(base_url)
    res_email = email_client.send_email("u@example.com", "sub", "body", "intent-email-clean")
    assert not contains_key_recursive(res_email, "intent_id")

    ticket_client = TicketsServiceClient(base_url)
    res_ticket = ticket_client.create_ticket("c_1", "t", "b", "ext_1", "intent-ticket-clean")
    assert not contains_key_recursive(res_ticket, "intent_id")


def test_missing_x_intent_id_header_rejected(test_server):
    server, ledger = test_server
    base_url = server.base_url

    count_before = len(ledger.all_effects())
    with httpx.Client() as client:
        resp = client.post(
            f"{base_url}/payments/charge",
            json={"order_id": "ord_no_header", "amount": 100},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    count_after = len(ledger.all_effects())
    assert count_after == count_before


def test_sqlite_wal_journal_mode(tmp_path: Path):
    db_file = tmp_path / "ledger_wal_verify.db"
    ledger = EffectLedger(db_file)
    with ledger._get_connection() as conn:
        cursor = conn.cursor()
        mode = cursor.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode.lower() == "wal"
