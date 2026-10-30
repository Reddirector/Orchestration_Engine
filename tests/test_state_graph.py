"""Tests for Agentic State Graphs and Cyclic Loops."""

from __future__ import annotations

from typing import Any

import pytest

from orchestration_engine.errors import WorkflowValidationError
from orchestration_engine.state_graph import (
    END,
    START,
    StateCheckpointer,
    StateGraph,
)


def test_state_graph_reflection_loop() -> None:
    # Autonomous agent loop: generate -> review -> if score < 0.8: loop back
    graph = StateGraph()

    def generate_code(state: dict[str, Any]) -> dict[str, Any]:
        attempts = state.get("attempts", 0) + 1
        return {"code": f"def hello_{attempts}(): pass", "attempts": attempts}

    def review_code(state: dict[str, Any]) -> dict[str, Any]:
        # Score increases with attempts
        score = 0.5 if state["attempts"] < 3 else 0.95
        return {"review_score": score}

    def route_decision(state: dict[str, Any]) -> str:
        if state.get("review_score", 0.0) >= 0.8:
            return END
        return "generate"

    graph.add_node("generate", generate_code)
    graph.add_node("review", review_code)
    graph.set_entry_point("generate")
    graph.add_edge("generate", "review")
    graph.add_conditional_edges("review", route_decision)

    compiled = graph.compile()
    res = compiled.invoke({"task": "write function"})

    assert res.final_state["attempts"] == 3
    assert res.final_state["review_score"] == 0.95
    assert res.node_history == ["generate", "review", "generate", "review", "generate", "review"]


def test_state_graph_max_iterations_cap() -> None:
    graph = StateGraph()

    def endless(state: dict[str, Any]) -> dict[str, Any]:
        return {"count": state.get("count", 0) + 1}

    graph.add_node("loop", endless)
    graph.set_entry_point("loop")
    graph.add_edge("loop", "loop")

    compiled = graph.compile(max_iterations=10)
    res = compiled.invoke({"count": 0})

    assert res.iterations == 10
    assert res.final_state["count"] == 10


def test_state_graph_sqlite_checkpoints(tmp_path: Any) -> None:
    db = str(tmp_path / "sg.db")
    checkpointer = StateCheckpointer(db)

    graph = StateGraph()

    def step_a(state: dict[str, Any]) -> dict[str, Any]:
        return {"a": 1}

    def step_b(state: dict[str, Any]) -> dict[str, Any]:
        return {"b": state.get("a", 0) + 2}

    graph.add_node("step_a", step_a)
    graph.add_node("step_b", step_b)
    graph.set_entry_point("step_a")
    graph.add_edge("step_a", "step_b")
    graph.add_edge("step_b", END)

    compiled = graph.compile(checkpointer=checkpointer)
    thread_id = "thread-agent-1"
    res = compiled.invoke({}, thread_id=thread_id)

    assert res.final_state == {"a": 1, "b": 3}
    assert checkpointer.get_latest_checkpoint(thread_id) == {"a": 1, "b": 3}
    assert compiled.get_state(thread_id) == {"a": 1, "b": 3}


def test_state_graph_validation_errors() -> None:
    graph = StateGraph()
    with pytest.raises(WorkflowValidationError):
        graph.add_node(START, lambda s: s)

    with pytest.raises(WorkflowValidationError):
        graph.add_node(END, lambda s: s)

    with pytest.raises(WorkflowValidationError):
        graph.compile()  # No entry point
