from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ledgerlens.agents.graph import (
    FINALIZE_RUN,
    MODE_MEMORY,
    MODE_PERSISTENT,
    NODE_NAMES,
    START_NODE,
    GraphState,
    StoreCheckpointer,
    build_graph,
    initial_graph_state,
    run_config,
)
from ledgerlens.domain import NormalizedTransaction as StoredTransaction
from ledgerlens.domain import deterministic_id
from ledgerlens.llm import (
    MODEL_FAMILY,
    CachedLLMAdjudicator,
    DeterministicFakeLLM,
    InMemoryLLMCache,
    StoreLLMCache,
    build_adjudication_request,
)
from ledgerlens.matching import CandidatePair, MatchDecision, MatchingPolicy, NormalizedTransaction, TieredMatcher
from ledgerlens.persistence import SQLiteStore
from ledgerlens.reporting import AuditEvent, ReconciliationReport, ReviewTask, build_reconciliation_report

STATUS_AWAITING_REVIEW = "awaiting_review"
STATUS_COMPLETED = "completed"


@dataclass
class WorkflowState:
    run_id: str
    left_transactions: list[NormalizedTransaction]
    right_transactions: list[NormalizedTransaction]
    candidate_pairs: list[CandidatePair] = field(default_factory=list)
    pending_pairs: list[CandidatePair] = field(default_factory=list)
    ambiguous_pairs: list[CandidatePair] = field(default_factory=list)
    decisions: list[MatchDecision] = field(default_factory=list)
    review_tasks: list[ReviewTask] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)
    unmatched_transaction_ids: dict[str, list[str]] = field(default_factory=dict)
    node_trace: list[str] = field(default_factory=list)
    decision_counts: Counter = field(default_factory=Counter)
    llm_budget_remaining: int = 0
    report: ReconciliationReport | None = None
    mode: str = MODE_MEMORY
    finalized: bool = False

    @property
    def candidate_pair_ids(self) -> list[str]:
        return [pair.id for pair in self.candidate_pairs]

    @property
    def review_task_ids(self) -> list[str]:
        return [task.id for task in self.review_tasks]


@dataclass
class PersistentWorkflowResult:
    run_id: str
    report: str
    state: WorkflowState
    status: str = STATUS_COMPLETED


class ReconciliationWorkflow:
    node_names = list(NODE_NAMES)

    def __init__(
        self,
        *args,
        policy: MatchingPolicy | None = None,
        llm: CachedLLMAdjudicator | None = None,
    ) -> None:
        self.store: SQLiteStore | None = None
        if args:
            self.store = args[0]
        if len(args) >= 2 and policy is None:
            policy = args[1]
        self.policy = policy or MatchingPolicy()
        self.matcher = TieredMatcher(self.policy)
        cache = StoreLLMCache(self.store) if self.store is not None else InMemoryLLMCache()
        self.llm = llm or CachedLLMAdjudicator(DeterministicFakeLLM(), cache)
        self._active: dict[str, WorkflowState] = {}
        self._persistent_graph_cache = None
        self._nodes: dict[str, Callable[[WorkflowState], None]] = {
            "load_run_context": self.load_run_context,
            "normalize_batch": self.normalize_batch,
            "generate_candidates": self.generate_candidates,
            "apply_exact_matches": self.apply_exact_matches,
            "apply_rule_matches": self.apply_rule_matches,
            "score_fuzzy_candidates": self.score_fuzzy_candidates,
            "adjudicate_ambiguous_pairs": self.adjudicate_ambiguous_pairs,
            "route_review_tasks": self.route_review_tasks,
            "surface_unmatched_transactions": self.surface_unmatched_transactions,
            "persist_decisions": self.persist_decisions,
            "generate_report": self.generate_report,
        }

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        """Drop in-flight state and the compiled graph; the store owner closes the connection."""
        self._active.clear()
        self._persistent_graph_cache = None

    def run(self, *args, run_id: str | None = None, **kwargs):
        if self.store is not None and "client_id" in kwargs and "sources" in kwargs:
            return self._run_persistent(client_id=kwargs["client_id"], sources=kwargs["sources"])
        if self.store is not None and args and isinstance(args[0], str):
            return self._run_persistent(client_id=args[0], sources=args[1])
        if len(args) < 2 or run_id is None:
            raise TypeError("run() requires left_transactions, right_transactions, and run_id in memory mode")
        return self._run_memory(args[0], args[1], run_id=run_id)

    def _run_memory(
        self,
        left_transactions: list[NormalizedTransaction],
        right_transactions: list[NormalizedTransaction],
        *,
        run_id: str,
    ) -> WorkflowState:
        state = WorkflowState(
            run_id=run_id,
            left_transactions=left_transactions,
            right_transactions=right_transactions,
            llm_budget_remaining=self.policy.max_llm_calls,
            mode=MODE_MEMORY,
        )
        graph = build_graph(self, InMemorySaver())
        initial = initial_graph_state(
            run_id=run_id,
            client_id="",
            mode=MODE_MEMORY,
            gated=False,
            llm_budget_remaining=state.llm_budget_remaining,
        )
        self._active[run_id] = state
        try:
            graph.invoke(initial, config=run_config(run_id))
        finally:
            self._active.pop(run_id, None)
        return state

    def _run_persistent(
        self,
        *,
        client_id: str,
        sources: list[tuple[str | Path, str | Path]],
    ) -> PersistentWorkflowResult:
        if self.store is None:
            raise RuntimeError("persistent workflow requires a SQLiteStore")
        source_specs = self._validate_sources(client_id, sources)
        graph = self._persistent_graph()

        with self.store.transaction():
            run = self.store.create_run(client_id=client_id, metadata={"mode": "persistent_cli"})
            run_id = run.id if hasattr(run, "id") else str(run)
            transactions_by_source = self._ingest_sources(run_id, source_specs)
            source_names = sorted(transactions_by_source)
            state = WorkflowState(
                run_id=run_id,
                left_transactions=transactions_by_source[source_names[0]],
                right_transactions=transactions_by_source[source_names[1]],
                llm_budget_remaining=self.policy.max_llm_calls,
                mode=MODE_PERSISTENT,
            )
            initial = initial_graph_state(
                run_id=run_id,
                client_id=client_id,
                mode=MODE_PERSISTENT,
                gated=True,
                llm_budget_remaining=state.llm_budget_remaining,
            )
            config = run_config(run_id)
            self._active[run_id] = state
            try:
                graph.invoke(initial, config=config)
            finally:
                self._active.pop(run_id, None)
            status = STATUS_AWAITING_REVIEW if graph.get_state(config).next else STATUS_COMPLETED
            if status == STATUS_AWAITING_REVIEW:
                self.store.set_run_status(run_id, STATUS_AWAITING_REVIEW)
        report = state.report.markdown if state.report else ""
        return PersistentWorkflowResult(run_id=run_id, report=report, state=state, status=status)

    def complete_review(self, run_id: str, *, reviewer: str, note: str = "") -> dict[str, Any]:
        """Validate the resume payload against the store, then resume the interrupted graph (D-4)."""
        if self.store is None:
            raise RuntimeError("complete_review requires a SQLiteStore")
        reviewer = (reviewer or "").strip()
        if not reviewer:
            raise ValueError("reviewer is required to complete a review")
        run = self.store.get_run(run_id)
        if run["status"] != STATUS_AWAITING_REVIEW:
            raise ValueError(f"run {run_id} is {run['status']}; only awaiting_review runs can be completed")
        open_tasks = self.store.open_review_task_count(run_id)
        if open_tasks:
            raise ValueError(f"run {run_id} still has {open_tasks} open review task(s); resolve them first")

        graph = self._persistent_graph()
        config = run_config(run_id)
        with self.store.transaction():
            graph.invoke(Command(resume={"reviewer": reviewer, "note": note}), config=config)
        snapshot = graph.get_state(config)
        if snapshot.next:
            raise RuntimeError(f"run {run_id} did not reach END after review; pending {list(snapshot.next)}")
        return {
            "run_id": run_id,
            "status": STATUS_COMPLETED,
            "reviewer": reviewer,
            "note": note,
            "finalized": bool(snapshot.values.get("finalized")),
            "report": snapshot.values.get("report_markdown") or "",
        }

    def graph_history(self, run_id: str) -> list[dict[str, Any]]:
        """Checkpoints oldest first: step, node, stage, checkpoint_id, created_at."""
        if self.store is None:
            raise RuntimeError("graph_history requires a SQLiteStore")
        self.store.get_run(run_id)
        snapshots = list(self._persistent_graph().get_state_history(run_config(run_id)))
        entries = []
        for index, snapshot in enumerate(snapshots):
            parent = snapshots[index + 1] if index + 1 < len(snapshots) else None
            values = snapshot.values if isinstance(snapshot.values, dict) else {}
            entries.append(
                {
                    "step": (snapshot.metadata or {}).get("step"),
                    "node": parent.next[0] if parent is not None and parent.next else START_NODE,
                    "stage": values.get("stage"),
                    "checkpoint_id": snapshot.config["configurable"]["checkpoint_id"],
                    "created_at": snapshot.created_at,
                }
            )
        entries.reverse()
        return entries

    # ------------------------------------------------------------------ graph callbacks

    def run_node(self, name: str, graph_state: GraphState) -> dict[str, Any]:
        """Run one engine node against the in-flight WorkflowState and return the checkpoint delta."""
        state = self._active[graph_state["run_id"]]
        self._nodes[name](state)
        state.node_trace.append(name)
        return {
            "stage": name,
            "node_trace": [*graph_state.get("node_trace", []), name],
            "candidate_pair_ids": state.candidate_pair_ids,
            "review_task_ids": state.review_task_ids,
            "decision_counts": dict(state.decision_counts),
            "llm_budget_remaining": state.llm_budget_remaining,
        }

    def finalize_run(self, graph_state: GraphState) -> dict[str, Any]:
        """Close the run: persistent mode re-reads the store and regenerates the report."""
        run_id = graph_state["run_id"]
        state = self._active.get(run_id)
        if graph_state.get("mode") == MODE_PERSISTENT and self.store is not None:
            report = self._finalize_persistent(
                run_id,
                reviewer=graph_state.get("reviewer"),
                note=graph_state.get("review_note"),
            )
        else:
            report = state.report.markdown if state is not None and state.report else None
        if state is not None:
            state.finalized = True
            state.node_trace.append(FINALIZE_RUN)
        return {
            "stage": FINALIZE_RUN,
            "node_trace": [*graph_state.get("node_trace", []), FINALIZE_RUN],
            "awaiting_review": False,
            "report_markdown": report,
            "finalized": True,
        }

    # ------------------------------------------------------------------ persistent helpers

    def _persistent_graph(self):
        if self.store is None:
            raise RuntimeError("persistent graph requires a SQLiteStore")
        if self._persistent_graph_cache is None:
            self._persistent_graph_cache = build_graph(self, StoreCheckpointer(self.store))
        return self._persistent_graph_cache

    def _validate_sources(self, client_id: str, sources: list[tuple[str | Path, str | Path]]) -> list[tuple[Any, Any]]:
        from ledgerlens.ingestion import load_mapping_profile

        if len(sources) != 2:
            raise ValueError("persistent workflow currently reconciles exactly two source/profile pairs")
        source_specs = []
        source_keys: set[str] = set()
        for csv_path, profile_path in sources:
            profile = load_mapping_profile(profile_path)
            if profile.client_id != client_id:
                raise ValueError(f"profile {profile.profile_name} belongs to client {profile.client_id}, not {client_id}")
            source_key = f"{profile.source_system}:{profile.account_id}"
            if source_key in source_keys:
                raise ValueError(f"duplicate source/account pair: {source_key}")
            source_keys.add(source_key)
            source_specs.append((csv_path, profile))
        return source_specs

    def _ingest_sources(self, run_id: str, source_specs: list[tuple[Any, Any]]) -> dict[str, list[NormalizedTransaction]]:
        from dataclasses import asdict, replace

        from ledgerlens.ingestion import CSVIngestor
        from ledgerlens.normalization import TransactionNormalizer

        assert self.store is not None
        transactions_by_source: dict[str, list[NormalizedTransaction]] = {}
        for csv_path, profile in source_specs:
            batch = CSVIngestor(profile).ingest(csv_path)
            normalized = TransactionNormalizer(profile).normalize(batch)
            source_file = replace(
                batch.source_file,
                id=deterministic_id("src", run_id, batch.source_file.id),
                run_id=run_id,
            )
            raw_id_by_base_id = {
                raw.id: deterministic_id("raw", source_file.id, raw.source_row_number, raw.raw_hash)
                for raw in batch.raw_transactions
            }
            raw_transactions = [
                replace(raw, id=raw_id_by_base_id[raw.id], source_file_id=source_file.id)
                for raw in batch.raw_transactions
            ]
            stored_transactions = [
                replace(
                    transaction,
                    id=deterministic_id("txn", run_id, transaction.id),
                    raw_transaction_id=raw_id_by_base_id[transaction.raw_transaction_id],
                    run_id=run_id,
                )
                for transaction in normalized.transactions
            ]
            diagnostics = replace(normalized.diagnostics, source_file_id=source_file.id)
            self.store.add_source_file(source_file)
            self.store.add_raw_transactions(raw_transactions)
            self.store.add_normalized_transactions(stored_transactions)
            self.store.set_metric(run_id, f"source_diagnostics.{profile.source_system}", asdict(diagnostics))
            source_key = f"{profile.source_system}:{profile.account_id}"
            transactions_by_source[source_key] = [_to_matching_transaction(transaction) for transaction in stored_transactions]
        return transactions_by_source

    def _persist_state(self, state: WorkflowState) -> None:
        """Write pairs, decisions, tasks, audit events and matching metrics for the run."""
        assert self.store is not None
        for pair in state.candidate_pairs:
            self.store.save_candidate_pair(pair)
        for decision in state.decisions:
            self.store.save_match_decision(decision)
        for task in state.review_tasks:
            self.store.save_review_task(task)
        for event in state.audit_events:
            self.store.save_audit_event(event)
        llm_stats = self.llm.stats()
        self.store.set_metric(state.run_id, "matching", llm_stats | {
            "candidate_count": len(state.candidate_pairs),
            "decision_count": len(state.decisions),
            "review_task_count": len(state.review_tasks),
            "unmatched_left_count": len(state.unmatched_transaction_ids.get("left", [])),
            "unmatched_right_count": len(state.unmatched_transaction_ids.get("right", [])),
            "unmatched_transaction_count": sum(len(ids) for ids in state.unmatched_transaction_ids.values()),
            "unmatched_transaction_ids": state.unmatched_transaction_ids,
            "llm_calls": llm_stats.get("calls", 0),
            "llm_cache_hits": llm_stats.get("cache_hits", 0),
            "llm_calls_avoided": llm_stats.get("calls_avoided", 0),
        })

    def _finalize_persistent(self, run_id: str, *, reviewer: str | None, note: str | None) -> str:
        from ledgerlens.reporting.report import generate_markdown_report

        assert self.store is not None
        self.store.save_audit_event(
            AuditEvent(
                id=deterministic_id("audit", run_id, "run.finalized"),
                run_id=run_id,
                entity_type="run",
                entity_id=run_id,
                event_type="run.finalized",
                actor_type="human" if reviewer else "system",
                actor_id=reviewer or "agents.workflow",
                after={
                    "reviewer": reviewer,
                    "note": note or "",
                    "decisions_by_tier": self.store.decisions_by_tier(run_id),
                    "open_review_tasks": self.store.open_review_task_count(run_id),
                },
            )
        )
        self.store.set_run_status(run_id, STATUS_COMPLETED)
        return generate_markdown_report(self.store, run_id)

    # ------------------------------------------------------------------ engine nodes

    def load_run_context(self, state: WorkflowState) -> None:
        self._audit(
            state,
            entity_type="run",
            entity_id=state.run_id,
            event_type="run.loaded",
            actor_id="agents.workflow",
            after={"left_count": len(state.left_transactions), "right_count": len(state.right_transactions)},
        )

    def normalize_batch(self, state: WorkflowState) -> None:
        # This sidecar receives NormalizedTransaction objects; the node remains explicit for graph parity.
        self._audit(
            state,
            entity_type="run",
            entity_id=state.run_id,
            event_type="batch.normalized",
            actor_id="agents.workflow",
            after={"mode": "passthrough"},
        )

    def generate_candidates(self, state: WorkflowState) -> None:
        from ledgerlens.matching import generate_candidate_pairs

        state.candidate_pairs = generate_candidate_pairs(
            state.left_transactions,
            state.right_transactions,
            run_id=state.run_id,
            policy=self.policy,
        )
        state.pending_pairs = list(state.candidate_pairs)
        self._audit(
            state,
            entity_type="candidate_pair",
            entity_id=state.run_id,
            event_type="match.candidates_created",
            actor_id="matching.blocker",
            after={"candidate_pair_ids": state.candidate_pair_ids},
        )

    def apply_exact_matches(self, state: WorkflowState) -> None:
        remaining: list[CandidatePair] = []
        for pair in state.pending_pairs:
            evaluation = self.matcher.evaluate_exact(pair)
            if evaluation is None:
                remaining.append(pair)
                continue
            self._record_decision(state, pair, evaluation.to_match_decision(
                run_id=state.run_id,
                pair=pair,
                decided_by="matching.exact",
            ))
        state.pending_pairs = remaining

    def apply_rule_matches(self, state: WorkflowState) -> None:
        remaining: list[CandidatePair] = []
        for pair in state.pending_pairs:
            evaluation = self.matcher.evaluate_rule(pair)
            if evaluation is None:
                remaining.append(pair)
                continue
            self._record_decision(state, pair, evaluation.to_match_decision(
                run_id=state.run_id,
                pair=pair,
                decided_by="matching.rule",
            ))
        state.pending_pairs = remaining

    def score_fuzzy_candidates(self, state: WorkflowState) -> None:
        remaining: list[CandidatePair] = []
        for pair in state.pending_pairs:
            evaluation = self.matcher.evaluate_fuzzy(pair)
            if evaluation.status == "ambiguous":
                state.ambiguous_pairs.append(pair)
                continue
            self._record_decision(state, pair, evaluation.to_match_decision(
                run_id=state.run_id,
                pair=pair,
                decided_by="matching.fuzzy",
            ))
        state.pending_pairs = remaining

    def adjudicate_ambiguous_pairs(self, state: WorkflowState) -> None:
        for pair in state.ambiguous_pairs:
            if state.llm_budget_remaining <= 0:
                decision = MatchDecision(
                    id=f"decision_{state.run_id}_{pair.left_transaction_id}_{pair.right_transaction_id}_llm_budget",
                    run_id=state.run_id,
                    candidate_pair_id=pair.id,
                    decision="needs_review",
                    tier="llm",
                    confidence=0.0,
                    reason_code="llm_budget_exhausted",
                    explanation="The configured LLM call budget was exhausted before adjudication.",
                    evidence={"candidate_score": pair.candidate_score},
                    decided_by="llm.budget",
                )
                self._record_decision(state, pair, decision)
                continue

            model_family = getattr(self.llm.client, "model_family", MODEL_FAMILY)
            request = build_adjudication_request(pair, self.policy, model_family=model_family)
            result = self.llm.adjudicate(request)
            if not result.cache_hit:
                state.llm_budget_remaining -= 1

            final_decision = result.decision
            reason_code = result.reason_code
            explanation = result.explanation
            evidence = {
                "candidate_score": pair.candidate_score,
                "llm_cache_key": result.cache_key,
                "cache_hit": result.cache_hit,
                "suggested_decision": result.decision,
            }
            if result.decision == "needs_review" or result.confidence < self.policy.require_human_review_below_confidence:
                final_decision = "needs_review"
                reason_code = "llm_low_confidence" if result.confidence < self.policy.require_human_review_below_confidence else result.reason_code
                explanation = f"{result.explanation} Routed to review by confidence policy."

            decision = MatchDecision(
                id=f"decision_{state.run_id}_{pair.left_transaction_id}_{pair.right_transaction_id}_llm",
                run_id=state.run_id,
                candidate_pair_id=pair.id,
                decision=final_decision,
                tier="llm",
                confidence=result.confidence,
                reason_code=reason_code,
                explanation=explanation,
                evidence=evidence,
                llm_cache_key=result.cache_key,
                decided_by="llm.fake",
            )
            self._record_decision(state, pair, decision)

    def route_review_tasks(self, state: WorkflowState) -> None:
        existing_pair_ids = {task.candidate_pair_id for task in state.review_tasks}
        pair_by_id = {pair.id: pair for pair in state.candidate_pairs}
        for decision in state.decisions:
            if decision.decision != "needs_review" or decision.candidate_pair_id in existing_pair_ids:
                continue
            pair = pair_by_id[decision.candidate_pair_id]
            task = ReviewTask(
                id=f"review_{state.run_id}_{pair.right_transaction_id}_{pair.left_transaction_id}",
                run_id=state.run_id,
                candidate_pair_id=pair.id,
                priority="high" if decision.confidence < 0.60 else "medium",
                status="open",
                reason=decision.reason_code,
                suggested_decision=str(decision.evidence.get("suggested_decision", decision.decision)),
            )
            decision.review_task_id = task.id
            state.review_tasks.append(task)
            existing_pair_ids.add(decision.candidate_pair_id)
            self._audit(
                state,
                entity_type="review_task",
                entity_id=task.id,
                event_type="review.required",
                actor_id="agents.workflow",
                after={"candidate_pair_id": task.candidate_pair_id, "reason": task.reason},
            )

    def surface_unmatched_transactions(self, state: WorkflowState) -> None:
        unmatched = _unmatched_transaction_ids(state)
        state.unmatched_transaction_ids = unmatched
        if unmatched["left"] or unmatched["right"]:
            self._audit(
                state,
                entity_type="run",
                entity_id=state.run_id,
                event_type="exceptions.unmatched_detected",
                actor_id="agents.workflow",
                after={
                    "left_unmatched_count": len(unmatched["left"]),
                    "right_unmatched_count": len(unmatched["right"]),
                },
            )

    def persist_decisions(self, state: WorkflowState) -> None:
        """Write the run's pairs, decisions, tasks and audit trail; memory mode only audits."""
        self._audit(
            state,
            entity_type="run",
            entity_id=state.run_id,
            event_type="run.persisted",
            actor_id="agents.workflow",
            after={"decision_count": len(state.decisions), "review_task_count": len(state.review_tasks)},
        )
        if state.mode == MODE_PERSISTENT and self.store is not None:
            self._persist_state(state)

    def generate_report(self, state: WorkflowState) -> None:
        state.report = build_reconciliation_report(
            run_id=state.run_id,
            left_transactions=state.left_transactions,
            right_transactions=state.right_transactions,
            candidate_pairs=state.candidate_pairs,
            decisions=state.decisions,
            review_tasks=state.review_tasks,
            llm_stats=self.llm.stats(),
            audit_events=state.audit_events,
        )
        event = self._audit(
            state,
            entity_type="report",
            entity_id=state.run_id,
            event_type="report.generated",
            actor_id="reporting.markdown",
            after={"open_review_tasks": len(state.review_tasks)},
        )
        if state.mode == MODE_PERSISTENT and self.store is not None:
            self.store.save_audit_event(event)

    def _record_decision(self, state: WorkflowState, pair: CandidatePair, decision: MatchDecision) -> None:
        state.decisions.append(decision)
        state.decision_counts[decision.tier] += 1
        self._audit(
            state,
            entity_type="match_decision",
            entity_id=decision.id,
            event_type="match.decision_created",
            actor_id=decision.decided_by,
            after={
                "candidate_pair_id": pair.id,
                "decision": decision.decision,
                "tier": decision.tier,
                "confidence": decision.confidence,
                "reason_code": decision.reason_code,
            },
        )

    def _audit(
        self,
        state: WorkflowState,
        *,
        entity_type: str,
        entity_id: str,
        event_type: str,
        actor_id: str,
        after: dict[str, object] | None = None,
    ) -> AuditEvent:
        event_id = deterministic_id(
            "audit",
            state.run_id,
            len(state.audit_events) + 1,
            event_type,
            entity_type,
            entity_id,
        )
        event = AuditEvent(
            id=event_id,
            run_id=state.run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_type="system",
            actor_id=actor_id,
            after=after,
        )
        state.audit_events.append(event)
        return event


def _to_matching_transaction(transaction: StoredTransaction) -> NormalizedTransaction:
    return NormalizedTransaction(
        id=transaction.id,
        account_id=transaction.account_id,
        source_system=transaction.source_system,
        posting_date=transaction.posting_date,
        amount=transaction.amount,
        currency=transaction.currency,
        description_raw=transaction.description_raw,
        description_normalized=transaction.description_normalized,
        raw_transaction_id=transaction.raw_transaction_id,
        external_transaction_id=transaction.external_transaction_id,
        value_date=transaction.value_date,
        direction=transaction.direction,
        counterparty=transaction.counterparty or "",
        reference=transaction.reference or "",
        quality_flags=tuple(transaction.quality_flags),
    )


def _unmatched_transaction_ids(state: WorkflowState) -> dict[str, list[str]]:
    pair_by_id = {pair.id: pair for pair in state.candidate_pairs}
    covered_ids: set[str] = set()
    for decision in state.decisions:
        if decision.decision not in {"match", "duplicate", "needs_review"}:
            continue
        pair = pair_by_id.get(decision.candidate_pair_id)
        if pair is None:
            continue
        covered_ids.add(pair.left_transaction_id)
        covered_ids.add(pair.right_transaction_id)
    return {
        "left": [transaction.id for transaction in state.left_transactions if transaction.id not in covered_ids],
        "right": [transaction.id for transaction in state.right_transactions if transaction.id not in covered_ids],
    }
