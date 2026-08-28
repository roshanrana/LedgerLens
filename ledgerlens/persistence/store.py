from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from ledgerlens.domain.models import (
    AuditEvent,
    CandidatePair,
    LLMCacheEntry,
    MatchDecision,
    NormalizedTransaction,
    RawTransaction,
    ReconciliationRun,
    ReviewTask,
    SourceFile,
    new_id,
    utc_now,
)


ALLOWED_REVIEW_DECISIONS = {"match", "no_match", "duplicate", "needs_review", "unmatched"}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class SQLiteStore:
    """Small repository layer for the portable LedgerLens demo database."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._transaction_depth = 0

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        is_outermost = self._transaction_depth == 0
        if is_outermost:
            self.conn.execute("BEGIN")
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            self._transaction_depth -= 1
            if is_outermost:
                self.conn.rollback()
            raise
        else:
            self._transaction_depth -= 1
            if is_outermost:
                self.conn.commit()

    def _commit(self) -> None:
        if self._transaction_depth == 0:
            self.conn.commit()

    def initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                metadata_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_files (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                source_system TEXT NOT NULL,
                account_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                mapping_profile TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                UNIQUE(run_id, client_id, file_hash, mapping_profile)
            );

            CREATE TABLE IF NOT EXISTS raw_transactions (
                id TEXT PRIMARY KEY,
                source_file_id TEXT NOT NULL,
                source_row_number INTEGER NOT NULL,
                raw_payload_json TEXT NOT NULL,
                raw_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS normalized_transactions (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                raw_transaction_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                source_system TEXT NOT NULL,
                external_transaction_id TEXT,
                posting_date TEXT NOT NULL,
                value_date TEXT,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                direction TEXT NOT NULL,
                description_raw TEXT NOT NULL,
                description_normalized TEXT NOT NULL,
                counterparty TEXT,
                reference TEXT,
                fingerprint_exact TEXT NOT NULL,
                fingerprint_loose TEXT NOT NULL,
                quality_flags_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS candidate_pairs (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                left_transaction_id TEXT NOT NULL,
                right_transaction_id TEXT NOT NULL,
                blocking_reason TEXT NOT NULL,
                feature_vector_json TEXT NOT NULL,
                candidate_score REAL NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, left_transaction_id, right_transaction_id)
            );

            CREATE TABLE IF NOT EXISTS match_decisions (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                candidate_pair_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                tier TEXT NOT NULL,
                confidence REAL NOT NULL,
                reason_code TEXT NOT NULL,
                explanation TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                llm_cache_key TEXT,
                review_task_id TEXT,
                decided_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS review_tasks (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                candidate_pair_id TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                suggested_decision TEXT NOT NULL,
                assigned_to TEXT,
                reviewer_decision TEXT,
                reviewer_notes TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                prompt_schema_version TEXT NOT NULL,
                model TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                output_json TEXT NOT NULL,
                decision TEXT NOT NULL,
                confidence REAL NOT NULL,
                reason TEXT NOT NULL,
                token_estimate INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS run_metrics (
                run_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(run_id, key)
            );

            CREATE INDEX IF NOT EXISTS idx_source_files_hash ON source_files(file_hash, client_id);
            CREATE INDEX IF NOT EXISTS idx_norm_run_account ON normalized_transactions(run_id, account_id);
            CREATE INDEX IF NOT EXISTS idx_norm_exact ON normalized_transactions(fingerprint_exact);
            CREATE INDEX IF NOT EXISTS idx_norm_loose ON normalized_transactions(fingerprint_loose);
            CREATE INDEX IF NOT EXISTS idx_pairs_run ON candidate_pairs(run_id);
            CREATE INDEX IF NOT EXISTS idx_decisions_run ON match_decisions(run_id, tier, decision);
            CREATE INDEX IF NOT EXISTS idx_reviews_status ON review_tasks(status, priority, created_at);
            """
        )
        self._migrate_source_files_run_scoped_uniqueness()
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_source_files_hash ON source_files(file_hash, client_id)")
        self._commit()

    def _migrate_source_files_run_scoped_uniqueness(self) -> None:
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'source_files'"
        ).fetchone()
        if row is None:
            return
        table_sql = " ".join(str(row["sql"] or "").split())
        if "UNIQUE(client_id, file_hash, mapping_profile)" not in table_sql:
            return

        self.conn.execute("ALTER TABLE source_files RENAME TO source_files_legacy_unique")
        self.conn.execute(
            """
            CREATE TABLE source_files (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                source_system TEXT NOT NULL,
                account_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                mapping_profile TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                UNIQUE(run_id, client_id, file_hash, mapping_profile)
            )
            """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO source_files
            (id, run_id, client_id, source_system, account_id, filename, file_hash,
             mapping_profile, ingested_at, row_count, status)
            SELECT id, run_id, client_id, source_system, account_id, filename, file_hash,
                   mapping_profile, ingested_at, row_count, status
            FROM source_files_legacy_unique
            """
        )
        self.conn.execute("DROP TABLE source_files_legacy_unique")

    def create_run(self, client_id: str, metadata: dict[str, Any] | None = None) -> ReconciliationRun:
        run = ReconciliationRun(id=new_id("run"), client_id=client_id, metadata=metadata or {})
        self.conn.execute(
            "INSERT INTO reconciliation_runs VALUES (?, ?, ?, ?, ?, ?)",
            (run.id, run.client_id, run.status, run.created_at, run.completed_at, _json(run.metadata)),
        )
        self._commit()
        return run

    def complete_run(self, run_id: str) -> None:
        self.conn.execute(
            "UPDATE reconciliation_runs SET status = ?, completed_at = ? WHERE id = ?",
            ("completed", utc_now(), run_id),
        )
        self._commit()

    def add_source_file(self, source: SourceFile) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO source_files
            (id, run_id, client_id, source_system, account_id, filename, file_hash, mapping_profile,
             ingested_at, row_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.id,
                source.run_id,
                source.client_id,
                source.source_system,
                source.account_id,
                source.filename,
                source.file_hash,
                source.mapping_profile,
                source.ingested_at,
                source.row_count,
                source.status,
            ),
        )
        self._commit()

    def add_raw_transactions(self, rows: Iterable[RawTransaction]) -> None:
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO raw_transactions
            (id, source_file_id, source_row_number, raw_payload_json, raw_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (row.id, row.source_file_id, row.source_row_number, _json(row.raw_payload), row.raw_hash, row.created_at)
                for row in rows
            ],
        )
        self._commit()

    def add_normalized_transactions(self, rows: Iterable[NormalizedTransaction]) -> None:
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO normalized_transactions
            (id, run_id, raw_transaction_id, account_id, source_system, external_transaction_id,
             posting_date, value_date, amount, currency, direction, description_raw,
             description_normalized, counterparty, reference, fingerprint_exact, fingerprint_loose,
             quality_flags_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.id,
                    row.run_id,
                    row.raw_transaction_id,
                    row.account_id,
                    row.source_system,
                    row.external_transaction_id,
                    row.posting_date.isoformat() if hasattr(row.posting_date, "isoformat") else row.posting_date,
                    row.value_date.isoformat() if hasattr(row.value_date, "isoformat") else row.value_date,
                    str(row.amount),
                    row.currency,
                    row.direction,
                    row.description_raw,
                    row.description_normalized,
                    row.counterparty,
                    row.reference,
                    row.fingerprint_exact,
                    row.fingerprint_loose,
                    _json(row.quality_flags),
                    row.created_at,
                )
                for row in rows
            ],
        )
        self._commit()

    def list_normalized_transactions(self, run_id: str) -> list[NormalizedTransaction]:
        rows = self.conn.execute(
            "SELECT * FROM normalized_transactions WHERE run_id = ? ORDER BY source_system, posting_date, id",
            (run_id,),
        ).fetchall()
        return [self._normalized_from_row(row) for row in rows]

    def save_candidate_pair(self, pair: CandidatePair) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO candidate_pairs
            (id, run_id, left_transaction_id, right_transaction_id, blocking_reason,
             feature_vector_json, candidate_score, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pair.id,
                pair.run_id,
                pair.left_transaction_id,
                pair.right_transaction_id,
                pair.blocking_reason,
                _json(pair.feature_vector),
                pair.candidate_score,
                pair.created_by,
                getattr(pair, "created_at", utc_now()),
            ),
        )
        self._commit()

    def save_match_decision(self, decision: MatchDecision) -> None:
        self.conn.execute(
            """
            INSERT INTO match_decisions
            (id, run_id, candidate_pair_id, decision, tier, confidence, reason_code,
             explanation, evidence_json, llm_cache_key, review_task_id, decided_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.id,
                decision.run_id,
                decision.candidate_pair_id,
                decision.decision,
                decision.tier,
                decision.confidence,
                decision.reason_code,
                decision.explanation,
                _json(decision.evidence),
                decision.llm_cache_key,
                decision.review_task_id,
                decision.decided_by,
                getattr(decision, "created_at", utc_now()),
            ),
        )
        self._commit()

    def save_review_task(self, task: ReviewTask) -> None:
        self.conn.execute(
            """
            INSERT INTO review_tasks
            (id, run_id, candidate_pair_id, priority, status, reason, suggested_decision,
             assigned_to, reviewer_decision, reviewer_notes, created_at, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.run_id,
                task.candidate_pair_id,
                task.priority,
                task.status,
                task.reason,
                task.suggested_decision,
                task.assigned_to,
                task.reviewer_decision,
                task.reviewer_notes,
                getattr(task, "created_at", utc_now()),
                getattr(task, "resolved_at", None),
            ),
        )
        self._commit()

    def list_review_tasks(self, run_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(f"SELECT * FROM review_tasks {where} ORDER BY created_at", params).fetchall()
        return [dict(row) for row in rows]

    def resolve_review_task(self, task_id: str, decision: str, notes: str, reviewer: str = "analyst") -> MatchDecision:
        if decision not in ALLOWED_REVIEW_DECISIONS:
            raise ValueError(f"unsupported review decision: {decision}")
        resolved_at = utc_now()
        row = self.conn.execute("SELECT * FROM review_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise ValueError(f"review task not found: {task_id}")
        if row["status"] == "resolved":
            raise ValueError(f"review task already resolved: {task_id}")
        before = dict(row)
        self.conn.execute(
            """
            UPDATE review_tasks
            SET status = ?, reviewer_decision = ?, reviewer_notes = ?, assigned_to = ?, resolved_at = ?
            WHERE id = ?
            """,
            ("resolved", decision, notes, reviewer, resolved_at, task_id),
        )
        human_decision = MatchDecision(
            id=f"decision_{task_id}_human",
            run_id=row["run_id"],
            candidate_pair_id=row["candidate_pair_id"],
            decision=decision,
            tier="human",
            confidence=1.0,
            reason_code="human_review_resolution",
            explanation="Reviewer resolved the exception and overrode or confirmed the system recommendation.",
            evidence={
                "review_task_id": task_id,
                "previous_suggested_decision": row["suggested_decision"],
                "reviewer_notes": notes,
            },
            review_task_id=task_id,
            decided_by=reviewer,
        )
        if not self.conn.execute("SELECT 1 FROM match_decisions WHERE id = ?", (human_decision.id,)).fetchone():
            self.save_match_decision(human_decision)
            self.save_decision_audit(human_decision)
        self.save_audit_event(
            AuditEvent(
                id=new_id("audit"),
                run_id=row["run_id"],
                entity_type="review_task",
                entity_id=task_id,
                event_type="review.resolved",
                actor_type="human",
                actor_id=reviewer,
                before=before,
                after={"status": "resolved", "decision": decision, "notes": notes, "resolved_at": resolved_at},
            )
        )
        self._commit()
        return human_decision

    def get_llm_cache(self, cache_key: str) -> LLMCacheEntry | None:
        row = self.conn.execute("SELECT * FROM llm_cache WHERE cache_key = ?", (cache_key,)).fetchone()
        if row is None:
            return None
        return LLMCacheEntry(
            cache_key=row["cache_key"],
            prompt_schema_version=row["prompt_schema_version"],
            model=row["model"],
            input_hash=row["input_hash"],
            output_json=json.loads(row["output_json"]),
            decision=row["decision"],
            confidence=float(row["confidence"]),
            reason=row["reason"],
            token_estimate=int(row["token_estimate"]),
            created_at=row["created_at"],
        )

    def put_llm_cache(self, entry: LLMCacheEntry) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO llm_cache
            (cache_key, prompt_schema_version, model, input_hash, output_json, decision,
             confidence, reason, token_estimate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.cache_key,
                entry.prompt_schema_version,
                entry.model,
                entry.input_hash,
                _json(entry.output_json),
                entry.decision,
                entry.confidence,
                entry.reason,
                entry.token_estimate,
                entry.created_at,
            ),
        )
        self._commit()

    def save_audit_event(self, event: AuditEvent) -> None:
        self.conn.execute(
            """
            INSERT INTO audit_events
            (id, run_id, entity_type, entity_id, event_type, actor_type, actor_id,
             before_json, after_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.run_id,
                event.entity_type,
                event.entity_id,
                event.event_type,
                event.actor_type,
                event.actor_id,
                _json(event.before) if event.before is not None else None,
                _json(event.after) if event.after is not None else None,
                _json(event.metadata),
                event.created_at,
            ),
        )
        self._commit()

    def set_metric(self, run_id: str, key: str, value: Any) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO run_metrics(run_id, key, value, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, key, _json(value), utc_now()),
        )
        self._commit()

    def metrics(self, run_id: str) -> dict[str, Any]:
        rows = self.conn.execute("SELECT key, value FROM run_metrics WHERE run_id = ?", (run_id,)).fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def table_counts(self, run_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in ["source_files", "normalized_transactions", "candidate_pairs", "match_decisions", "review_tasks"]:
            counts[table] = int(self.conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE run_id = ?", (run_id,)).fetchone()["c"])
        counts["llm_cache"] = int(self.conn.execute("SELECT COUNT(*) AS c FROM llm_cache").fetchone()["c"])
        counts["audit_events"] = int(self.conn.execute("SELECT COUNT(*) AS c FROM audit_events WHERE run_id = ?", (run_id,)).fetchone()["c"])
        return counts

    def decisions_by_tier(self, run_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT tier, decision, COUNT(*) AS c FROM match_decisions WHERE run_id = ? GROUP BY tier, decision",
            (run_id,),
        ).fetchall()
        return {f"{row['tier']}:{row['decision']}": int(row["c"]) for row in rows}

    def list_match_decisions(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM match_decisions WHERE run_id = ? ORDER BY created_at, id",
            (run_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "evidence": json.loads(row["evidence_json"]),
            }
            for row in rows
        ]

    def list_audit_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM audit_events WHERE run_id = ? ORDER BY created_at, id",
            (run_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "before": json.loads(row["before_json"]) if row["before_json"] else None,
                "after": json.loads(row["after_json"]) if row["after_json"] else None,
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def save_decision_audit(self, decision: MatchDecision) -> None:
        self.save_audit_event(
            AuditEvent(
                id=new_id("audit"),
                run_id=decision.run_id,
                entity_type="match_decision",
                entity_id=decision.id,
                event_type="decision_created",
                actor_type="agent" if decision.tier == "llm" else "system",
                actor_id=decision.decided_by,
                after=asdict(decision),
            )
        )

    def _normalized_from_row(self, row: sqlite3.Row) -> NormalizedTransaction:
        return NormalizedTransaction(
            id=row["id"],
            run_id=row["run_id"],
            raw_transaction_id=row["raw_transaction_id"],
            account_id=row["account_id"],
            source_system=row["source_system"],
            external_transaction_id=row["external_transaction_id"],
            posting_date=row["posting_date"],
            value_date=row["value_date"],
            amount=Decimal(row["amount"]),
            currency=row["currency"],
            direction=row["direction"],
            description_raw=row["description_raw"],
            description_normalized=row["description_normalized"],
            counterparty=row["counterparty"],
            reference=row["reference"],
            fingerprint_exact=row["fingerprint_exact"],
            fingerprint_loose=row["fingerprint_loose"],
            quality_flags=json.loads(row["quality_flags_json"]),
            created_at=row["created_at"],
        )
