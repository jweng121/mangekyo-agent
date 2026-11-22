"""Command-line interface for local history, recovery, and interfaces."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .demo import benchmark, resume, run_demo
from .store import Store, default_path


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mangekyo", description="Inspect and recover local agent runs")
    parser.add_argument("--home", type=Path, help="Local store path (also MANGEKYO_HOME)")
    parser.add_argument("--tui", action="store_true", help="Open the interactive terminal UI")
    sub = parser.add_subparsers(dest="command")
    setup = sub.add_parser("setup", help="Initialize local history and optionally connect a Python project")
    setup.add_argument("--project", type=Path, help="Install the SDK into this project's .venv")
    setup.add_argument("--browser", action="store_true", help="Install Chromium for optional browser capture")
    init = sub.add_parser("init", help="Alias for setup")
    init.add_argument("--project", type=Path)
    init.add_argument("--browser", action="store_true")
    sub.add_parser("demo", help="Record a contained failing reference run")
    run = sub.add_parser("run", help="Launch a command and automatically identify its run")
    run.add_argument("--label", help="Human-readable task label")
    run.add_argument("argv", nargs=argparse.REMAINDER, help="Command to launch after --")
    sub.add_parser("log", help="List runs and branches")
    show = sub.add_parser("show", help="Show a run, event, snapshot, or branch")
    show.add_argument("id")
    diff = sub.add_parser("diff", help="Compare two snapshots")
    diff.add_argument("a")
    diff.add_argument("b")
    branch = sub.add_parser("branch", help="Create a correction branch")
    branch.add_argument("snapshot")
    branch.add_argument("-m", "--name", required=True)
    branch.add_argument("--replacement", default="safe", help="Reference agent correction")
    replay = sub.add_parser("replay", help="Display recorded events without executing")
    replay.add_argument("id", help="Run or snapshot ID")
    recover = sub.add_parser("resume", help="Resume a compatible branch")
    recover.add_argument("branch")
    bench = sub.add_parser("benchmark", help="Report measured snapshot reuse")
    bench.add_argument("run")
    bench.add_argument("--openai-model", help="Also make two real Responses API requests to probe prompt caching")
    bench.add_argument("--api-key-env", default="OPENAI_API_KEY")
    bench.add_argument("--base-url", default="https://api.openai.com/v1/responses")
    bench.add_argument("--input-price", type=float, help="USD per 1M ordinary input tokens")
    bench.add_argument("--cached-price", type=float, help="USD per 1M cached input tokens")
    bench.add_argument("--cache-write-price", type=float, help="USD per 1M cache write tokens")
    bench.add_argument("--output-price", type=float, help="USD per 1M output tokens")
    cache = sub.add_parser("cache", help="Storage usage")
    cache.add_argument("action", choices=["stats"])
    dashboard = sub.add_parser("dashboard", help="Open local web dashboard")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--no-open", action="store_true")
    sub.add_parser("doctor", help="Check local installation and store")
    evidence = sub.add_parser("evidence", help="Attach a document or Chromium capture to a run")
    evidence.add_argument("action", choices=["add", "capture"])
    evidence.add_argument("run", help="Existing run ID")
    evidence.add_argument("source", help="File path for add, URL for capture")
    evidence.add_argument("--event", help="Event ID the agent used this evidence for")
    evidence.add_argument("--parsed-text-file", type=Path, help="Exact parsed text to show beside the original file")
    return parser


def show_item(store: Store, ident: str) -> dict[str, Any]:
    for table in ("runs", "events", "snapshots", "branches"):
        try:
            data = store.one(table, ident)
        except KeyError:
            continue
        if table == "runs":
            data["events"] = store.events(ident)
            data["snapshots"] = store.snapshots(ident)
            data["artifacts"] = store.artifacts(ident)
        elif table == "events":
            data["payload"] = store.get(data["payload_hash"])
        elif table == "snapshots":
            data["context"] = store.context(ident)
            data["environment_restorable"] = bool(data["env_hash"] and data["adapter"] == "mangekyo.simulation")
        elif table == "branches":
            data["correction"] = store.get(data["correction_hash"])
        return {"type": table[:-1], **data}
    raise KeyError(f"No run, event, snapshot, or branch: {ident}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        home = (args.home or default_path()).resolve()
        checks: dict[str, Any] = {"python": sys.version.split()[0], "store": str(home),
                                  "store_exists": (home / "history.sqlite3").exists()}
        try:
            with Store(home) as store:
                checks["schema"] = "ok"
                checks["runs"] = len(store.runs())
        except Exception as exc:
            checks["schema"] = f"error: {exc}"
        print_json(checks)
        return 0 if checks["schema"] == "ok" else 1
    if not args.command and not args.tui:
        build_parser().print_help()
        return 0
    try:
        with Store(args.home) as store:
            if args.tui:
                from .tui import run_tui
                run_tui(store)
            elif args.command in {"setup", "init"}:
                print(f"Mangekyo store ready: {store.path}")
                if args.project:
                    from .setup_project import connect_project
                    print("Connecting project virtual environment...")
                    print("SDK import verified: " + connect_project(args.project))
                if args.browser:
                    from .evidence import install_chromium
                    print("Installing Chromium for browser evidence...")
                    install_chromium()
                    print("Chromium ready")
                print("Next: mangekyo demo")
            elif args.command == "demo":
                result = run_demo(store)
                print_json(result)
                print("Next: mangekyo show " + result["run_id"])
                print("Or:   mangekyo --tui / mangekyo dashboard")
            elif args.command == "run":
                from .launch import launch
                return launch(store, args.argv, args.label)
            elif args.command == "log":
                print_json({"runs": store.runs(), "branches": store.branches()})
            elif args.command == "show":
                print_json(show_item(store, args.id))
            elif args.command == "diff":
                a, b = store.context(args.a), store.context(args.b)
                print_json({"a": args.a, "b": args.b, "changed": {
                    k: {"before": a.get(k), "after": b.get(k)} for k in sorted(a.keys() | b.keys())
                    if a.get(k) != b.get(k)}})
            elif args.command == "branch":
                store.branch(args.snapshot, args.name, {"replacement": args.replacement})
                print(f"Created branch {args.name} from {args.snapshot}")
                print(f"Next: mangekyo resume {args.name}")
            elif args.command == "replay":
                try:
                    run_id = store.one("snapshots", args.id)["run_id"]
                except KeyError:
                    run_id = args.id
                    store.one("runs", run_id)
                print_json({"mode": "recorded replay; no execution", "events": store.events(run_id)})
            elif args.command == "resume":
                print_json(resume(store, args.branch))
            elif args.command == "benchmark":
                report = benchmark(store, args.run, create_baseline=True)
                if args.openai_model:
                    from .provider import probe_openai_cache
                    values = (args.input_price, args.cached_price, args.cache_write_price, args.output_price)
                    if any(v is not None for v in values) and not all(v is not None for v in values):
                        raise ValueError("Provide all four token prices or none")
                    prices = dict(zip(("input", "cached", "cache_write", "output"), values)) if all(v is not None for v in values) else None
                    print("Sending the first snapshot's captured context to the configured model provider for two requests.")
                    report["provider_probe"] = probe_openai_cache(store, args.run, args.openai_model,
                        api_key_env=args.api_key_env, base_url=args.base_url, prices=prices)
                print_json(report)
            elif args.command == "cache":
                print_json(store.stats())
            elif args.command == "dashboard":
                from .dashboard import serve
                serve(store.path, port=args.port, open_browser=not args.no_open)
            elif args.command == "evidence":
                from .evidence import add_file, capture_url
                if args.action == "add":
                    parsed = args.parsed_text_file.read_text(encoding="utf-8") if args.parsed_text_file else None
                    ident = add_file(store, args.run, Path(args.source), event_id=args.event, parsed_text=parsed)
                else:
                    if args.parsed_text_file:
                        raise ValueError("Browser capture extracts the page text automatically")
                    ident = capture_url(store, args.run, args.source, event_id=args.event)
                print_json({"artifact_id": ident, "run_id": args.run,
                            "dashboard": "mangekyo dashboard"})
    except (KeyError, ValueError, sqlite3.Error, OSError, RuntimeError) as exc:
        print(f"mangekyo: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
