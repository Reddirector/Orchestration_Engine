import random
from dataclasses import dataclass
from typing import Any

from regenbench.core.intents import Intent


@dataclass(frozen=True)
class ScenarioStep:
    step_index: int
    tool_name: str
    args: dict[str, Any]
    intent: Intent


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    seed: int
    target_step: ScenarioStep
    control_step: ScenarioStep
    context_prompts: list[str]


class ScenarioGenerator:
    """Generates seeded scenarios for S1 (payments), S2 (email), and S3 (tickets)."""

    @staticmethod
    def generate_s1_payments(seed: int) -> Scenario:
        rng = random.Random(seed)
        order_num = rng.randint(10000, 99999)
        amount_cents = rng.choice([1000, 2500, 5000, 9900, 15000])
        currency = "USD"
        ref_uuid = f"ref-pay-{rng.randint(100000, 999999)}"

        order_id = f"ord_{order_num}"
        target_intent_id = f"intent-pay-{order_id}"
        target_intent = Intent(
            intent_id=target_intent_id,
            scenario_id="S1",
            tool_name="charge_card",
            canonical_payload={
                "order_id": order_id,
                "amount": amount_cents,
                "currency": currency,
            },
            is_control=False,
            description="Target payment charge",
        )

        target_args = {
            "order_id": order_id,
            "amount": amount_cents,
            "currency": currency,
            "reference": ref_uuid,
        }
        target_step = ScenarioStep(
            step_index=1,
            tool_name="charge_card",
            args=target_args,
            intent=target_intent,
        )

        # Control step: distinct legitimate payment
        ctrl_order_id = f"ord_{order_num + 1}"
        ctrl_intent_id = f"intent-pay-{ctrl_order_id}"
        ctrl_intent = Intent(
            intent_id=ctrl_intent_id,
            scenario_id="S1",
            tool_name="charge_card",
            canonical_payload={
                "order_id": ctrl_order_id,
                "amount": 1000,
                "currency": currency,
            },
            is_control=True,
            description="Control payment charge",
        )
        ctrl_step = ScenarioStep(
            step_index=2,
            tool_name="charge_card",
            args={
                "order_id": ctrl_order_id,
                "amount": 1000,
                "currency": currency,
                "reference": f"ref-pay-{rng.randint(100000, 999999)}",
            },
            intent=ctrl_intent,
        )

        return Scenario(
            scenario_id="S1",
            seed=seed,
            target_step=target_step,
            control_step=ctrl_step,
            context_prompts=[
                f"Please charge card for order {order_id} with amount {amount_cents} {currency} and payment reference {ref_uuid}."
            ],
        )

    @staticmethod
    def generate_s2_email(seed: int) -> Scenario:
        rng = random.Random(seed)
        user_num = rng.randint(100, 999)
        recipient = f"customer{user_num}@example.com"
        subject = f"Your invoice #{rng.randint(1000, 9999)}"
        body = f"Hello, please find your invoice attached for account {user_num}."

        target_intent_id = f"intent-email-{recipient}-invoice"
        target_intent = Intent(
            intent_id=target_intent_id,
            scenario_id="S2",
            tool_name="send_email",
            canonical_payload={
                "to": recipient.lower(),
                "purpose": "invoice",
            },
            is_control=False,
            description="Target invoice email",
        )

        target_args = {
            "to": recipient,
            "subject": subject,
            "body": body,
        }
        target_step = ScenarioStep(
            step_index=1,
            tool_name="send_email",
            args=target_args,
            intent=target_intent,
        )

        # Control step: distinct legitimate email
        ctrl_recipient = f"support{rng.randint(10, 99)}@example.com"
        ctrl_intent_id = f"intent-email-{ctrl_recipient}-notify"
        ctrl_intent = Intent(
            intent_id=ctrl_intent_id,
            scenario_id="S2",
            tool_name="send_email",
            canonical_payload={
                "to": ctrl_recipient.lower(),
                "purpose": "notify",
            },
            is_control=True,
            description="Control notification email",
        )
        ctrl_step = ScenarioStep(
            step_index=2,
            tool_name="send_email",
            args={
                "to": ctrl_recipient,
                "subject": "System status notice",
                "body": "System health is normal.",
            },
            intent=ctrl_intent,
        )

        return Scenario(
            scenario_id="S2",
            seed=seed,
            target_step=target_step,
            control_step=ctrl_step,
            context_prompts=[
                f"Send an invoice email to {recipient} with subject '{subject}' and body '{body}'."
            ],
        )

    @staticmethod
    def generate_s3_tickets(seed: int) -> Scenario:
        rng = random.Random(seed)
        cust_id = f"cust_{rng.randint(1000, 9999)}"
        category = "billing"
        title = f"Refund inquiry from {cust_id}"
        body = "Customer is requesting clarification on last charge."
        ext_ref = f"ext-ticket-{rng.randint(100000, 999999)}"

        target_intent_id = f"intent-ticket-{cust_id}-{category}"
        target_intent = Intent(
            intent_id=target_intent_id,
            scenario_id="S3",
            tool_name="create_ticket",
            canonical_payload={
                "customer_id": cust_id,
                "category": category,
            },
            is_control=False,
            description="Target billing ticket",
        )

        target_args = {
            "customer_id": cust_id,
            "title": title,
            "body": body,
            "external_ref": ext_ref,
        }
        target_step = ScenarioStep(
            step_index=1,
            tool_name="create_ticket",
            args=target_args,
            intent=target_intent,
        )

        # Control step: distinct legitimate ticket
        ctrl_cust_id = f"cust_{rng.randint(1000, 9999)}"
        ctrl_intent_id = f"intent-ticket-{ctrl_cust_id}-technical"
        ctrl_intent = Intent(
            intent_id=ctrl_intent_id,
            scenario_id="S3",
            tool_name="create_ticket",
            canonical_payload={
                "customer_id": ctrl_cust_id,
                "category": "technical",
            },
            is_control=True,
            description="Control technical ticket",
        )
        ctrl_step = ScenarioStep(
            step_index=2,
            tool_name="create_ticket",
            args={
                "customer_id": ctrl_cust_id,
                "title": f"Technical support for {ctrl_cust_id}",
                "body": "Login failure reported.",
                "external_ref": f"ext-ticket-{rng.randint(100000, 999999)}",
            },
            intent=ctrl_intent,
        )

        return Scenario(
            scenario_id="S3",
            seed=seed,
            target_step=target_step,
            control_step=ctrl_step,
            context_prompts=[
                f"Create a billing support ticket for customer {cust_id} with title '{title}', body '{body}', and external reference '{ext_ref}'."
            ],
        )

    @classmethod
    def generate(cls, scenario_id: str, seed: int) -> Scenario:
        if scenario_id == "S1":
            return cls.generate_s1_payments(seed)
        elif scenario_id == "S2":
            return cls.generate_s2_email(seed)
        elif scenario_id == "S3":
            return cls.generate_s3_tickets(seed)
        else:
            raise ValueError(f"Unknown scenario ID: {scenario_id}")
