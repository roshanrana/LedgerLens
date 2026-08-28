from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .schemas import LLMDecision


class InMemoryLLMCache:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[LLMDecision, int]] = {}

    def get(self, cache_key: str) -> LLMDecision | None:
        entry = self._entries.get(cache_key)
        return entry[0] if entry else None

    def set(self, cache_key: str, decision: LLMDecision, *, token_estimate: int = 0) -> None:
        self._entries[cache_key] = (decision, token_estimate)

    def stats(self) -> dict[str, int]:
        return {"entries": len(self._entries)}


class SQLiteLLMCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_schema(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS llm_cache (
                        cache_key TEXT PRIMARY KEY,
                        output_json TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        reason_code TEXT NOT NULL,
                        explanation TEXT NOT NULL,
                        token_estimate INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

    def get(self, cache_key: str) -> LLMDecision | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT output_json FROM llm_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        return LLMDecision.from_json(json.loads(row[0]))

    def set(self, cache_key: str, decision: LLMDecision, *, token_estimate: int = 0) -> None:
        output_json = json.dumps(decision.to_json(), sort_keys=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO llm_cache (
                        cache_key, output_json, decision, confidence, reason_code, explanation, token_estimate
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        output_json = excluded.output_json,
                        decision = excluded.decision,
                        confidence = excluded.confidence,
                        reason_code = excluded.reason_code,
                        explanation = excluded.explanation,
                        token_estimate = excluded.token_estimate
                    """,
                    (
                        cache_key,
                        output_json,
                        decision.decision,
                        decision.confidence,
                        decision.reason_code,
                        decision.explanation,
                        token_estimate,
                    ),
                )

    def stats(self) -> dict[str, int]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) FROM llm_cache").fetchone()
        return {"entries": int(row[0])}


class StoreLLMCache:
    def __init__(self, store) -> None:
        self.store = store

    def get(self, cache_key: str) -> LLMDecision | None:
        entry = self.store.get_llm_cache(cache_key)
        if entry is None:
            return None
        return LLMDecision(
            decision=entry.decision,
            confidence=float(entry.confidence),
            reason_code=entry.reason,
            explanation=str(entry.output_json.get("explanation", entry.reason)),
        )

    def set(self, cache_key: str, decision: LLMDecision, *, token_estimate: int = 0) -> None:
        from ledgerlens.domain import LLMCacheEntry
        from .schemas import MODEL_FAMILY, PROMPT_SCHEMA_VERSION

        self.store.put_llm_cache(
            LLMCacheEntry(
                cache_key=cache_key,
                prompt_schema_version=PROMPT_SCHEMA_VERSION,
                model=MODEL_FAMILY,
                input_hash=cache_key,
                output_json=decision.to_json(),
                decision=decision.decision,
                confidence=decision.confidence,
                reason=decision.reason_code,
                token_estimate=token_estimate,
            )
        )

    def stats(self) -> dict[str, int]:
        try:
            row = self.store.conn.execute("SELECT COUNT(*) AS c FROM llm_cache").fetchone()
            return {"entries": int(row["c"])}
        except Exception:
            return {"entries": 0}
