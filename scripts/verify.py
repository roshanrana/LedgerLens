from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run LedgerLens local verification checks.")
    parser.add_argument(
        "--docker",
        choices=["auto", "required", "skip"],
        default="auto",
        help="Docker check mode. auto runs Docker checks when the daemon is available.",
    )
    parser.add_argument(
        "--kafka-smoke",
        action="store_true",
        help="Run an opt-in Redpanda round-trip smoke after Docker checks.",
    )
    args = parser.parse_args(argv)

    run("python unit/e2e/contract tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    run_cli_smoke()
    run_docker_checks(args.docker, kafka_smoke=args.kafka_smoke)

    print("\nLedgerLens verification passed.")
    return 0


def run(label: str, command: list[str], *, cwd: Path = ROOT) -> None:
    print(f"\n==> {label}", flush=True)
    print(format_command(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def run_cli_smoke() -> None:
    print("\n==> CLI demo smoke", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ledgerlens-smoke.db"
        command = [
            sys.executable,
            "-m",
            "ledgerlens.cli",
            "--db",
            str(db_path),
            "demo",
        ]
        print(format_command(command), flush=True)
        completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode != 0:
            print(completed.stdout)
            print(completed.stderr, file=sys.stderr)
            raise SystemExit(completed.returncode)

        required = ["LedgerLens Reconciliation Report", "Run ID:", "LLM calls made"]
        missing = [text for text in required if text not in completed.stdout]
        if missing:
            print(completed.stdout)
            raise SystemExit(f"CLI smoke output missing: {', '.join(missing)}")
        print("CLI demo produced report, run id, and LLM control metrics.")


def run_docker_checks(mode: str, *, kafka_smoke: bool) -> None:
    if mode == "skip":
        print("\n==> Docker checks skipped", flush=True)
        if kafka_smoke:
            raise SystemExit("--kafka-smoke requires Docker checks")
        return

    if shutil.which("docker") is None:
        handle_docker_unavailable(mode, "docker CLI is not installed or not on PATH")
        return

    version = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if version.returncode != 0:
        handle_docker_unavailable(mode, version.stderr.strip() or "Docker daemon is not available")
        return

    print(f"\n==> Docker daemon detected ({version.stdout.strip()})", flush=True)
    run(
        "Go worker tests in Docker",
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "GOWORK=off",
            "-v",
            f"{ROOT}:/repo",
            "-w",
            "/repo/go/match-worker",
            "golang:1.23-alpine",
            "go",
            "test",
            "./...",
        ],
    )
    run("Go worker Docker build", ["docker", "build", "-t", "ledgerlens-match-worker:verify", "./go/match-worker"])
    run_go_worker_file_smoke()
    run("streaming compose config", ["docker", "compose", "--profile", "streaming", "config"])
    if kafka_smoke:
        run_kafka_smoke()


def handle_docker_unavailable(mode: str, reason: str) -> None:
    if mode == "required":
        raise SystemExit(f"Docker checks required but unavailable: {reason}")
    print(f"\n==> Docker checks skipped: {reason}", flush=True)


def run_go_worker_file_smoke() -> None:
    print("\n==> Go worker container file-mode smoke", flush=True)
    ndjson = exported_demo_events_ndjson()
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "ledgerlens-match-worker:verify",
        "--mode",
        "file",
        "--input",
        "-",
        "--output",
        "-",
    ]
    print(format_command(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, input=ndjson, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr, file=sys.stderr)
        raise SystemExit(completed.returncode)
    if "ledgerlens.match.candidate_created" not in completed.stdout:
        print(completed.stdout)
        raise SystemExit("Go worker file-mode smoke did not emit a candidate event")
    print("Go worker emitted a candidate event from Python-exported normalized events.")


def run_kafka_smoke() -> None:
    print("\n==> Redpanda Kafka round-trip smoke", flush=True)
    ndjson = exported_demo_events_ndjson()
    compose = ["docker", "compose", "-p", "ledgerlens-verify", "--profile", "streaming"]

    try:
        run("clean previous smoke stack", compose + ["down", "-v", "--remove-orphans"])
        run("start Redpanda and match worker", compose + ["up", "-d", "--build", "redpanda", "match-worker"])
        wait_for_redpanda(compose)
        create_smoke_topics(compose)
        produce = compose + [
            "exec",
            "-T",
            "redpanda",
            "rpk",
            "-X",
            "brokers=localhost:9092",
            "topic",
            "produce",
            "ledgerlens.transaction.normalized",
            "--format",
            "%v\n",
            "--output-format",
            "",
        ]
        print("\n==> produce normalized events to Kafka", flush=True)
        print(format_command(produce), flush=True)
        produced = subprocess.run(produce, cwd=ROOT, input=ndjson, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if produced.returncode != 0:
            print(produced.stdout)
            print(produced.stderr, file=sys.stderr)
            raise SystemExit(produced.returncode)

        candidate = consume_candidate(compose)
        if candidate.get("event_type") != "ledgerlens.match.candidate_created":
            raise SystemExit(f"unexpected Kafka candidate event: {candidate}")
        print("Kafka smoke produced a normalized event and consumed a candidate event.")
    finally:
        subprocess.run(compose + ["down", "-v", "--remove-orphans"], cwd=ROOT, text=True)


def wait_for_redpanda(compose: list[str]) -> None:
    command = compose + ["exec", "-T", "redpanda", "rpk", "cluster", "health"]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        combined = f"{completed.stdout}\n{completed.stderr}".lower()
        if completed.returncode == 0 and re.search(r"healthy:\s*true", combined):
            print("Redpanda is healthy.")
            return
        time.sleep(2)
    print(completed.stdout)
    print(completed.stderr, file=sys.stderr)
    raise SystemExit("Redpanda did not become healthy in time")


def create_smoke_topics(compose: list[str]) -> None:
    for topic in ["ledgerlens.transaction.normalized", "ledgerlens.match.candidate_created"]:
        command = compose + [
            "exec",
            "-T",
            "redpanda",
            "rpk",
            "-X",
            "brokers=localhost:9092",
            "topic",
            "create",
            topic,
        ]
        print(f"\n==> create smoke topic {topic}", flush=True)
        print(format_command(command), flush=True)
        completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        combined = f"{completed.stdout}\n{completed.stderr}"
        if completed.returncode != 0 and "TOPIC_ALREADY_EXISTS" not in combined:
            print(completed.stdout)
            print(completed.stderr, file=sys.stderr)
            raise SystemExit(completed.returncode)


def consume_candidate(compose: list[str]) -> dict[str, object]:
    command = compose + [
        "exec",
        "-T",
        "redpanda",
        "rpk",
        "-X",
        "brokers=localhost:9092",
        "topic",
        "consume",
        "ledgerlens.match.candidate_created",
        "--num",
        "1",
        "--offset",
        "start",
        "--format",
        "%v\n",
    ]
    print("\n==> consume candidate event from Kafka", flush=True)
    print(format_command(command), flush=True)
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except subprocess.TimeoutExpired as exc:
        print(exc.stdout or "")
        print(exc.stderr or "", file=sys.stderr)
        raise SystemExit("timed out waiting for candidate event") from exc
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr, file=sys.stderr)
        raise SystemExit(completed.returncode)
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
    raise SystemExit("Kafka smoke did not consume a candidate event")


def exported_demo_events_ndjson() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ledgerlens-events.db"
        demo = subprocess.run(
            [sys.executable, "-m", "ledgerlens.cli", "--db", str(db_path), "demo"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if demo.returncode != 0:
            print(demo.stdout)
            print(demo.stderr, file=sys.stderr)
            raise SystemExit(demo.returncode)
        run_id = parse_run_id(demo.stdout)
        export = subprocess.run(
            [sys.executable, "-m", "ledgerlens.cli", "--db", str(db_path), "export-normalized-events", run_id],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if export.returncode != 0:
            print(export.stdout)
            print(export.stderr, file=sys.stderr)
            raise SystemExit(export.returncode)
        events = [json.loads(line) for line in export.stdout.splitlines() if line.strip()]
        if len(events) < 2:
            raise SystemExit("expected at least two exported normalized events")
        if any(event["event_type"] != "ledgerlens.transaction.normalized" for event in events):
            raise SystemExit("exported event stream contains non-normalized events")
        return export.stdout


def parse_run_id(output: str) -> str:
    for line in reversed(output.splitlines()):
        if line.startswith("Run ID:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("CLI demo smoke did not print a run id")


def format_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command).replace("\n", "\\n")


if __name__ == "__main__":
    raise SystemExit(main())
