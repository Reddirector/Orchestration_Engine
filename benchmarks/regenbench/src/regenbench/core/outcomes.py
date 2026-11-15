from dataclasses import dataclass
from enum import Enum

from regenbench.core.ledger import EffectLedger


class TargetOutcome(str, Enum):
    OK = "OK"  # Exactly 1 commit, no halt
    DUP = "DUP"  # >= 2 commits (unsafe)
    LOST = "LOST"  # 0 commits, no halt (unsafe)
    HALT_SAFE = "HALT-SAFE"  # 1 commit, halted for human
    HALT_STALL = "HALT-STALL"  # 0 commits, halted for human
    FALSE_BLOCK = "FALSE_BLOCK"  # Legitimate different request falsely blocked


class ControlOutcome(str, Enum):
    OK = "OK"  # Control action executed successfully (>= 1 commit)
    FALSE_BLOCK = "FALSE_BLOCK"  # Legitimate distinct action falsely blocked (0 commits)


@dataclass(frozen=True)
class TrialClassification:
    target_intent_id: str
    target_outcome: TargetOutcome
    target_commits: int
    control_intent_id: str | None
    control_outcome: ControlOutcome | None
    control_commits: int
    halted_for_human: bool
    is_safe: bool
    is_autonomous: bool
    requests_w1: int = 0
    requests_w2: int = 0
    task_runner_invocations_w2: int = 0


class OutcomeOracle:
    """Classifies trial outcomes strictly from the out-of-band effect ledger and halt flags."""

    @staticmethod
    def classify(
        ledger: EffectLedger,
        target_intent_id: str,
        control_intent_id: str | None = None,
        halted: bool = False,
        requests_w1: int = 0,
        requests_w2: int = 0,
        task_runner_invocations_w2: int = 0,
    ) -> TrialClassification:
        target_commits = ledger.count_effects(target_intent_id)

        if target_commits >= 2:
            target_outcome = TargetOutcome.DUP
        elif target_commits == 1:
            target_outcome = TargetOutcome.HALT_SAFE if halted else TargetOutcome.OK
        else:  # target_commits == 0
            target_outcome = TargetOutcome.HALT_STALL if halted else TargetOutcome.LOST

        control_outcome: ControlOutcome | None = None
        control_commits = 0
        if control_intent_id:
            control_commits = ledger.count_effects(control_intent_id)
            if control_commits >= 1:
                control_outcome = ControlOutcome.OK
            else:
                control_outcome = ControlOutcome.FALSE_BLOCK

        is_safe = target_outcome in (
            TargetOutcome.OK,
            TargetOutcome.HALT_SAFE,
            TargetOutcome.HALT_STALL,
        )
        is_autonomous = (target_outcome == TargetOutcome.OK) and (
            control_outcome == ControlOutcome.OK if control_intent_id else True
        )

        return TrialClassification(
            target_intent_id=target_intent_id,
            target_outcome=target_outcome,
            target_commits=target_commits,
            control_intent_id=control_intent_id,
            control_outcome=control_outcome,
            control_commits=control_commits,
            halted_for_human=halted,
            is_safe=is_safe,
            is_autonomous=is_autonomous,
            requests_w1=requests_w1,
            requests_w2=requests_w2,
            task_runner_invocations_w2=task_runner_invocations_w2,
        )
