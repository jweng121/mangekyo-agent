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
    sub.add_parser("chat", help="Converse about agent runs; guides first-time model setup")
    sub.add_parser("model", help="Configure the debugging chat model")
    sample = sub.add_parser("sample", help="Create an isolated PDF-backed agent for the walkthrough")
    sample.add_argument("destination", type=Path, nargs="?", default=Path("mangekyo-sample-agent"))
    add = sub.add_parser("add", help="Register an agent project and inspect capture capabilities")
    add.add_argument("project", type=Path, nargs="?", default=Path("."))
    add.add_argument("--graph", action="append", default=[], metavar="NAME=MODULE:FACTORY",
                     help="Register a resumable LangGraph graph factory")
    setup = sub.add_parser("setup", help="Initialize local history and optionally connect a Python project")
    setup.add_argument("--project", type=Path, help="Install the SDK into this project's .venv")
    setup.add_argument("--browser", action="store_true", help="Install Chromium for optional browser capture")
    init = sub.add_parser("init", help="Alias for setup")
    init.add_argument("--project", type=Path)
    init.add_argument("--browser", action="store_true")
    sub.add_parser("demo", help="Record a contained failing reference run")
    run = sub.add_parser("run", help="Launch a command and automatically identify its run")
    run.add_argument("--label", help="Human-readable task label")
    run.add_argument("--capture-output", action="store_true",
                     help="Save up to 256 KB each of child stdout and stderr for batch commands")
    run.add_argument("argv", nargs=argparse.REMAINDER, help="Command to launch after --")
    ingest = sub.add_parser("ingest", help="Import a language-neutral JSON run trace")
    ingest.add_argument("file", type=Path)
    sub.add_parser("log", help="List runs and branches")
    show = sub.add_parser("show", help="Show a run, event, snapshot, or branch")
    show.add_argument("id")
    check = sub.add_parser("check", help="Check a run against an expected outcome in JSON")
    check.add_argument("run", help="Run ID to evaluate")
    check.add_argument("--case", type=Path, required=True,
                       help="JSON file with expected event payload and optional kind or event_id")
    mark = sub.add_parser("mark", help="Mark a suspected or eval-verified wrong step")
    mark.add_argument("run")
    mark.add_argument("--event", required=True)
    mark.add_argument("--reason", required=True)
    diff = sub.add_parser("diff", help="Compare two snapshots")
    diff.add_argument("a")
    diff.add_argument("b")
    branch = sub.add_parser("branch", help="Create a correction branch")
    branch.add_argument("source", help="Snapshot ID, or run ID when --at is set")
    branch.add_argument("-m", "--name", required=True)
    branch.add_argument("--at", help="Snapshot ID within the selected run")
    branch.add_argument("--correction-file", type=Path,
                        help="JSON object with corrected runtime state")
    branch.add_argument("--replacement", default="safe", help="Reference agent correction")
    commit = sub.add_parser("commit", help="Save a corrected branch snapshot and passing check")
    commit.add_argument("branch")
    push = sub.add_parser("push", help="Train, evaluate, and activate a user-owned model")
    push.add_argument("commit")
    push.add_argument("--project", type=Path, default=Path("."))
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
    bundle = sub.add_parser("bundle", help="Export or import a portable run history bundle")
    bundle_sub = bundle.add_subparsers(dest="bundle_action", required=True)
    bundle_export = bundle_sub.add_parser("export", help="Export a run and its family")
    bundle_export.add_argument("run")
    bundle_export.add_argument("file", type=Path)
    bundle_import = bundle_sub.add_parser("import", help="Import a verified run bundle")
    bundle_import.add_argument("file", type=Path)
    team = sub.add_parser("team", help="Run an optional authenticated team server")
    team.add_argument("--root", type=Path, required=True, help="Team server storage directory")
    team.add_argument("--config", type=Path, required=True, help="Team user config JSON")
    team.add_argument("--host", default="127.0.0.1")
    team.add_argument("--port", type=int, default=8780)
    team.add_argument("--cert", type=Path, help="TLS certificate for remote access")
    team.add_argument("--key", type=Path, help="TLS private key for remote access")
    dashboard = sub.add_parser("dashboard", help="Open local web dashboard")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--no-open", action="store_true")
    sub.add_parser("doctor", help="Check local installation and store")
    evidence = sub.add_parser("evidence", help="Attach a document or Chromium capture to a run")
    evidence.add_argument("action", choices=["add", "capture"])
    evidence.add_argument("run", help="Existing run ID")
    evidence.add_argument("source", help="File path for add, URL for capture")
    evidence.add_argument("--event", help="Event ID the agent used this evidence for")
    evidence.add_argument("--selector", help="Browser target to locate and highlight")
    evidence.add_argument("--mask-selector", action="append", default=[],
                          help="Hide a matching page region in a browser screenshot; repeat as needed")
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
            from .checks import outcome_from_events
            from .capture import capture_report
            data["outcome"] = outcome_from_events(data["events"])
            data["snapshots"] = store.snapshots(ident)
            data["artifacts"] = store.artifacts(ident)
            data["capture"] = capture_report(store, ident, events=data["events"],
                                             snapshots=data["snapshots"], artifacts=data["artifacts"])
        elif table == "events":
            data["payload"] = store.get(data["payload_hash"])
        elif table == "snapshots":
            data["context"] = store.context(ident)
            data["environment_restorable"] = bool(data["env_hash"] and data["adapter"] == "mangekyo.simulation")
        elif table == "branches":
            data["correction"] = store.get(data["correction_hash"])
            if data["result_run"]:
                from .langgraph_api import _with_cache_note
                saved = next((event["payload"] for event in store.events(data["result_run"])
                              if event["kind"] == "branch_benchmark"), None)
                data["benchmark"] = _with_cache_note(saved) if saved else None
        return {"type": table[:-1], **data}
    raise KeyError(f"No run, event, snapshot, or branch: {ident}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "add":
        from .project import add_project
        print_json(add_project(args.project, args.graph))
        return 0
    if args.command == "team":
        from .team import serve_team
        serve_team(args.root, args.config, host=args.host, port=args.port,
                   cert=args.cert, key=args.key)
        return 0
    if args.command == "doctor":
        home = (args.home or default_path()).resolve()
        checks: dict[str, Any] = {"python": sys.version.split()[0], "store": str(home),
                                  "store_exists": (home / "history.sqlite3").exists()}
        if not checks["store_exists"]:
            checks["schema"] = "missing"
            checks["fix"] = "Run mangekyo setup in this directory, or pass --home PATH for an existing store."
            print_json(checks)
            return 1
        try:
            with Store(home) as store:
                checks["schema"] = "ok"
                checks["runs"] = len(store.runs())
                integrity = store.db.execute("PRAGMA integrity_check").fetchone()[0]
                checks["database_integrity"] = integrity
                if integrity != "ok":
                    checks["fix"] = "Restore this store from a backup; keep the damaged store for inspection."
        except Exception as exc:
            checks["schema"] = f"error: {exc}"
            checks["fix"] = ("Upgrade Mangekyo to a version that supports this store."
                             if "Unsupported storage schema" in str(exc)
                             else "Check store permissions and restore a damaged database from backup.")
        print_json(checks)
        return 0 if checks["schema"] == "ok" and checks.get("database_integrity") == "ok" else 1
    if not args.command and not args.tui:
        build_parser().print_help()
        return 0
    try:
        with Store(args.home) as store:
            if args.tui:
                from .tui import run_tui
                run_tui(store)
            elif args.command == "chat":
                from .chat import run_chat
                run_chat(store)
            elif args.command == "model":
                from .chat import configure_model
                configure_model(store.path)
            elif args.command == "sample":
                from .sample_project import create_sample
                print(f"Sample agent ready: {create_sample(args.destination)}")
            elif args.command in {"setup", "init"}:
                print(f"Mangekyo store ready: {store.path}")
                if args.project:
                    from .setup_project import connect_project
                    print("Connecting project virtual environment...")
                    print("SDK import verified: " + connect_project(args.project))
                    print("Add recording at a model or tool boundary in your agent:")
                    print('from mangekyo import RunRecorder, Store\n'
                          'with Store() as store, RunRecorder(store, "my-agent", "my task") as run:\n'
                          '    run.record("tool", name="read", result="observed value")')
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
                return launch(store, args.argv, args.label, capture_output=args.capture_output)
            elif args.command == "ingest":
                from .ingest import ingest_run
                document = json.loads(args.file.read_text(encoding="utf-8"))
                if not isinstance(document, dict):
                    raise ValueError("Trace must be a JSON object")
                if os.environ.get("MANGEKYO_RUN_ID") and "run_id" not in document:
                    document["run_id"] = os.environ["MANGEKYO_RUN_ID"]
                print_json(ingest_run(store, document))
            elif args.command == "log":
                from .checks import outcome_from_events
                runs = store.runs()
                for run in runs:
                    run["outcome"] = outcome_from_events(store.events(run["id"]))
                print_json({"runs": runs, "branches": store.branches()})
            elif args.command == "show":
                print_json(show_item(store, args.id))
            elif args.command == "check":
                from .checks import check_run
                case = json.loads(args.case.read_text(encoding="utf-8"))
                if not isinstance(case, dict):
                    raise ValueError("Check case must be a JSON object")
                result = check_run(store, args.run, case)
                print_json(result)
                return 0 if result["passed"] else 2
            elif args.command == "mark":
                from .diagnosis import mark_divergence
                print_json(mark_divergence(store, args.run, args.event, args.reason))
            elif args.command == "diff":
                try:
                    store.one("branches", args.b)
                except KeyError:
                    a, b = store.context(args.a), store.context(args.b)
                    print_json({"a": args.a, "b": args.b, "changed": {
                        k: {"before": a.get(k), "after": b.get(k)} for k in sorted(a.keys() | b.keys())
                        if a.get(k) != b.get(k)}})
                else:
                    from .diffs import diff_branch
                    print_json(diff_branch(store, args.a, args.b))
            elif args.command == "branch":
                snapshot_id = args.at or args.source
                if args.at and store.one("snapshots", snapshot_id)["run_id"] != args.source:
                    raise ValueError("Selected snapshot does not belong to that run")
                correction = ({"replacement": args.replacement} if not args.correction_file
                              else json.loads(args.correction_file.read_text(encoding="utf-8")))
                if not isinstance(correction, dict) or not correction:
                    raise ValueError("Correction must be a nonempty JSON object")
                store.branch(snapshot_id, args.name, correction)
                print(f"Created branch {args.name} from {snapshot_id}")
                adapter = store.one("snapshots", snapshot_id)["adapter"]
                if adapter in {"mangekyo.simulation", "langgraph"}:
                    print(f"Next: mangekyo resume {args.name} (compatibility checked before execution)")
                else:
                    print("This branch is inspectable; live resume requires a compatible runtime adapter.")
            elif args.command == "commit":
                from .commits import commit_branch
                print_json(commit_branch(store, args.branch))
            elif args.command == "push":
                from .push import push_commit
                print_json(push_commit(store, args.commit, args.project))
            elif args.command == "replay":
                try:
                    run_id = store.one("snapshots", args.id)["run_id"]
                except KeyError:
                    run_id = args.id
                    store.one("runs", run_id)
                print_json({"mode": "recorded replay; no execution", "events": store.events(run_id)})
            elif args.command == "resume":
                branch = store.one("branches", args.branch)
                snapshot = store.one("snapshots", branch["source_snapshot"])
                if snapshot["adapter"] == "langgraph":
                    from .langgraph_api import LangGraphApi
                    print_json(LangGraphApi(store.path)._resume(store, args.branch))
                elif snapshot["adapter"] == "mangekyo.simulation":
                    print_json(resume(store, args.branch))
                else:
                    raise ValueError("This checkpoint is inspectable but has no live resume adapter; no action executed")
            elif args.command == "benchmark":
                run = store.one("runs", args.run)
                if run["adapter"] == "langgraph":
                    if args.openai_model:
                        raise ValueError("Provider cache probes use the reference simulation benchmark")
                    from .langgraph_api import saved_benchmarks
                    report = {"source_run": run["parent_run"] or args.run,
                              "saved_branch_benchmarks": saved_benchmarks(store, args.run),
                              "note": "Saved LangGraph comparisons; no graph or provider calls were made."}
                else:
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
            elif args.command == "bundle":
                from .bundle import export_bundle, import_bundle
                if args.bundle_action == "export":
                    package = export_bundle(store, args.run)
                    with args.file.open("x", encoding="utf-8") as stream:
                        json.dump(package, stream, ensure_ascii=False, separators=(",", ":"))
                    print_json({"file": str(args.file.resolve()), "root_run": package["root_run"],
                                "runs": len(package["records"]["runs"]), "sha256": package["sha256"]})
                else:
                    package = json.loads(args.file.read_text(encoding="utf-8"))
                    print_json(import_bundle(store, package))
            elif args.command == "dashboard":
                from .dashboard import serve
                serve(store.path, port=args.port, open_browser=not args.no_open)
            elif args.command == "evidence":
                from .evidence import add_file, capture_url
                if args.action == "add":
                    if args.selector:
                        raise ValueError("--selector is only valid for browser capture")
                    if args.mask_selector:
                        raise ValueError("--mask-selector is only valid for browser capture")
                    parsed = args.parsed_text_file.read_text(encoding="utf-8") if args.parsed_text_file else None
                    ident = add_file(store, args.run, Path(args.source), event_id=args.event, parsed_text=parsed)
                else:
                    if args.parsed_text_file:
                        raise ValueError("Browser capture extracts the page text automatically")
                    ident = capture_url(store, args.run, args.source, event_id=args.event,
                                        selector=args.selector,
                                        mask_selectors=tuple(args.mask_selector))
                print_json({"artifact_id": ident, "run_id": args.run,
                            "dashboard": "mangekyo dashboard"})
    except (KeyError, ValueError, sqlite3.Error, OSError, RuntimeError) as exc:
        print(f"mangekyo: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
