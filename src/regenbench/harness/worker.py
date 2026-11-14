import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from regenbench.core.scenario import ScenarioGenerator
from regenbench.drift.mutators import DriftMutator
from regenbench.faults.crashpoints import CrashInjector
from regenbench.guards.none import NoGuard
from regenbench.guards.call4agents_adapter import Call4AgentsAdapter
from regenbench.services.payments import PaymentsServiceClient
from regenbench.services.email import EmailServiceClient
from regenbench.services.tickets import TicketsServiceClient


def get_guard(guard_name: str, run_id: str, workdir: Path):
    if guard_name == "G0":
        guard = NoGuard()
    elif guard_name == "G1":
        guard = Call4AgentsAdapter(use_workaround_key=False)
    elif guard_name == "G1_workaround":
        guard = Call4AgentsAdapter(use_workaround_key=True)
    else:
        raise ValueError(f"Unknown guard: {guard_name}")
    guard.setup(run_id, workdir)
    return guard


def execute_call(service_url: str, tool_name: str, args: dict[str, Any], intent_id: str):
    if tool_name == "charge_card":
        client = PaymentsServiceClient(service_url)
        return client.charge_card(
            order_id=args["order_id"],
            amount=args["amount"],
            currency=args["currency"],
            reference=args.get("reference", ""),
            intent_id=intent_id,
        )
    elif tool_name == "send_email":
        client = EmailServiceClient(service_url)
        return client.send_email(
            to=args["to"],
            subject=args["subject"],
            body=args["body"],
            intent_id=intent_id,
        )
    elif tool_name == "create_ticket":
        client = TicketsServiceClient(service_url)
        return client.create_ticket(
            customer_id=args["customer_id"],
            title=args["title"],
            body=args["body"],
            external_ref=args.get("external_ref", ""),
            intent_id=intent_id,
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
        # CP-A: Crash after recording intent, before service call
        CrashInjector.maybe_crash(args.crash_point, "CP-A")
        
        try:
            res = execute_call(
                args.service_url,
                target_step.tool_name,
                call_args,
                intent_id=target_step.intent.intent_id,
            )
        except Exception as e:
            # CP-B2: If worker-side kill after commit but before response processed
            CrashInjector.maybe_crash(args.crash_point, "CP-B2")
            raise e

        # CP-B2 for clean responses
        CrashInjector.maybe_crash(args.crash_point, "CP-B2")
        # CP-C: Response received, before guard stores result
        CrashInjector.maybe_crash(args.crash_point, "CP-C")
        return res

    wrapped_target = guard.wrap(target_step.tool_name, target_invoker)

    if args.role == "worker1":
        # Initial execution
        try:
            res = wrapped_target(target_step.args)
            # CP-D: Guard recorded result, before agent checkpoint saved
            CrashInjector.maybe_crash(args.crash_point, "CP-D")
        except Exception as exc:
            pass
        sys.exit(0)

    elif args.role == "worker2":
        # Resume worker: re-issues step with mutated arguments
        guard.on_resume(args.run_id)
        mutated_args = DriftMutator.mutate(args.drift_type, target_step.args, seed=args.seed)

        try:
            wrapped_target(mutated_args)
        except Exception:
            pass

        # Execute control action
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

        # Dump halt state if any
        halted = guard.halted()
        with open(workdir / "worker2_halt.json", "w") as f:
            json.dump([h.__dict__ for h in halted], f)

        sys.exit(0)


if __name__ == "__main__":
    main()
