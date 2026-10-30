"""Agentic Reflection and Self-Correction Loop.

Demonstrates cyclic AI agent graph execution with zero external dependencies:
1. StateGraph with cyclic loops for generate -> test -> critique -> refine.
2. Conditional edge routing based on runtime state evaluations.
3. Iteration bounding to prevent infinite loops (max_iterations safeguard).
4. SQLite thread checkpointing for resumption and audit trails.
"""

from __future__ import annotations

import tempfile
from typing import Any

from orchestration_engine import (
    END,
    START,
    StateCheckpointer,
    StateGraph,
)


def run_agentic_loop() -> None:
    print("=" * 70)
    print("🤖 Agentic State Graph: Code Generation with Reflection & Self-Correction")
    print("=" * 70)

    # 1. Initialize State Graph
    builder = StateGraph()

    # 2. Define Agent Nodes
    def draft_agent(state: dict[str, Any]) -> dict[str, Any]:
        prompt = state.get("task", "Write a fibonacci function")
        print(f"\n[Draft Agent] Received prompt: '{prompt}'")
        return {
            "code": "def fib(n):\n    if n <= 1: return 1\n    return fib(n-1) + fib(n-2)",
            "tests_passed": False,
            "critique": "Not yet evaluated",
            "iterations": state.get("iterations", 0) + 1,
        }

    def evaluation_agent(state: dict[str, Any]) -> dict[str, Any]:
        iters = state.get("iterations", 1)
        print(f"[Critic Agent] Testing candidate code (Iteration {iters})...")

        # Simulate automated unit test evaluation
        if iters >= 2:
            print("  ✓ Tests passed! Base cases fib(0)=0 and fib(1)=1 properly handled.")
            return {
                "tests_passed": True,
                "critique": "Passes all test cases and edge boundaries.",
            }

        print("  ✗ Test failure: fib(0) should be 0, but current code returns 1.")
        return {
            "tests_passed": False,
            "critique": "Base case off-by-one: fib(0) evaluates to 1 instead of 0.",
        }

    def refinement_agent(state: dict[str, Any]) -> dict[str, Any]:
        critique = state.get("critique", "")
        iters = state.get("iterations", 1)
        print(f"[Refine Agent] Addressing feedback: '{critique}'")
        refined_code = (
            "def fib(n):\n"
            "    if n <= 0: return 0\n"
            "    if n == 1: return 1\n"
            "    return fib(n-1) + fib(n-2)"
        )
        return {
            "code": refined_code,
            "critique": "Corrected base cases for n=0 and n=1",
            "iterations": iters + 1,
        }

    def finalize_agent(state: dict[str, Any]) -> dict[str, Any]:
        print("[Finalize] Packaging validated solution for release.")
        return {"status": "SUCCESS"}

    # 3. Register Nodes
    builder.add_node("draft", draft_agent)
    builder.add_node("evaluate", evaluation_agent)
    builder.add_node("refine", refinement_agent)
    builder.add_node("finalize", finalize_agent)

    # 4. Define Graph Topology & Cyclic Conditional Edges
    builder.add_edge(START, "draft")
    builder.add_edge("draft", "evaluate")

    def route_evaluation(state: dict[str, Any]) -> str:
        if state.get("tests_passed", False):
            return "finalize"
        return "refine"

    builder.add_conditional_edges(
        "evaluate",
        route_evaluation,
        {"finalize": "finalize", "refine": "refine"},
    )
    # Complete the cyclic loop: refine -> evaluate
    builder.add_edge("refine", "evaluate")
    builder.add_edge("finalize", END)

    # 5. Compile with SQLite Checkpointer
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = tmp.name
        checkpointer = StateCheckpointer(db_path)
        app = builder.compile(checkpointer=checkpointer, max_iterations=10)

        initial_state = {
            "task": "Implement zero-indexed fibonacci in Python",
            "iterations": 0,
        }

        print("\n🚀 Executing Agent Graph with thread checkpointing...")
        res = app.invoke(
            initial_state,
            thread_id="thread-agent-42",
        )
        final_state = res.final_state

        print("\n" + "=" * 70)
        print("🏆 Final Agent State:")
        print(f"  Execution Path: {' -> '.join(res.node_history)}")
        print(f"  Total Iterations: {res.iterations}")
        print(f"  Tests Passed: {final_state['tests_passed']}")
        print(f"  Critique: {final_state['critique']}")
        print(f"  Generated Code:\n{final_state['code']}")

        # 6. Verify Checkpointer Persistence
        saved_state = app.get_state("thread-agent-42")
        assert saved_state is not None
        print(
            f"\n💾 Checkpoint Verified: Thread 'thread-agent-42' state captured "
            f"({len(saved_state)} keys saved)."
        )


if __name__ == "__main__":
    run_agentic_loop()
