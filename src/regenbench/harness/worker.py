import argparse
import json
import sys
from pathlib import Path
from typing import Any

from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from regenbench.faults.crashpoints import CrashInjector
from regenbench.guards.agentraas_adapter import AgentRaaSAdapter
from regenbench.guards.analyzer import SemanticAnalyzerGuard
from regenbench.guards.call4agents_adapter import Call4AgentsAdapter
from regenbench.guards.idempotent_tools_adapter import IdempotentToolsAdapter
from regenbench.guards.intentguard.guard import IntentGuard
from regenbench.guards.none import NoGuard
from regenbench.guards.server_key import ServerIdempotencyKeyGuard
from regenbench.guards.stepkey import StepKeyGuard
from regenbench.services.email import EmailServiceClient
from regenbench.services.payments import PaymentsServiceClient
from regenbench.services.tickets import TicketsServiceClient


def get_guard(guard_name: str, run_id: str, workdir: Path):
    if guard_name == "G0":
        guard = NoGuard()
    elif guard_name == "G1":
        guard = Call4AgentsAdapter(use_workaround_key=False)
    elif guard_name == "G1_workaround":
        guard = Call4AgentsAdapter(use_workaround_key=True)
    elif guard_name == "G2":
        guard = AgentRaaSAdapter(use_workaround_key=False)
    elif guard_name == "G2_workaround":
        guard = AgentRaaSAdapter(use_workaround_key=True)
    elif guard_name == "G3a":
        guard = IdempotentToolsAdapter(mode="default")
    elif guard_name == "G3b":
        guard = IdempotentToolsAdapter(mode="context")
    elif guard_name == "G5":
        guard = StepKeyGuard()
    elif guard_name == "G6":
        guard = ServerIdempotencyKeyGuard()
    elif guard_name == "G4":
        guard = IntentGuard()
    elif guard_name == "G7":
        guard = SemanticAnalyzerGuard()
    else:
        raise ValueError(f"Unknown guard: {guard_name}")
    guard.setup(run_id, workdir)
    return guard


def execute_call(service_url: str, tool_name: str, args: dict[str, Any], intent_id: str):
    idem_key = args.get("idempotency_key")
    if tool_name == "charge_card":
        client = PaymentsServiceClient(service_url)
        return client.charge_card(
            order_id=args["order_id"],
            amount=args["amount"],
            currency=args["currency"],
            reference=args.get("reference", ""),
            intent_id=intent_id,
            idempotency_key=idem_key,
        )
    elif tool_name == "send_email":
        client = EmailServiceClient(service_url)
        return client.send_email(
            to=args["to"],
            subject=args["subject"],
            body=args["body"],
            intent_id=intent_id,
            idempotency_key=idem_key,
        )
    elif tool_name == "create_ticket":
        client = TicketsServiceClient(service_url)
        return client.create_ticket(
            customer_id=args["customer_id"],
            title=args["title"],
            body=args["body"],
            external_ref=args.get("external_ref", ""),
            intent_id=intent_id,
            idempotency_key=idem_key,
        )
    else:
        raise ValueError(f"Unknown tool: {tool_name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["worker1", "worker2"], required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--guard", required=True)
    parser.add_argument("--crash-point", default="")
    parser.add_argument("--drift-type", default="D0")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--service-url", required=True)
    args = parser.parse_args()

    workdir = Path(args.workdir)
    scenario = ScenarioGenerator.generate(args.scenario, seed=args.seed)
    guard = get_guard(args.guard, args.run_id, workdir)

    target_step = scenario.target_step
    ctrl_step = scenario.control_step

    def target_invoker(call_args):
        CrashInjector.maybe_crash(args.crash_point, "CP-A")
        try:
            res = execute_call(
                args.service_url,
                target_step.tool_name,
                call_args,
                intent_id=target_step.intent.intent_id,
            )
        except Exception as e:
            CrashInjector.maybe_crash(args.crash_point, "CP-B2")
            raise e

        CrashInjector.maybe_crash(args.crash_point, "CP-B2")
        CrashInjector.maybe_crash(args.crash_point, "CP-C")
        return res

    wrapped_target = guard.wrap(target_step.tool_name, target_invoker)

    if args.role == "worker1":
        try:
            wrapped_target(target_step.args)
            CrashInjector.maybe_crash(args.crash_point, "CP-D")
        except Exception:
            pass
        sys.exit(0)

    elif args.role == "worker2":
        guard.on_resume(args.run_id)
        mutated_args = DriftMutator.mutate(args.drift_type, target_step.args, seed=args.seed)

        try:
            wrapped_target(mutated_args)
        except Exception:
            pass

        ctrl_invoker = guard.wrap(
            ctrl_step.tool_name,
            lambda c_args: execute_call(
                args.service_url,
                ctrl_step.tool_name,
                c_args,
                intent_id=ctrl_step.intent.intent_id,
            ),
        )
        try:
            ctrl_invoker(ctrl_step.args)
        except Exception:
            pass

        halted = guard.halted()
        with open(workdir / "worker2_halt.json", "w") as f:
            json.dump([h.__dict__ for h in halted], f)

        sys.exit(0)


if __name__ == "__main__":
    main()
