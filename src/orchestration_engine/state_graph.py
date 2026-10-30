"""Agentic State Graphs and Cyclic Loops.

Provides cyclic execution graphs, self-correction reflection loops, and persistent
scratchpad memory for autonomous multi-agent AI systems with zero external dependencies.
Unlike DAGs, StateGraphs allow cycles with iteration limits and checkpointed persistence.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import json
import logging
import time
import uuid
from typing import Any, cast

from orchestration_engine.errors import OrchestrationError, WorkflowValidationError
from orchestration_engine.persistence import get_connection

logger = logging.getLogger(__name__)

START = "__start__"
END = "__end__"


@dataclasses.dataclass(frozen=True)
class StateGraphResult:
    """Outcome of a StateGraph invocation."""

    final_state: dict[str, Any]
    node_history: list[str]
    iterations: int
    thread_id: str


class StateCheckpointer:
    """Persistent SQLite checkpointer for state graph snapshots."""

    def __init__(self, db_path: str = "orchestration.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_graph_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    node_name TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sg_thread ON "
                "state_graph_checkpoints(thread_id, step_index)"
            )

    def save_checkpoint(
        self,
        *,
        thread_id: str,
        step_index: int,
        node_name: str,
        state: dict[str, Any],
        timestamp: float | None = None,
    ) -> str:
        cid = uuid.uuid4().hex
        ts = timestamp if timestamp is not None else time.time()
        state_str = json.dumps(state)
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO state_graph_checkpoints (
                    checkpoint_id, thread_id, step_index, node_name, state_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cid, thread_id, step_index, node_name, state_str, ts),
            )
        return cid

    def get_latest_checkpoint(self, thread_id: str) -> dict[str, Any] | None:
        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.execute(
                """
                SELECT state_json FROM state_graph_checkpoints
                WHERE thread_id = ? ORDER BY step_index DESC LIMIT 1
                """,
                (thread_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return cast(dict[str, Any], json.loads(row[0]))


class CompiledStateGraph:
    """Compiled runnable state graph supporting cyclic execution and checkpointing."""

    def __init__(
        self,
        *,
        nodes: dict[str, collections.abc.Callable[[dict[str, Any]], dict[str, Any] | None]],
        edges: dict[str, str],
        conditional_edges: dict[
            str,
            tuple[
                collections.abc.Callable[[dict[str, Any]], str],
                dict[str, str] | None,
            ],
        ],
        entry_point: str,
        checkpointer: StateCheckpointer | None = None,
        max_iterations: int = 50,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.conditional_edges = conditional_edges
        self.entry_point = entry_point
        self.checkpointer = checkpointer
        self.max_iterations = max_iterations

    def get_state(self, thread_id: str) -> dict[str, Any] | None:
        """Retrieve the latest checkpointed state for a thread."""
        if not self.checkpointer:
            return None
        return self.checkpointer.get_latest_checkpoint(thread_id)

    def invoke(
        self,
        initial_state: dict[str, Any],
        *,
        thread_id: str | None = None,
    ) -> StateGraphResult:
        """Execute the cyclic state graph until reaching END or max_iterations."""
        current_thread_id = thread_id or uuid.uuid4().hex
        state: dict[str, Any] = dict(initial_state)

        # Resume from checkpoint if thread exists
        if self.checkpointer and thread_id:
            existing = self.checkpointer.get_latest_checkpoint(thread_id)
            if existing is not None:
                state = {**state, **existing}

        current_node = self.entry_point
        history: list[str] = []
        iteration = 0

        while current_node != END and iteration < self.max_iterations:
            if current_node not in self.nodes:
                raise OrchestrationError(f"Node '{current_node}' not found in StateGraph")

            history.append(current_node)
            node_fn = self.nodes[current_node]

            try:
                node_updates = node_fn(dict(state))
            except Exception as exc:
                logger.error("StateGraph node '%s' raised exception: %s", current_node, exc)
                raise

            # Merge returned updates into global state
            if isinstance(node_updates, dict):
                state.update(node_updates)

            iteration += 1

            if self.checkpointer:
                self.checkpointer.save_checkpoint(
                    thread_id=current_thread_id,
                    step_index=iteration,
                    node_name=current_node,
                    state=state,
                )

            # Determine next node
            if current_node in self.conditional_edges:
                router_fn, path_map = self.conditional_edges[current_node]
                decision = router_fn(dict(state))
                if path_map and decision in path_map:
                    current_node = path_map[decision]
                else:
                    current_node = decision
            elif current_node in self.edges:
                current_node = self.edges[current_node]
            else:
                # No outgoing edge defaults to END
                current_node = END

        if iteration >= self.max_iterations and current_node != END:
            logger.warning(
                "StateGraph thread '%s' reached max iterations (%d) before END",
                current_thread_id,
                self.max_iterations,
            )

        return StateGraphResult(
            final_state=state,
            node_history=history,
            iterations=iteration,
            thread_id=current_thread_id,
        )


class StateGraph:
    """Builder for cyclic agentic state graphs."""

    def __init__(self) -> None:
        self._nodes: dict[
            str, collections.abc.Callable[[dict[str, Any]], dict[str, Any] | None]
        ] = {}
        self._edges: dict[str, str] = {}
        self._conditional_edges: dict[
            str,
            tuple[
                collections.abc.Callable[[dict[str, Any]], str],
                dict[str, str] | None,
            ],
        ] = {}
        self._entry_point: str | None = None

    def add_node(
        self,
        name: str,
        action: collections.abc.Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> StateGraph:
        """Register a node with an action callable taking and returning state updates."""
        if name in (START, END):
            raise WorkflowValidationError(f"Cannot use reserved node name '{name}'")
        self._nodes[name] = action
        return self

    def add_edge(self, from_node: str, to_node: str) -> StateGraph:
        """Register a static directed edge between nodes."""
        if from_node == START:
            self._entry_point = to_node
        else:
            self._edges[from_node] = to_node
        return self

    def add_conditional_edges(
        self,
        source: str,
        router: collections.abc.Callable[[dict[str, Any]], str],
        path_map: dict[str, str] | None = None,
    ) -> StateGraph:
        """Register conditional routing logic deciding the next node dynamically."""
        self._conditional_edges[source] = (router, path_map)
        return self

    def set_entry_point(self, node: str) -> StateGraph:
        """Set the initial node to execute."""
        self._entry_point = node
        return self

    def compile(
        self,
        *,
        checkpointer: StateCheckpointer | None = None,
        max_iterations: int = 50,
    ) -> CompiledStateGraph:
        """Validate and compile into an executable CompiledStateGraph."""
        if not self._entry_point:
            raise WorkflowValidationError("StateGraph must have an entry point set")
        if self._entry_point not in self._nodes:
            raise WorkflowValidationError(
                f"Entry point '{self._entry_point}' is not registered as a node"
            )

        return CompiledStateGraph(
            nodes=dict(self._nodes),
            edges=dict(self._edges),
            conditional_edges=dict(self._conditional_edges),
            entry_point=self._entry_point,
            checkpointer=checkpointer,
            max_iterations=max_iterations,
        )
