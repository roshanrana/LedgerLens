from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from ledgerlens.agents import GraphState, ReconciliationWorkflow, run_config
from ledgerlens.agents.graph import ENGINE_NODES, NODE_NAMES
from ledgerlens.llm import CachedLLMAdjudicator, InMemoryLLMCache, LLMAdjudicationRequest, LLMDecision
from ledgerlens.matching import NormalizedTransaction
from ledgerlens.persistence.store import SQLiteStore


ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    (ROOT / "data" / "samples" / "acme_bank_statement.csv", ROOT / "configs" / "clients" / "acme_bank.json"),
    (ROOT / "data" / "samples" / "acme_ledger_export.csv", ROOT / "configs" / "clients" / "acme_ledger.json"),
]
GRAPH_STATE_KEYS = set(GraphState.__annotations__)


class GraphGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "gate.db"
        self.store = SQLiteStore(self.db_path)
        self.store.initialize()
        self.workflow = ReconciliationWorkflow(self.store)
        self._stores = [self.store]

    def tearDown(self) -> None:
        for store in self._stores:
            store.close()
        self._tmp.cleanup()

    def _fresh_store(self) -> SQLiteStore:
        store = SQLiteStore(self.db_path)
        store.initialize()
        self._stores.append(store)
        return store

    def test_node_names_follow_the_design_order(self):
        self.assertEqual(ReconciliationWorkflow.node_names, list(NODE_NAMES))
        self.assertEqual(len(ReconciliationWorkflow.node_names), 13)
        self.assertEqual(ReconciliationWorkflow.node_names[-2:], ["await_review", "finalize_run"])

    def test_persistent_run_stops_at_the_review_gate(self):
        result = self.workflow.run("acme", SOURCES)

        self.assertEqual(result.status, "awaiting_review")
        self.assertIn("LedgerLens Reconciliation Report", result.report)
        self.assertEqual(self.store.get_run(result.run_id)["status"], "awaiting_review")
        self.assertEqual(self.store.open_review_task_count(result.run_id), 1)
        self.assertNotIn("await_review", result.state.node_trace)
        self.assertFalse(result.state.finalized)

        # Everything is committed and visible from a second connection at the interrupt.
        other = self._fresh_store()
        self.assertEqual(other.get_run(result.run_id)["status"], "awaiting_review")
        self.assertEqual(len(other.list_review_tasks(result.run_id, status="open")), 1)
        self.assertEqual(other.table_counts(result.run_id)["match_decisions"], 4)
        self.assertGreaterEqual(other.table_counts(result.run_id)["audit_events"], 1)

    def test_checkpoint_holds_ids_and_counters_only(self):
        result = self.workflow.run("acme", SOURCES)
        snapshot = self.workflow._persistent_graph().get_state(run_config(result.run_id))

        self.assertEqual(snapshot.next, ("await_review",))
        self.assertTrue(snapshot.tasks[0].interrupts)
        self.assertLessEqual(set(snapshot.values), GRAPH_STATE_KEYS)
        self.assertEqual(snapshot.values["review_task_ids"], result.state.review_task_ids)
        self.assertEqual(snapshot.values["candidate_pair_ids"], result.state.candidate_pair_ids)
        self.assertTrue(snapshot.values["awaiting_review"])
        self.assertEqual(snapshot.values["node_trace"], list(ENGINE_NODES))
        interrupt_value = snapshot.tasks[0].interrupts[0].value
        self.assertEqual(interrupt_value["run_id"], result.run_id)
        self.assertEqual(interrupt_value["open_review_task_ids"], result.state.review_task_ids)

    def test_complete_review_is_refused_while_a_task_is_open_or_reviewer_missing(self):
        result = self.workflow.run("acme", SOURCES)

        with self.assertRaisesRegex(ValueError, "open review task"):
            self.workflow.complete_review(result.run_id, reviewer="qa")
        with self.assertRaisesRegex(ValueError, "reviewer is required"):
            self.workflow.complete_review(result.run_id, reviewer="  ")
        with self.assertRaisesRegex(ValueError, "run not found"):
            self.workflow.complete_review("run_missing", reviewer="qa")

        self.assertEqual(self.store.get_run(result.run_id)["status"], "awaiting_review")
        self.assertEqual(self.store.open_review_task_count(result.run_id), 1)

    def test_resume_from_a_fresh_workflow_instance_completes_the_run(self):
        result = self.workflow.run("acme", SOURCES)
        self.workflow.close()

        other = self._fresh_store()
        task = other.list_review_tasks(result.run_id, status="open")[0]
        other.resolve_review_task(task["id"], "no_match", "Fee wording only looks similar.", "qa")
        outcome = ReconciliationWorkflow(other).complete_review(result.run_id, reviewer="qa", note="Reviewed.")

        self.assertEqual(outcome["status"], "completed")
        self.assertTrue(outcome["finalized"])
        self.assertIn("human:no_match", outcome["report"])
        self.assertIn("run.finalized", outcome["report"])
        self.assertIn("Open review tasks: 0", outcome["report"])
        self.assertEqual(self.store.get_run(result.run_id)["status"], "completed")
        finalized = [event for event in other.list_audit_events(result.run_id) if event["event_type"] == "run.finalized"]
        self.assertEqual(len(finalized), 1)
        self.assertEqual(finalized[0]["actor_id"], "qa")
        self.assertEqual(finalized[0]["after"]["note"], "Reviewed.")

        with self.assertRaisesRegex(ValueError, "only awaiting_review runs"):
            ReconciliationWorkflow(other).complete_review(result.run_id, reviewer="qa")

    def test_graph_history_lists_every_checkpoint_oldest_first(self):
        result = self.workflow.run("acme", SOURCES)
        task = self.store.list_review_tasks(result.run_id, status="open")[0]
        self.store.resolve_review_task(task["id"], "match", "Same payment.", "qa")
        self.workflow.complete_review(result.run_id, reviewer="qa")

        history = ReconciliationWorkflow(self._fresh_store()).graph_history(result.run_id)

        self.assertGreaterEqual(len(history), 13)
        self.assertEqual(set(history[0]), {"step", "node", "stage", "checkpoint_id", "created_at"})
        steps = [entry["step"] for entry in history]
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(history[-1]["stage"], "finalize_run")
        self.assertEqual(history[-1]["node"], "finalize_run")
        self.assertIn("await_review", [entry["stage"] for entry in history])
        self.assertEqual(len({entry["checkpoint_id"] for entry in history}), len(history))

    def test_memory_mode_never_interrupts_and_finalizes(self):
        left = [_tx("bank-1", "-42.00", "2026-05-01", "Card settlement REF42", reference="REF42", source_system="bank")]
        right = [_tx("ledger-1", "42.00", "2026-05-01", "Card settlement REF42", reference="REF42", source_system="ledger")]
        workflow = ReconciliationWorkflow()

        state = workflow.run(left, right, run_id="run-memory")

        self.assertTrue(state.finalized)
        self.assertNotIn("await_review", state.node_trace)
        self.assertEqual(state.node_trace[-1], "finalize_run")
        self.assertEqual(state.node_trace[: len(ENGINE_NODES)], list(ENGINE_NODES))
        self.assertIsNotNone(state.report)
        self.assertEqual(state.decision_counts["exact"], 1)

    def test_persistent_run_without_review_tasks_completes_immediately(self):
        confident = CachedLLMAdjudicator(_ConfidentMatchLLM(), InMemoryLLMCache())
        workflow = ReconciliationWorkflow(self.store, llm=confident)

        result = workflow.run("acme", SOURCES)

        self.assertEqual(result.state.review_tasks, [])
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.state.finalized)
        self.assertEqual(result.state.node_trace[-2:], ["generate_report", "finalize_run"])
        self.assertEqual(self.store.get_run(result.run_id)["status"], "completed")
        self.assertEqual(self.store.open_review_task_count(result.run_id), 0)
        events = {event["event_type"] for event in self.store.list_audit_events(result.run_id)}
        self.assertIn("run.finalized", events)
        history = workflow.graph_history(result.run_id)
        self.assertNotIn("await_review", [entry["stage"] for entry in history])
        self.assertEqual(history[-1]["stage"], "finalize_run")


def _tx(transaction_id, amount, posting_date, description, *, reference="", source_system):
    return NormalizedTransaction(
        id=transaction_id,
        account_id="operating",
        source_system=source_system,
        posting_date=posting_date,
        amount=Decimal(amount),
        currency="USD",
        description_raw=description,
        description_normalized=description,
        reference=reference,
    )


class _ConfidentMatchLLM:
    """Adjudicator stub that never asks for review, so the gate routes straight to finalize_run."""

    model = "confident-stub"

    def adjudicate(self, request: LLMAdjudicationRequest) -> LLMDecision:
        return LLMDecision(decision="match", confidence=0.99, reason_code="stub", explanation="Stubbed match.")


if __name__ == "__main__":
    unittest.main()
