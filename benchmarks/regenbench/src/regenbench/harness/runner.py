import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from regenbench.core.env import EnvironmentRecord
from regenbench.core.ledger import EffectLedger
from regenbench.core.outcomes import ControlOutcome, OutcomeOracle, TargetOutcome, TrialClassification
from regenbench.core.scenario import ScenarioGenerator
from regenbench.services.server import MockServicesServer


class TrialRunner:
    """Runs a single trial by launching Worker 1, injecting crash, resuming with Worker 2, and calling Oracle."""

    def __init__(self, results_path: Path | None = None):
        self.results_path = results_path

    def run_trial(
        self,
        scenario_id: str,
        guard_id: str,
        crash_point: str,
        drift_type: str,
        seed: int = 42,
        workdir: Path | None = None,
    ) -> TrialClassification:
        if workdir is None:
            temp_dir = tempfile.mkdtemp()
            workdir = Path(temp_dir)
        else:
            workdir.mkdir(parents=True, exist_ok=True)

        run_id = f"trial-{uuid.uuid4().hex[:8]}"
        ledger_path = workdir / "effects_ledger.db"
        ledger = EffectLedger(ledger_path)

        # Start mock services server
        server = MockServicesServer(ledger=ledger)
        if crash_point == "CP-B1":
            server.fault_config.crash_point = "CP-B1"
        elif crash_point == "CP-E":
            # Timeout / delay fault
            server.fault_config.delay_seconds = 2.0
        server.start()

        env_rec = EnvironmentRecord.capture()
        scenario = ScenarioGenerator.generate(scenario_id, seed=seed)

        # 1. Spawn Worker 1 in separate OS process
        server.set_phase("w1")
        cmd_w1 = [
            sys.executable,
            "-m",
            "regenbench.harness.worker",
            "--role",
            "worker1",
            "--scenario",
            scenario_id,
            "--seed",
            str(seed),
            "--guard",
            guard_id,
            "--crash-point",
            crash_point,
            "--drift-type",
            drift_type,
            "--run-id",
            run_id,
            "--workdir",
            str(workdir),
            "--service-url",
            server.base_url,
        ]

        proc1 = subprocess.run(cmd_w1, capture_output=True, text=True)
        worker1_exit_code = proc1.returncode

        # 2. Spawn Worker 2 in separate OS process (resume)
        server.set_phase("w2")
        cmd_w2 = [
            sys.executable,
            "-m",
            "regenbench.harness.worker",
            "--role",
            "worker2",
            "--scenario",
            scenario_id,
            "--seed",
            str(seed),
            "--guard",
            guard_id,
            "--crash-point",
            "",
            "--drift-type",
            drift_type,
            "--run-id",
            run_id,
            "--workdir",
            str(workdir),
            "--service-url",
            server.base_url,
        ]

        proc2 = subprocess.run(cmd_w2, capture_output=True, text=True)
        worker2_exit_code = proc2.returncode

        # Stop server
        server.stop()

        # Check halt state from worker 2
        halted = False
        halt_file = workdir / "worker2_halt.json"
        if halt_file.exists():
            try:
                halt_data = json.loads(halt_file.read_text())
                if len(halt_data) > 0:
                    halted = True
            except Exception:
                pass

        invocations_file = workdir / "worker2_task_runner_invocations.txt"
        task_runner_invocations_w2 = 0
        if invocations_file.exists():
            try:
                task_runner_invocations_w2 = int(invocations_file.read_text().strip())
            except Exception:
                pass

        # 3. Classify outcome via Oracle
        if drift_type in ("N1", "N2", "N3"):
            n_intent_id = f"{scenario.target_step.intent.intent_id}_{drift_type}"
            n_commits = ledger.count_effects(n_intent_id)
            target_outcome = TargetOutcome.OK if n_commits >= 1 else TargetOutcome.FALSE_BLOCK
            target_commits = n_commits

            ctrl_commits = ledger.count_effects(scenario.control_step.intent.intent_id)
            ctrl_outcome = ControlOutcome.OK if ctrl_commits >= 1 else ControlOutcome.FALSE_BLOCK

            req_w1 = ledger.count_requests(scenario.target_step.intent.intent_id, phase="w1")
            req_w2 = ledger.count_requests(n_intent_id, phase="w2")

            classification = TrialClassification(
                target_intent_id=n_intent_id,
                target_outcome=target_outcome,
                target_commits=target_commits,
                control_intent_id=scenario.control_step.intent.intent_id,
                control_outcome=ctrl_outcome,
                control_commits=ctrl_commits,
                halted_for_human=halted,
                is_safe=(target_outcome == TargetOutcome.OK),
                is_autonomous=(target_outcome == TargetOutcome.OK and ctrl_outcome == ControlOutcome.OK),
                requests_w1=req_w1,
                requests_w2=req_w2,
                task_runner_invocations_w2=task_runner_invocations_w2,
            )
        else:
            req_w1 = ledger.count_requests(scenario.target_step.intent.intent_id, phase="w1")
            req_w2 = ledger.count_requests(scenario.target_step.intent.intent_id, phase="w2")

            classification = OutcomeOracle.classify(
                ledger=ledger,
                target_intent_id=scenario.target_step.intent.intent_id,
                control_intent_id=scenario.control_step.intent.intent_id,
                halted=halted,
                requests_w1=req_w1,
                requests_w2=req_w2,
                task_runner_invocations_w2=task_runner_invocations_w2,
            )

        result_row = {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "guard_id": guard_id,
            "crash_point": crash_point,
            "drift_type": drift_type,
            "seed": seed,
            "target_outcome": classification.target_outcome.value,
            "control_outcome": classification.control_outcome.value
            if classification.control_outcome
            else None,
            "target_commits": classification.target_commits,
            "control_commits": classification.control_commits,
            "requests_w1": classification.requests_w1,
            "requests_w2": classification.requests_w2,
            "task_runner_invocations_w2": classification.task_runner_invocations_w2,
            "halted": classification.halted_for_human,
            "worker1_exit_code": worker1_exit_code,
            "worker2_exit_code": worker2_exit_code,
            "env": env_rec.to_dict(),
        }

        if self.results_path:
            self.results_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.results_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result_row) + "\n")

        return classification
