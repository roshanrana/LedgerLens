"""LangGraph wiring for the reconciliation workflow (docs/05 section 2).

START -> load_run_context -> ... -> generate_report -> [gate]
gate:  gated and review tasks -> await_review -> finalize_run -> END
       otherwise              -> finalize_run -> END

The checkpointed ``GraphState`` holds ids and counters only. The heavy ``WorkflowState``
(transactions, pairs, decisions) lives on the workflow instance for the duration of one
``invoke`` and never enters a checkpoint; at the interrupt everything it holds has already
been written to SQLite by ``persist_decisions``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Iterator, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

if TYPE_CHECKING:
    import sqlite3

    from ledgerlens.agents.workflow import ReconciliationWorkflow
    from ledgerlens.persistence.store import SQLiteStore


ENGINE_NODES: tuple[str, ...] = (
    "load_run_context",
    "normalize_batch",
    "generate_candidates",
    "apply_exact_matches",
    "apply_rule_matches",
    "score_fuzzy_candidates",
    "adjudicate_ambiguous_pairs",
    "route_review_tasks",
    "surface_unmatched_transactions",
    "persist_decisions",
    "generate_report",
)
AWAIT_REVIEW = "await_review"
FINALIZE_RUN = "finalize_run"
NODE_NAMES: tuple[str, ...] = (*ENGINE_NODES, AWAIT_REVIEW, FINALIZE_RUN)
START_NODE = "__start__"

MODE_MEMORY = "memory"
MODE_PERSISTENT = "persistent"


class GraphState(TypedDict, total=False):
    """Checkpointed cursor over a run: ids and counters only (design decision D-2)."""

    run_id: str
    client_id: str
    mode: str
    gated: bool
    stage: str
    node_trace: list[str]
    candidate_pair_ids: list[str]
    review_task_ids: list[str]
    decision_counts: dict[str, int]
    llm_budget_remaining: int
    awaiting_review: bool
    reviewer: str | None
    review_note: str | None
    report_markdown: str | None
    finalized: bool


def initial_graph_state(
    *,
    run_id: str,
    client_id: str,
    mode: str,
    gated: bool,
    llm_budget_remaining: int,
) -> GraphState:
    return GraphState(
        run_id=run_id,
        client_id=client_id,
        mode=mode,
        gated=gated,
        stage=START_NODE,
        node_trace=[],
        candidate_pair_ids=[],
        review_task_ids=[],
        decision_counts={},
        llm_budget_remaining=llm_budget_remaining,
        awaiting_review=False,
        reviewer=None,
        review_note=None,
        report_markdown=None,
        finalized=False,
    )


def run_config(run_id: str) -> dict[str, Any]:
    """LangGraph config for a run: ``thread_id`` is the run id."""
    return {"configurable": {"thread_id": run_id}}


def route_after_report(state: GraphState) -> str:
    """The gate: interrupt for human review only when the run is gated and has open tasks."""
    if state.get("gated") and state.get("review_task_ids"):
        return AWAIT_REVIEW
    return FINALIZE_RUN


def build_graph(workflow: ReconciliationWorkflow, checkpointer: BaseCheckpointSaver):
    """Compile the thirteen-node reconciliation graph with ``workflow`` bound into every node."""
    graph: StateGraph = StateGraph(GraphState)
    for name in ENGINE_NODES:
        graph.add_node(name, _engine_node(workflow, name))
    graph.add_node(AWAIT_REVIEW, _await_review)
    graph.add_node(FINALIZE_RUN, _finalize_node(workflow))

    graph.add_edge(START, ENGINE_NODES[0])
    for previous, following in zip(ENGINE_NODES, ENGINE_NODES[1:]):
        graph.add_edge(previous, following)
    graph.add_conditional_edges(
        ENGINE_NODES[-1],
        route_after_report,
        {AWAIT_REVIEW: AWAIT_REVIEW, FINALIZE_RUN: FINALIZE_RUN},
    )
    graph.add_edge(AWAIT_REVIEW, FINALIZE_RUN)
    graph.add_edge(FINALIZE_RUN, END)
    return graph.compile(checkpointer=checkpointer)


def _engine_node(workflow: ReconciliationWorkflow, name: str) -> Callable[[GraphState], dict[str, Any]]:
    is_last_engine_node = name == ENGINE_NODES[-1]

    def node(state: GraphState) -> dict[str, Any]:
        update = workflow.run_node(name, state)
        if is_last_engine_node:
            update["awaiting_review"] = route_after_report({**state, **update}) == AWAIT_REVIEW
        return update

    node.__name__ = name
    return node


def _await_review(state: GraphState) -> dict[str, Any]:
    """Pause until a reviewer completes the review; the resume value is validated by the service (D-4)."""
    resume = interrupt(
        {
            "run_id": state["run_id"],
            "open_review_task_ids": list(state.get("review_task_ids", [])),
            "preliminary_report": True,
        }
    )
    payload = resume if isinstance(resume, dict) else {}
    return {
        "stage": AWAIT_REVIEW,
        "node_trace": [*state.get("node_trace", []), AWAIT_REVIEW],
        "awaiting_review": False,
        "reviewer": payload.get("reviewer"),
        "review_note": payload.get("note", ""),
    }


def _finalize_node(workflow: ReconciliationWorkflow) -> Callable[[GraphState], dict[str, Any]]:
    def finalize_run(state: GraphState) -> dict[str, Any]:
        return workflow.finalize_run(state)

    return finalize_run


class StoreCheckpointer(SqliteSaver):
    """``SqliteSaver`` over ``store.db_path`` that shares the store's connection.

    Two facts force the shared connection: a second SQLite connection cannot write
    checkpoints while the store's run transaction holds the WAL write lock, and the stock
    saver commits after every write, which would break the run's atomicity. Sharing the
    connection and deferring the commit while the store is inside ``transaction()`` makes
    the checkpoints part of the same atomic unit as the rows they describe: a failure before
    the interrupt rolls back rows and checkpoints together.
    """

    def __init__(self, store: SQLiteStore) -> None:
        super().__init__(store.conn)
        self._store = store
        if self._store_in_transaction():
            raise RuntimeError("build the checkpointer outside store.transaction(); setup() would commit it")
        self.setup()

    def _store_in_transaction(self) -> bool:
        return getattr(self._store, "_transaction_depth", 0) > 0

    @contextmanager
    def cursor(self, transaction: bool = True) -> Iterator[sqlite3.Cursor]:
        with self.lock:
            self.setup()
            cur = self.conn.cursor()
            cur.row_factory = None
            try:
                yield cur
            finally:
                if transaction and not self._store_in_transaction():
                    self.conn.commit()
                cur.close()


__all__ = [
    "AWAIT_REVIEW",
    "ENGINE_NODES",
    "FINALIZE_RUN",
    "MODE_MEMORY",
    "MODE_PERSISTENT",
    "NODE_NAMES",
    "START_NODE",
    "GraphState",
    "StoreCheckpointer",
    "build_graph",
    "initial_graph_state",
    "route_after_report",
    "run_config",
]
