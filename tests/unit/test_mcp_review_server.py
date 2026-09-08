"""LL-3: the ``ledgerlens-review`` MCP server over an in-memory client and over stdio."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from ledgerlens.api import resources
from ledgerlens.llm.masking import MASKING_VERSION
from ledgerlens.mcp import server as mcp_server
from ledgerlens.mcp.server import (
    COMPLETION_UNAVAILABLE,
    DEFAULT_DB_PATH,
    ENV_DB_PATH,
    SERVER_NAME,
    TOOL_NAMES,
    build_server,
    db_path_from_env,
)
from ledgerlens.persistence.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSVS = (
    ROOT / "data" / "samples" / "acme_bank_statement.csv",
    ROOT / "data" / "samples" / "acme_ledger_export.csv",
)
# Column names under which the sample feeds carry counterparties and references.
SENSITIVE_COLUMNS = ("Counterparty", "Customer", "Reference", "Invoice")
REVIEW_NOTES = "Bank fee wording is similar but policy requires manual no-match."
REVIEWER = "review-mcp"


def _raw_sensitive_values() -> set[str]:
    """Every non-empty counterparty/reference string in the sample CSVs run_demo ingests."""
    values: set[str] = set()
    for path in SAMPLE_CSVS:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                for column in SENSITIVE_COLUMNS:
                    value = (row.get(column) or "").strip()
                    if value:
                        values.add(value)
    return values


def _service_available() -> bool:
    return callable(getattr(resources, "complete_review", None))


class _SeededServerCase(unittest.IsolatedAsyncioTestCase):
    """Seeds a temp DB with run_demo (one open review task) and builds a server over it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "ledgerlens.db"
        demo = resources.run_demo(self.db_path, client_id="acme")
        self.run_id: str = demo["run_id"]
        open_tasks = [task for task in demo["review_tasks"] if task["status"] == "open"]
        self.assertEqual(len(open_tasks), 1, "run_demo is expected to leave exactly one open task")
        self.task_id: str = open_tasks[0]["id"]
        self.server = build_server(self.db_path)

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async with Client(self.server) as client:
            result = await client.call_tool(name, arguments or {})
        self.assertFalse(result.is_error, f"{name} raised across the MCP boundary: {result.content}")
        self.assertIsInstance(result.structured_content, dict)
        return dict(result.structured_content)

    def store(self) -> SQLiteStore:
        store = SQLiteStore(self.db_path)
        self.addCleanup(store.close)
        return store


class ServerShapeTests(_SeededServerCase):
    async def test_server_exposes_the_seven_design_tools_with_docstrings(self) -> None:
        self.assertEqual(self.server.name, SERVER_NAME)
        async with Client(self.server) as client:
            listed = await client.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        self.assertEqual(tuple(by_name), TOOL_NAMES)
        for name, tool in by_name.items():
            description = (tool.description or "").strip()
            self.assertGreater(len(description), 120, f"{name} needs a docstring an LLM can act on")
            self.assertIn("error", description, f"{name} does not explain its error behaviour")

    async def test_every_tool_opens_and_closes_its_own_store(self) -> None:
        opened: list[_TrackingStore] = []

        class _TrackingStore(SQLiteStore):
            def __init__(self, db_path: str | Path):
                super().__init__(db_path)
                self.closed = False
                opened.append(self)

            def close(self) -> None:
                self.closed = True
                super().close()

        with mock.patch.object(mcp_server, "SQLiteStore", _TrackingStore):
            await self.call("list_runs")
            await self.call("get_run", {"run_id": self.run_id})
            await self.call("get_review_pair", {"task_id": self.task_id})
            await self.call("get_report", {"run_id": self.run_id})
            await self.call("get_run", {"run_id": "missing"})  # error path must close too
        self.assertEqual(len(opened), 5)
        self.assertTrue(all(store.closed for store in opened))


class ReadToolTests(_SeededServerCase):
    async def test_list_runs_and_get_run(self) -> None:
        runs = await self.call("list_runs", {"limit": 5})
        self.assertEqual([run["id"] for run in runs["runs"]], [self.run_id])
        self.assertEqual(runs["runs"][0]["client_id"], "acme")

        run = await self.call("get_run", {"run_id": self.run_id})
        self.assertEqual(run["run"]["id"], self.run_id)
        self.assertEqual(run["open_review_tasks"], 1)
        self.assertEqual(run["counts"]["review_tasks"], 1)
        self.assertEqual(run["decisions_by_tier"].get("llm:needs_review"), 1)

        self.assertIn("error", await self.call("list_runs", {"limit": 0}))
        self.assertEqual(await self.call("get_run", {"run_id": "run_missing"}), {"error": "run not found: run_missing"})

    async def test_list_review_tasks_filters_by_status(self) -> None:
        all_tasks = await self.call("list_review_tasks", {"run_id": self.run_id})
        self.assertEqual([task["id"] for task in all_tasks["tasks"]], [self.task_id])

        open_tasks = await self.call("list_review_tasks", {"run_id": self.run_id, "status": "open"})
        self.assertEqual(len(open_tasks["tasks"]), 1)
        self.assertEqual(open_tasks["status"], "open")

        resolved = await self.call("list_review_tasks", {"run_id": self.run_id, "status": "resolved"})
        self.assertEqual(resolved["tasks"], [])

        self.assertIn("error", await self.call("list_review_tasks", {"run_id": "run_missing"}))

    async def test_get_review_pair_is_masked_and_carries_machine_decision(self) -> None:
        result = await self.call("get_review_pair", {"task_id": self.task_id})

        self.assertEqual(result["task"]["id"], self.task_id)
        pair = result["pair"]
        self.assertEqual(pair["pair_id"], result["task"]["candidate_pair_id"])
        self.assertEqual(pair["masking_version"], MASKING_VERSION)
        self.assertIn("candidate_score", pair["features"])
        for side in ("left", "right"):
            self.assertNotIn("counterparty", pair[side])
            self.assertNotIn("reference", pair[side])
            self.assertIn("counterparty_token", pair[side])
            self.assertIn("reference_token", pair[side])
            self.assertEqual(pair[side]["masking_version"], MASKING_VERSION)

        machine = result["machine_decision"]
        self.assertIsNotNone(machine)
        self.assertNotEqual(machine["tier"], "human")
        self.assertEqual(machine["reason_code"], result["task"]["reason"])
        self.assertEqual(machine["decision"], result["task"]["suggested_decision"])
        self.assertIsInstance(machine["confidence"], float)
        self.assertTrue(machine["explanation"])

        self.assertEqual(
            await self.call("get_review_pair", {"task_id": "review_missing"}),
            {"error": "review task not found: review_missing"},
        )

    async def test_get_report_returns_markdown_and_counts(self) -> None:
        report = await self.call("get_report", {"run_id": self.run_id})
        self.assertEqual(report["run_id"], self.run_id)
        self.assertIn("# LedgerLens Reconciliation Report", report["report"])
        self.assertIn("Open review tasks: 1", report["report"])
        self.assertEqual(report["counts"]["review_tasks"], 1)
        self.assertIn("error", await self.call("get_report", {"run_id": "run_missing"}))


class DataPerimeterTests(_SeededServerCase):
    async def test_no_tool_result_contains_raw_counterparty_or_reference(self) -> None:
        raw_values = _raw_sensitive_values()
        self.assertGreaterEqual(len(raw_values), 8)
        self.assertIn("ACME CORP", raw_values)
        self.assertIn("INV-8127", raw_values)

        results = [
            await self.call("list_runs"),
            await self.call("get_run", {"run_id": self.run_id}),
            await self.call("list_review_tasks", {"run_id": self.run_id}),
            await self.call("get_review_pair", {"task_id": self.task_id}),
            await self.call("get_report", {"run_id": self.run_id}),
            await self.call("complete_review", {"run_id": self.run_id, "reviewer": REVIEWER}),
            await self.call(
                "resolve_review_task",
                {"task_id": self.task_id, "decision": "no_match", "notes": REVIEW_NOTES, "reviewer": REVIEWER},
            ),
            await self.call("get_review_pair", {"task_id": self.task_id}),
            await self.call("list_review_tasks", {"run_id": self.run_id, "status": "resolved"}),
        ]
        serialized = json.dumps(results)
        for raw in sorted(raw_values):
            self.assertNotIn(raw, serialized, f"raw value {raw!r} leaked through a tool result")

        # And the store really does hold the raw values, so the masking is doing the work.
        store = self.store()
        pair = store.get_candidate_pair(results[3]["pair"]["pair_id"])
        self.assertIn(pair.left.counterparty or pair.right.counterparty, raw_values)


class ResolveReviewTaskTests(_SeededServerCase):
    async def _task_status(self) -> str:
        return self.store().list_review_tasks(run_id=self.run_id)[0]["status"]

    async def test_resolve_refuses_blank_reviewer_or_notes_and_bad_decisions(self) -> None:
        base = {"task_id": self.task_id, "decision": "no_match"}
        for arguments in (
            {**base, "notes": REVIEW_NOTES, "reviewer": ""},
            {**base, "notes": REVIEW_NOTES, "reviewer": "   "},
            {**base, "notes": "", "reviewer": REVIEWER},
            {**base, "notes": " \n", "reviewer": REVIEWER},
        ):
            result = await self.call("resolve_review_task", arguments)
            self.assertIn("error", result, arguments)
            self.assertRegex(result["error"], r"(reviewer|notes) is required")

        bad = await self.call(
            "resolve_review_task",
            {"task_id": self.task_id, "decision": "approve", "notes": REVIEW_NOTES, "reviewer": REVIEWER},
        )
        self.assertEqual(bad, {"error": "unsupported review decision: approve"})
        self.assertEqual(await self._task_status(), "open")

    async def test_resolve_delegates_to_store_and_refuses_a_second_resolution(self) -> None:
        arguments = {"task_id": self.task_id, "decision": "no_match", "notes": REVIEW_NOTES, "reviewer": REVIEWER}
        result = await self.call("resolve_review_task", arguments)

        self.assertEqual(result["task"]["status"], "resolved")
        self.assertEqual(result["task"]["reviewer_decision"], "no_match")
        self.assertEqual(result["task"]["reviewer_notes"], REVIEW_NOTES)
        self.assertEqual(result["task"]["assigned_to"], REVIEWER)
        self.assertEqual(result["decision"]["tier"], "human")
        self.assertEqual(result["decision"]["decision"], "no_match")
        self.assertEqual(result["decision"]["decided_by"], REVIEWER)
        self.assertEqual(result["decision"]["review_task_id"], self.task_id)
        self.assertEqual(await self._task_status(), "resolved")

        again = await self.call("resolve_review_task", {**arguments, "decision": "match"})
        self.assertEqual(again, {"error": f"review task already resolved: {self.task_id}"})

        unknown = await self.call("resolve_review_task", {**arguments, "task_id": "review_missing"})
        self.assertEqual(unknown, {"error": "review task not found: review_missing"})


class CompleteReviewTests(_SeededServerCase):
    async def test_complete_review_refuses_while_tasks_are_open(self) -> None:
        result = await self.call("complete_review", {"run_id": self.run_id, "reviewer": REVIEWER})
        self.assertIn("error", result)
        self.assertRegex(result["error"], r"open review task")
        self.assertEqual(self.store().open_review_task_count(self.run_id), 1)

    async def test_complete_review_requires_reviewer_and_known_run(self) -> None:
        blank = await self.call("complete_review", {"run_id": self.run_id, "reviewer": " "})
        self.assertEqual(blank, {"error": "reviewer is required and must not be empty"})
        unknown = await self.call("complete_review", {"run_id": "run_missing", "reviewer": REVIEWER})
        self.assertEqual(unknown, {"error": "run not found: run_missing"})

    async def test_complete_review_after_resolution_delegates_or_reports_unavailable(self) -> None:
        await self.call(
            "resolve_review_task",
            {"task_id": self.task_id, "decision": "no_match", "notes": REVIEW_NOTES, "reviewer": REVIEWER},
        )
        result = await self.call("complete_review", {"run_id": self.run_id, "reviewer": REVIEWER, "note": "ok"})

        if _service_available():
            self.assertNotIn("error", result, f"resources.complete_review refused: {result}")
            self.assertEqual(self.store().get_run(self.run_id)["status"], "completed")
        else:
            self.assertEqual(result, {"error": COMPLETION_UNAVAILABLE})

    async def test_complete_review_calls_the_service_lazily_with_keyword_arguments(self) -> None:
        await self.call(
            "resolve_review_task",
            {"task_id": self.task_id, "decision": "no_match", "notes": REVIEW_NOTES, "reviewer": REVIEWER},
        )
        calls: list[tuple[Any, ...]] = []

        def fake_complete_review(db_path: Path, run_id: str, *, reviewer: str, note: str = "") -> dict[str, Any]:
            calls.append((Path(db_path), run_id, reviewer, note))
            return {"run_id": run_id, "status": "completed"}

        with mock.patch.object(resources, "complete_review", fake_complete_review, create=True):
            result = await self.call("complete_review", {"run_id": self.run_id, "reviewer": REVIEWER, "note": "ok"})

        self.assertEqual(result, {"run_id": self.run_id, "status": "completed"})
        self.assertEqual(calls, [(self.db_path, self.run_id, REVIEWER, "ok")])


class EntryPointTests(unittest.TestCase):
    def test_db_path_defaults_and_honours_env(self) -> None:
        self.assertEqual(db_path_from_env({}), DEFAULT_DB_PATH)
        self.assertEqual(db_path_from_env({ENV_DB_PATH: ""}), DEFAULT_DB_PATH)
        self.assertEqual(db_path_from_env({ENV_DB_PATH: "C:/tmp/x.db"}), Path("C:/tmp/x.db"))

    def test_main_runs_the_server_over_stdio(self) -> None:
        with mock.patch.object(mcp_server, "build_server") as build:
            with mock.patch.dict(os.environ, {ENV_DB_PATH: "somewhere.db"}):
                mcp_server.main()
        build.assert_called_once_with(Path("somewhere.db"))
        build.return_value.run.assert_called_once_with("stdio")


class StdioSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_python_m_ledgerlens_mcp_server_lists_runs_over_stdio(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = Path(tmp) / "ledgerlens.db"
            demo = resources.run_demo(db_path, client_id="acme")
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "ledgerlens.mcp.server"],
                env={**os.environ, ENV_DB_PATH: str(db_path)},
                cwd=ROOT,
            )
            async with Client(params) as client:
                listed = await client.list_tools()
                result = await client.call_tool("list_runs", {"limit": 5})

            self.assertEqual({tool.name for tool in listed.tools}, set(TOOL_NAMES))
            self.assertFalse(result.is_error)
            self.assertEqual([run["id"] for run in result.structured_content["runs"]], [demo["run_id"]])


if __name__ == "__main__":
    unittest.main()
