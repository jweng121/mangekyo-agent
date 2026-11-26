"""Interactive terminal history inspector."""

from __future__ import annotations

import json
import os
import shlex
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from importlib.resources import files
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.processors import AfterInput
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea

from .demo import benchmark, resume
from .checks import check_run
from .capture import capture_report
from .commits import commit_branch
from .diagnosis import mark_divergence
from .diffs import diff_branch
from .langgraph_api import ApiError, LangGraphApi
from .project import CONFIG
from .tui_project import (active_project, launch_config, register_project,
                          resolve_launch, save_launch_config)
from .store import Store
from .chat_service import (KEY_ENV, PROVIDERS, ask as ask_model, model_config,
                           sessions as chat_sessions, save_model_config, verify_model,
                           openrouter_auth_url, exchange_openrouter_code)
from .banner_art import BANNER_HEIGHT, BANNER_WIDTH, STACKED_HEIGHT, STACKED_WIDTH, fragments as logo_fragments
from .banner_image import SINGLE_HEIGHT, STACKED_HEIGHT as IMAGE_STACKED_HEIGHT, draw as draw_logo_image, supported as image_supported, unicode_requested
from .crow_image import draw as draw_crow_image


CROW_ART = ANSI((files("mangekyo") / "assets" / "crow-tui-small.ans").read_text(encoding="utf-8"))
HOME_CROW = (
    "          .--.          \n"
    "       .-'    '-.       \n"
    "     .'  .-..-.  '.     \n"
    "    /   ( o  o )   \\    \n"
    "   /     \\  > /     \\   \n"
    "  /  .----`--'----.  \\  \n"
    "  \\_/  /  /\\  \\  \\_/  \n"
    "      /__/  \\__\\       \n"
    "        / /  \\ \\        \n"
    "       /_/    \\_\\       "
)
try:
    VERSION = version("mangekyo-agent")
except PackageNotFoundError:
    VERSION = "0.2.0b1"


def _langgraph_benchmark_status(reports: list[dict[str, Any]]) -> str:
    if not reports:
        return "No saved branch comparison yet"
    report = reports[0]
    delta = report["net_model_saving_usd"]
    if report["saving_demonstrated"]:
        verdict = f"Model saving ${delta:.7f}"
    else:
        verdict = f"No verified saving (model delta {delta:+.7f} USD)"
    skipped = len(report["skipped_steps"])
    elapsed = report["wall_time_saved_ms"]
    pace = f"{abs(elapsed):.0f} ms {'faster' if elapsed > 0 else 'slower' if elapsed < 0 else 'equal'}"
    cache = report["provider_cache_saving_usd"]
    cache_text = f"-${abs(cache):.7f}" if cache < 0 else f"${cache:.7f}"
    return (f"{verdict}; {skipped} step{'s' if skipped != 1 else ''} skipped; "
            f"{pace}; provider cache saving {cache_text}")


def _draw_images(rendered_app: Application[Any], image_single: Condition,
                 image_stacked: Condition, show_intro: Condition) -> None:
    # prompt_toolkit renders once more while leaving the alternate screen.
    # Images sent during that redraw remain visible over the shell.
    if rendered_app.is_done:
        return
    if image_single() or image_stacked():
        draw_logo_image(rendered_app.output, rendered_app.output.get_size().columns,
                        stacked=image_stacked(), top=6)
    if show_intro() and image_supported():
        draw_crow_image(rendered_app.output, SINGLE_HEIGHT + 7)


def run_tui(store: Store, *, start_view: str = "inspector", chat_mode: bool = False) -> None:
    runs: list[dict[str, Any]] = []
    selected_run = 0
    selected_event = 0
    override_detail: str | None = None
    launch_process: subprocess.Popen | None = None
    selected_project = active_project(store.path)
    add_in_progress = False
    config = model_config(store.path) if chat_mode else None
    view = "setup" if chat_mode and (start_view == "setup" or not config or not config.get("verified")) else start_view
    raw_detail = False
    message = ""
    command_history: list[str] = []
    history_index: int | None = None
    history_draft = ""
    previous_chats = chat_sessions(store.path) if chat_mode else []
    chat_session_id = previous_chats[-1]["id"] if previous_chats else None
    chat_run_id = previous_chats[-1].get("run_id") if previous_chats else None
    chat_log = list(previous_chats[-1]["messages"]) if previous_chats else []
    chat_busy = False
    setup_step = "provider"
    setup_provider = ""
    setup_model = ""
    setup_url = ""
    setup_auth = ""
    setup_verifier = ""
    setup_link = ""
    setup_choice = 0
    setup_busy = False
    setup_error = ""
    menu_index = 0

    # Keep this list in the same order in both Chat and the model-free inspector.
    slash_commands = [
        ("/help", "Show commands"), ("/home", "Opening screen"),
        ("/crow", "Show the temporary crow"),
        ("/runs", "Inspect recorded runs"), ("/run N", "Select a run"),
        ("/event N", "Select an event"), ("/raw", "Toggle raw event data"),
        ("/add PATH", "Connect a Python agent"), ("/project", "Show connected agent"),
        ("/launch", "Start the agent"), ("/capture", "Capture a run"),
        ("/evidence", "Inspect evidence"), ("/check FILE", "Run an evaluation"),
        ("/mark REASON", "Mark divergence"), ("/branches", "List branches"),
        ("/branch NAME", "Branch from checkpoint"), ("/resume NAME", "Resume branch"),
        ("/commit NAME", "Commit correction"), ("/diff A B", "Compare snapshots"),
        ("/benchmark", "Compare recovery runs"), ("/refresh", "Reload history"),
        ("/quit", "Exit Mangekyo"),
    ]
    if chat_mode:
        slash_commands[1:1] = [("/model", "Connect or change model"),
                               ("/use N", "Chat about a run")]
    command = TextArea(
        height=3, prompt="❯ ", multiline=False, password=Condition(lambda: view == "setup" and setup_step == "key"),
        style="class:command.field",
        input_processors=[AfterInput(lambda: (" Select with ↑↓ or enter a value" if view == "setup" else
                                      " Ask about a run or type /help" if chat_mode else
                                      " Type /add PATH or /help") if not command.text else "",
                                     style="class:command.placeholder")],
    )

    def reset_menu_selection(_buffer: Any) -> None:
        nonlocal menu_index
        menu_index = 0

    command.buffer.on_text_changed += reset_menu_selection

    def menu_options() -> list[tuple[str, str]]:
        typed = command.text.strip().lower()
        if view == "setup" or not typed.startswith("/") or " " in typed:
            return []
        return [item for item in slash_commands if item[0].split()[0].startswith(typed)]

    def setup_choices() -> list[str]:
        if setup_step == "provider":
            return ["OpenAI API", "OpenRouter API", "OpenRouter sign in", "Local model", "Custom endpoint"]
        if setup_step == "auth":
            choices = ["Paste API key", "Use environment variable"]
            return choices + (["No authentication"] if setup_provider == "custom" else [])
        return []

    def begin_verification(*, api_key: str | None = None, key_env: str | None = None,
                           oauth_code: str | None = None, no_auth: bool = False) -> None:
        nonlocal setup_step, setup_busy, setup_error
        setup_step = "verify"
        setup_busy = True
        setup_error = ""

        def worker() -> None:
            try:
                if oauth_code is not None:
                    exchange_openrouter_code(store.path, code=oauth_code,
                                             verifier=setup_verifier, model=setup_model)
                else:
                    save_model_config(store.path, provider=setup_provider, model=setup_model,
                                      base_url=setup_url or None, api_key=api_key,
                                      key_env=key_env, no_auth=no_auth)
                verify_model(store.path)
                error = ""
            except Exception as exc:
                error = str(exc)

            def finish() -> None:
                nonlocal view, setup_step, setup_busy, setup_error, message
                if app.is_done:
                    return
                setup_busy = False
                if error:
                    setup_error = error
                    setup_step = "provider"
                    message = "Connection failed. Choose a provider to retry."
                else:
                    view = "home"
                    message = f"Connected {setup_provider}: {setup_model}"
                app.invalidate()

            if app.loop is not None and not app.loop.is_closed():
                app.loop.call_soon_threadsafe(finish)

        threading.Thread(target=worker, daemon=True).start()

    def submit_setup(raw: str) -> None:
        nonlocal setup_step, setup_provider, setup_model, setup_url, setup_auth
        nonlocal setup_verifier, setup_link, setup_choice, setup_error, message
        value = raw.strip()
        if value in {"/quit", "/exit"}:
            app.exit()
            return
        if setup_busy:
            return
        try:
            if setup_step in {"provider", "auth"}:
                choices = setup_choices()
                if value:
                    choice = int(value) - 1
                    if choice not in range(len(choices)):
                        raise ValueError("Choose a number shown above")
                else:
                    choice = setup_choice
                if setup_step == "provider":
                    setup_provider = ["openai", "openrouter", "openrouter", "local", "custom"][choice]
                    setup_auth = "oauth" if choice == 2 else ""
                    setup_step = "model"
                else:
                    setup_auth = ["key", "env", "none"][choice]
                    if setup_auth == "key":
                        setup_step = "key"
                    elif setup_auth == "env":
                        setup_step = "env"
                    else:
                        begin_verification(no_auth=True)
                setup_choice = 0
            elif setup_step == "model":
                if not value:
                    raise ValueError("Enter the model name used by your provider")
                setup_model = value
                if setup_provider in {"local", "custom"}:
                    setup_step = "endpoint"
                elif setup_auth == "oauth":
                    setup_verifier = secrets.token_urlsafe(32)
                    setup_link = openrouter_auth_url(setup_verifier)
                    webbrowser.open(setup_link)
                    setup_step = "oauth_code"
                else:
                    setup_step = "auth"
            elif setup_step == "endpoint":
                setup_url = value or PROVIDERS[setup_provider]
                setup_step = "auth" if setup_provider == "custom" else "verify"
                if setup_step == "verify":
                    begin_verification(no_auth=True)
            elif setup_step == "key":
                if not value:
                    raise ValueError("Enter an API key")
                begin_verification(api_key=value)
            elif setup_step == "env":
                begin_verification(key_env=value or KEY_ENV.get(setup_provider) or "MODEL_API_KEY")
            elif setup_step == "oauth_code":
                if not value:
                    raise ValueError("Paste the authorization code")
                begin_verification(oauth_code=value)
            setup_error = ""
        except (ValueError, RuntimeError, OSError) as exc:
            setup_error = str(exc)
        app.invalidate()

    def refresh(*, preserve_selection: bool = False) -> None:
        nonlocal runs, selected_run, selected_event
        previous_run = runs[selected_run]["id"] if preserve_selection and runs else None
        previous_events = store.events(previous_run) if previous_run else []
        previous_event = (previous_events[selected_event]["id"]
                          if selected_event < len(previous_events) else None)
        runs = store.runs()
        if previous_run:
            selected_run = next((i for i, item in enumerate(runs)
                                 if item["id"] == previous_run), 0)
            events = store.events(runs[selected_run]["id"]) if runs else []
            selected_event = next((i for i, item in enumerate(events)
                                   if item["id"] == previous_event), 0)
        else:
            selected_run = min(selected_run, max(0, len(runs) - 1))
            selected_event = 0

    def current() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        run = runs[selected_run] if runs else None
        return run, store.events(run["id"]) if run else []

    def run_text() -> str:
        if not runs:
            return "No runs yet.\n\n/add PATH\n/launch"
        def shorten(value: str, limit: int = 26) -> str:
            value = " ".join(str(value).split())
            return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"
        return "\n\n".join(f"{'❯' if i == selected_run else ' '} {i + 1}. {shorten(r['label'])}\n   {r['status']}"
                         for i, r in enumerate(runs))

    def event_text() -> str:
        _, events = current()
        def label(event: dict[str, Any]) -> str:
            payload = event.get("payload") or {}
            if not isinstance(payload, dict):
                return event["kind"]
            value = (payload.get("name") or payload.get("tool") or
                     payload.get("step") or payload.get("label"))
            return f"{event['kind']}: {value}" if value else event["kind"]
        return "\n".join(f"{'❯' if i == selected_event else ' '} {e['seq']:02} {label(e)}"
                         for i, e in enumerate(events)) or "No events yet"

    def detail_text() -> Any:
        if override_detail is not None:
            return override_detail
        run, events = current()
        if not run:
            return ""
        if events:
            event = events[selected_event]
            detail = {"event": event["kind"], "payload": event["payload"]}
            if event["snapshot_id"]:
                detail["snapshot"] = event["snapshot_id"]
                detail["context"] = store.context(event["snapshot_id"])
        else:
            detail = run
        if not raw_detail:
            lines = [f"Run: {run['label']}", f"Status: {run['status']}", ""]
            if events:
                lines.append(f"Event {event['seq']}: {event['kind']}")
                payload = event.get("payload") or {}
                if isinstance(payload, dict):
                    for key, value in payload.items():
                        formatted = json.dumps(value, ensure_ascii=False, indent=2, default=str)
                        lines.append(f"{key.replace('_', ' ').title()}: {formatted}")
                else:
                    lines.append(str(payload))
                if event["snapshot_id"]:
                    lines.extend(["", "Checkpoint state:"])
                    for key, value in store.context(event["snapshot_id"]).items():
                        formatted = json.dumps(value, ensure_ascii=False, indent=2, default=str)
                        lines.append(f"{key.replace('_', ' ').title()}: {formatted}")
            lines.extend(["", "Use /raw for full event data."])
            return "\n".join(lines)
        return json.dumps(detail, indent=2, ensure_ascii=False, default=str)

    def info_text() -> list[tuple[str, str]]:
        return [
            ("class:home.section", "Available commands\n"),
            ("class:home.command", "/runs          "), ("", "Open run inspector\n"),
            ("class:home.command", "/run N         "), ("", "Select a run\n"),
            ("class:home.command", "/add PATH      "), ("", "Connect an agent project\n"),
            ("class:home.command", "/project       "), ("", "Show active project\n"),
            ("class:home.command", "/launch        "), ("", "Start the configured agent\n"),
            ("class:home.command", "/event N       "), ("", "Inspect an event\n"),
            ("class:home.command", "/check FILE    "), ("", "Check selected run or event\n"),
            ("class:home.command", "/mark REASON   "), ("", "Mark selected wrong event\n"),
            ("class:home.command", "/evidence      "), ("", "Show captured document text\n"),
            ("class:home.command", "/capture       "), ("", "Report what the run recorded\n"),
            ("class:home.command", "/branches      "), ("", "List branches\n"),
            ("class:home.command", "/branch NAME   "), ("", "Branch from selected checkpoint\n"),
            ("class:home.command", "/resume NAME   "), ("", "Resume a branch\n"),
            ("class:home.command", "/commit NAME   "), ("", "Commit a passing correction\n"),
            ("class:home.command", "/diff A B      "), ("", "Compare snapshots\n"),
            ("class:home.command", "/benchmark     "), ("", "Compare recovery runs\n"),
            ("class:home.command", "/raw           "), ("", "Toggle full event data\n"),
            ("class:home.command", "/home          "), ("", "Return to opening screen\n"),
            ("class:home.command", "/refresh       "), ("", "Reload local history\n"),
            ("class:home.command", "/help          "), ("", "Show all commands\n\n"),
            ("class:home.section", "Navigation\n"),
            ("class:home.command", "Ctrl-P/N       "), ("", "Move through events\n"),
            ("class:home.command", "↑ / ↓          "), ("", "Recall commands\n"),
            ("class:home.command", "/quit          "), ("", "Exit the TUI"),
        ]

    def do_command(raw: str) -> None:
        nonlocal selected_run, selected_event, message, override_detail, launch_process
        nonlocal selected_project, add_in_progress, view, raw_detail
        nonlocal chat_session_id, chat_run_id, chat_busy, chat_log
        raw = raw.strip()
        slash_command = raw.startswith("/")
        if slash_command:
            raw = raw[1:]
        parts = raw.split()
        if not parts:
            return
        action = parts[0].lower()
        try:
            run, events = current()
            if action in {"help", "?"}:
                view = "home" if chat_mode else "inspector"
                message = ("Ask about a selected run · /use N · /runs · /add PATH · /launch · /model · /help · /quit"
                           if chat_mode else
                           "/add PATH | /project | /launch [--capture-output] [COMMAND] | /runs | /run N | /event N | /capture | /evidence | /check FILE [selected] | /mark REASON | /branches | /branch NAME key=value | /resume NAME | /commit NAME | /diff A B | /benchmark | /raw | /home | /quit")
            elif action == "use" and chat_mode:
                refresh(preserve_selection=True)
                if not runs:
                    raise ValueError("No runs yet; use /add PATH and /launch")
                index = max(0, min(int(parts[1]) - 1, len(runs) - 1))
                new_run_id = runs[index]["id"]
                if new_run_id != chat_run_id:
                    chat_session_id = None
                    chat_log = []
                chat_run_id = new_run_id
                view = "home"
                message = f"Chat now uses run {index + 1}: {runs[index]['label']}"
            elif action == "model" and chat_mode:
                view = "setup"
                message = "Connect a debugging model"
            elif action in {"home", "start"}:
                view = "home"
                message = ""
            elif action in {"runs", "inspect"}:
                view = "inspector"
                refresh(preserve_selection=True)
                message = "Select a run and an event; use /raw for full data."
            elif action == "raw":
                view = "inspector"
                raw_detail = not raw_detail
                message = "Showing raw event data" if raw_detail else "Showing readable event details"
            elif action == "crow":
                view = "home"
                message = "Temporary crow art is centered on the opening screen."
            elif action == "run":
                view = "inspector"
                selected_run = max(0, min(int(parts[1]) - 1, len(runs) - 1))
                selected_event = 0
                override_detail = None
                message = f"Selected run {selected_run + 1}"
            elif action == "add":
                if add_in_progress:
                    raise ValueError("Project connection is already in progress")
                add_text = raw.strip().partition(" ")[2].strip()
                if not add_text:
                    raise ValueError("Use add PATH to select a Python agent project")
                arguments = shlex.split(add_text, posix=os.name != "nt")
                if os.name == "nt":
                    arguments = [arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] == '"'
                                 else arg for arg in arguments]
                if not arguments:
                    raise ValueError("Use add PATH to select a Python agent project")
                project_path = Path(arguments[0]).expanduser().resolve()
                graph_specs = []
                remaining = arguments[1:]
                while remaining:
                    if len(remaining) < 2 or remaining[0] != "--graph":
                        raise ValueError("Use add PATH [--graph NAME=module:factory]")
                    graph_specs.append(remaining[1])
                    remaining = remaining[2:]
                add_in_progress = True
                message = f"Connecting project {project_path}…"

                def connect() -> None:
                    try:
                        result = register_project(project_path, store.path, graph_specs)
                        error = None
                    except Exception as exc:
                        result, error = None, str(exc)

                    def update() -> None:
                        nonlocal add_in_progress, selected_project, message, override_detail
                        if app.is_done:
                            return
                        add_in_progress = False
                        if result is not None:
                            selected_project = Path(result["project"])
                            override_detail = json.dumps(result, indent=2, ensure_ascii=False)
                            if result["sdk"].startswith("connection failed"):
                                message = f"Added {selected_project.name}; SDK connection failed (see inspector)"
                            else:
                                message = (f"Added {selected_project.name}; type /launch"
                                           if result["launch"] else
                                           f"Added {selected_project.name}; type /launch COMMAND once")
                        else:
                            message = f"Project connection failed: {error}"
                        app.invalidate()

                    if app.loop is not None and not app.loop.is_closed():
                        app.loop.call_soon_threadsafe(update)

                threading.Thread(target=connect, daemon=True).start()
            elif action == "project":
                view = "inspector"
                if not selected_project:
                    raise ValueError("No active project; type /add PATH")
                override_detail = json.dumps({"project": str(selected_project),
                                              "launch": launch_config(selected_project)},
                                             indent=2, ensure_ascii=False)
                message = f"Active project: {selected_project}"
            elif action == "launch":
                view = "inspector"
                if add_in_progress:
                    raise ValueError("Wait for project connection to finish")
                if launch_process is not None and launch_process.poll() is None:
                    raise ValueError("An agent launched from this TUI is still running")
                project_path = selected_project or Path.cwd()
                command_text = raw.strip().partition(" ")[2].strip()
                capture_output = (command_text == "--capture-output" or
                                  command_text.startswith("--capture-output "))
                if capture_output:
                    command_text = command_text.removeprefix("--capture-output").strip()
                if command_text:
                    command_args = shlex.split(command_text, posix=os.name != "nt")
                    if os.name == "nt":
                        command_args = [arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] == '"'
                                        else arg for arg in command_args]
                    if (project_path / CONFIG).is_file():
                        save_launch_config(project_path, command_args)
                else:
                    command_args = launch_config(project_path)
                    if command_args is None:
                        raise ValueError("No launch command found; type /launch COMMAND once")
                if not command_args:
                    raise ValueError("Provide a command to launch")
                command_args = resolve_launch(project_path, command_args)
                launcher = ([sys.executable] if getattr(sys, "frozen", False)
                            else [sys.executable, "-m", "mangekyo"])
                started = time.time()
                launch_process = subprocess.Popen(
                    [*launcher, "--home", str(store.path), "run",
                     *(["--capture-output"] if capture_output else []), "--",
                     *command_args], cwd=project_path, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                process = launch_process
                message = f"Started agent process {process.pid}; events will appear here"

                def monitor() -> None:
                    follow_new_run = True
                    while True:
                        code = process.poll()

                        def update(code=code) -> None:
                            nonlocal selected_run, selected_event, message, launch_process, follow_new_run
                            if app.is_done:
                                return
                            refresh(preserve_selection=True)
                            if follow_new_run:
                                new_index = next((i for i, item in enumerate(runs)
                                                  if item["created"] >= started), None)
                                if new_index is not None:
                                    selected_run = new_index
                                    selected_event = 0
                                    follow_new_run = False
                            if code is not None:
                                launch_process = None
                                message = ("Agent run finished" if code == 0
                                           else f"Agent process exited {code}; inspect its run")
                            app.invalidate()

                        if app.loop is None or app.loop.is_closed():
                            return
                        app.loop.call_soon_threadsafe(update)
                        if code is not None:
                            return
                        time.sleep(.7)

                threading.Thread(target=monitor, daemon=True).start()
            elif action == "event":
                view = "inspector"
                selected_event = max(0, min(int(parts[1]) - 1, len(events) - 1))
                override_detail = None
                message = f"Selected event {selected_event + 1}"
            elif action == "branches":
                view = "inspector"
                override_detail = json.dumps(store.branches(), indent=2, ensure_ascii=False)
                message = f"Showing {len(store.branches())} branches"
            elif action == "evidence":
                view = "inspector"
                if not run:
                    raise ValueError("No run selected")
                artifacts = store.artifacts(run["id"])
                override_detail = json.dumps([{
                    "name": artifact["name"], "mime": artifact["mime"],
                    "source_event": artifact["event_id"],
                    "parsed_text": store.get(artifact["parsed_hash"])["text"]
                    if artifact["parsed_hash"] else None,
                } for artifact in artifacts], indent=2, ensure_ascii=False)
                message = f"Showing {len(artifacts)} captured items"
            elif action == "capture":
                view = "inspector"
                if not run:
                    raise ValueError("No run selected")
                report = capture_report(store, run["id"])
                override_detail = json.dumps(report, indent=2, ensure_ascii=False)
                message = f"Capture report for run {run['id']}"
            elif action == "check":
                view = "inspector"
                if not run:
                    raise ValueError("No run selected")
                case_path = Path(parts[1])
                if not case_path.is_absolute() and selected_project:
                    case_path = selected_project / case_path
                case = json.loads(case_path.read_text(encoding="utf-8"))
                if not isinstance(case, dict):
                    raise ValueError("Check case must be a JSON object")
                if len(parts) > 2:
                    if parts[2] != "selected" or not events:
                        raise ValueError("Use check FILE selected to target the selected event")
                    case["event_id"] = events[selected_event]["id"]
                result = check_run(store, run["id"], case)
                override_detail = json.dumps(result, indent=2, ensure_ascii=False)
                message = f"Check {result['outcome']} for event {result['source_event_seq']}"
            elif action == "mark":
                view = "inspector"
                if not run or not events:
                    raise ValueError("Select an event first")
                result = mark_divergence(store, run["id"], events[selected_event]["id"],
                                         raw.strip().partition(" ")[2])
                override_detail = json.dumps(result, indent=2, ensure_ascii=False)
                message = f"Marked event {result['source_event_seq']} as {result['classification']}"
            elif action == "branch":
                view = "inspector"
                if not events or not events[selected_event]["snapshot_id"]:
                    raise ValueError("Select a checkpoint event first")
                name = parts[1]
                snapshot_id = events[selected_event]["snapshot_id"]
                adapter = store.one("snapshots", snapshot_id)["adapter"]
                if adapter == "langgraph":
                    if len(parts) < 3 or any("=" not in part for part in parts[2:]):
                        raise ValueError("LangGraph branch needs key=value correction, e.g. selected_table=bookings")
                    correction = dict(part.split("=", 1) for part in parts[2:])
                else:
                    correction = {"replacement": parts[2] if len(parts) > 2 else "safe"}
                store.branch(snapshot_id, name, correction)
                override_detail = json.dumps(store.one("branches", name), indent=2)
                message = f"Created branch {name}; type /resume {name}"
            elif action == "resume":
                view = "inspector"
                branch = store.one("branches", parts[1])
                snapshot = store.one("snapshots", branch["source_snapshot"])
                if snapshot["adapter"] == "langgraph":
                    result = LangGraphApi(store.path, project_config=(selected_project / CONFIG)
                                          if selected_project else None)._resume(store, parts[1])
                elif snapshot["adapter"] == "mangekyo.simulation":
                    result = resume(store, parts[1])
                else:
                    raise ValueError("Selected checkpoint has no live resume adapter")
                refresh()
                override_detail = json.dumps(result, indent=2)
                message = f"Resumed as {result['run_id']}; skipped {result['skipped_steps']} steps"
            elif action == "commit":
                view = "inspector"
                result = commit_branch(store, parts[1])
                override_detail = json.dumps(result, indent=2, ensure_ascii=False)
                message = f"Committed branch {parts[1]} as {result['commit_id'][:12]}"
            elif action == "diff":
                view = "inspector"
                try:
                    store.one("branches", parts[2])
                except KeyError:
                    a, b = store.context(parts[1]), store.context(parts[2])
                    changes = {k: {"before": a.get(k), "after": b.get(k)} for k in a.keys() | b.keys()
                               if a.get(k) != b.get(k)}
                    override_detail = json.dumps(changes, indent=2, ensure_ascii=False)
                    message = "Changed context: " + (", ".join(sorted(changes)) or "none")
                else:
                    result = diff_branch(store, parts[1], parts[2])
                    override_detail = json.dumps(result, indent=2, ensure_ascii=False)
                    message = "Comparing source run with corrected branch"
            elif action == "benchmark":
                view = "inspector"
                if not run:
                    raise ValueError("No run selected")
                if run["adapter"] == "langgraph":
                    from .langgraph_api import saved_benchmarks
                    report = {"source_run": run["parent_run"] or run["id"],
                              "saved_branch_benchmarks": saved_benchmarks(store, run["id"]),
                              "note": "Saved LangGraph comparisons; no graph or provider calls were made."}
                    message = _langgraph_benchmark_status(report["saved_branch_benchmarks"])
                else:
                    report = benchmark(store, run["parent_run"] or run["id"], create_baseline=True)
                    refresh()
                    recovered = report["recovered"]
                    delta = recovered[0].get("wall_time_saved_ms_vs_latest_cold") if recovered else None
                    message = (f"Cold comparison: {abs(delta):.2f} ms "
                               f"{'faster' if delta > 0 else 'slower' if delta < 0 else 'equal'}; "
                               f"skipped {recovered[0]['skipped_steps']} steps"
                               if delta is not None else "Cold baseline measured; resume a branch to compare")
                override_detail = json.dumps(report, indent=2, ensure_ascii=False)
            elif action == "refresh":
                refresh()
                override_detail = None
                message = "Refreshed run history"
            elif action in {"quit", "exit", "q"}:
                app.exit()
            elif chat_mode and not slash_command:
                if chat_busy:
                    raise ValueError("Wait for the current answer")
                chat_busy = True
                question = raw
                message = "Thinking…"
                view = "home"

                def converse() -> None:
                    try:
                        result = ask_model(store.path, question, session_id=chat_session_id,
                                           run_id=chat_run_id)
                        error = None
                    except Exception as exc:
                        result, error = None, str(exc)

                    def update() -> None:
                        nonlocal chat_busy, chat_session_id, chat_run_id, chat_log, message
                        if app.is_done:
                            return
                        chat_busy = False
                        if result:
                            chat_session_id = result["session"]
                            chat_run_id = result["run_id"]
                            chat_log = result["messages"]
                            message = "Ready"
                        else:
                            message = f"Chat error: {error}"
                        app.invalidate()

                    if app.loop is not None and not app.loop.is_closed():
                        app.loop.call_soon_threadsafe(update)

                threading.Thread(target=converse, daemon=True).start()
            else:
                message = "Unknown command. Type /help."
        except (IndexError, ValueError, KeyError, OSError, ApiError, RuntimeError) as exc:
            message = f"Error: {exc}"
        app.invalidate()

    kb = KeyBindings()

    @kb.add("c-c")
    @kb.add("c-q")
    def _quit(_event: Any) -> None:
        app.exit()

    @kb.add("enter")
    def _submit(_event: Any) -> None:
        nonlocal history_index, history_draft, menu_index
        raw = command.text
        options = menu_options()
        if options:
            selected = options[min(menu_index, len(options) - 1)][0]
            if " " in selected:
                command.text = selected.split(" ", 1)[0] + " "
                command.buffer.cursor_position = len(command.text)
                menu_index = 0
                return
            raw = selected
        command.text = ""
        if view == "setup":
            submit_setup(raw)
            return
        if raw.strip():
            command_history.append(raw)
        history_index = None
        history_draft = ""
        do_command(raw)

    @kb.add("up")
    def _up(_event: Any) -> None:
        nonlocal history_index, history_draft, menu_index, setup_choice
        if view == "setup" and setup_choices():
            setup_choice = max(0, setup_choice - 1)
            app.invalidate()
            return
        if history_index is None and menu_options():
            menu_index = max(0, menu_index - 1)
            app.invalidate()
            return
        if not command_history:
            return
        if history_index is None:
            history_draft = command.text
            history_index = len(command_history) - 1
        else:
            history_index = max(0, history_index - 1)
        command.text = command_history[history_index]
        command.buffer.cursor_position = len(command.text)
        app.invalidate()

    @kb.add("down")
    def _down(_event: Any) -> None:
        nonlocal history_index, menu_index, setup_choice
        if view == "setup" and setup_choices():
            setup_choice = min(len(setup_choices()) - 1, setup_choice + 1)
            app.invalidate()
            return
        if history_index is None and menu_options():
            menu_index = min(len(menu_options()) - 1, menu_index + 1)
            app.invalidate()
            return
        if history_index is None:
            return
        history_index += 1
        if history_index >= len(command_history):
            history_index = None
            command.text = history_draft
        else:
            command.text = command_history[history_index]
        command.buffer.cursor_position = len(command.text)
        app.invalidate()

    @kb.add("tab")
    def _choose_command(_event: Any) -> None:
        nonlocal menu_index
        options = menu_options()
        if not options:
            return
        selected = options[min(menu_index, len(options) - 1)][0]
        command.text = selected.split(" ", 1)[0] + (" " if " " in selected else "")
        command.buffer.cursor_position = len(command.text)
        menu_index = 0

    @kb.add("c-p")
    def _previous_event(_event: Any) -> None:
        nonlocal selected_event, override_detail
        selected_event = max(0, selected_event - 1)
        override_detail = None
        app.invalidate()

    @kb.add("c-n")
    def _next_event(_event: Any) -> None:
        nonlocal selected_event, override_detail
        _, events = current()
        selected_event = min(max(0, len(events) - 1), selected_event + 1)
        override_detail = None
        app.invalidate()

    refresh()
    on_home = Condition(lambda: view == "home")
    on_inspector = Condition(lambda: view == "inspector")
    on_setup = Condition(lambda: view == "setup")
    show_menu = Condition(lambda: bool(menu_options()))
    show_crow = Condition(lambda: view == "home" and (not chat_mode or not chat_log))
    show_chat = Condition(lambda: view == "home" and chat_mode and bool(chat_log))
    image_single = Condition(lambda: view == "inspector" and image_supported()
                             and app.output.get_size().columns >= 100
                             and app.output.get_size().rows >= 27)
    image_stacked = Condition(lambda: view == "inspector" and image_supported()
                              and 70 <= app.output.get_size().columns < 100
                              and app.output.get_size().rows >= 27)
    large_banner = Condition(lambda: view == "inspector" and unicode_requested()
                             and app.output.get_size().columns >= BANNER_WIDTH
                             and app.output.get_size().rows >= 25)
    stacked_banner = Condition(lambda: view == "inspector" and unicode_requested()
                               and STACKED_WIDTH <= app.output.get_size().columns < BANNER_WIDTH
                               and app.output.get_size().rows >= 29)
    show_intro = Condition(lambda: view == "inspector" and app.output.get_size().rows >= 52
                           and app.output.get_size().columns >= 115)
    banner = Window(FormattedTextControl(logo_fragments), height=BANNER_HEIGHT, wrap_lines=False)
    stacked = Window(FormattedTextControl(lambda: logo_fragments(stacked=True)),
                     height=STACKED_HEIGHT, wrap_lines=False)
    def top_border() -> list[tuple[str, str]]:
        width = app.output.get_size().columns
        title = f" Mangekyo Agent v{VERSION} "
        left = 26
        right = max(0, width - 2 - left - len(title))
        return [("class:box.border", "╭" + "─" * left),
                ("class:box.title", title),
                ("class:box.border", "─" * right + "╮")]

    def bottom_border() -> str:
        return "╰" + "─" * (app.output.get_size().columns - 2) + "╯"

    side = [("class:box.border", "\n".join("│" for _ in range(22)))]
    intro_panel = HSplit([
        Window(FormattedTextControl(top_border), height=1, wrap_lines=False),
        VSplit([
            Window(FormattedTextControl(side), width=1, wrap_lines=False),
            Window(FormattedTextControl(lambda: "" if image_supported() else CROW_ART),
                   width=24, wrap_lines=False),
            Window(FormattedTextControl(""), width=2),
            Window(FormattedTextControl(info_text), wrap_lines=False),
            Window(FormattedTextControl(side), width=1, wrap_lines=False),
        ], height=22),
        Window(FormattedTextControl(bottom_border), height=1, wrap_lines=False),
    ], height=24)
    history_panel = HSplit([
        Window(FormattedTextControl("Ctrl-P/N events · ↑↓ history · /run N · /event N · /raw"), height=1),
        VSplit([
            Frame(HSplit([
                Window(FormattedTextControl([("class:runs.heading", " Runs")]), height=1),
                Window(FormattedTextControl(run_text), wrap_lines=False),
            ]), title="", width=31),
            Frame(HSplit([
                Window(FormattedTextControl([("class:timeline.heading", " Timeline")]), height=1),
                Window(FormattedTextControl(event_text), wrap_lines=False),
            ]), title="", width=27),
            Frame(HSplit([
                Window(FormattedTextControl([("class:inspector.heading", " Inspector")]), height=1),
                Window(FormattedTextControl(detail_text), wrap_lines=True),
            ]), title=""),
        ]),
    ])
    def home_status() -> list[tuple[str, str]]:
        if view == "setup":
            return [("class:home.command", "Model setup"),
                    ("", f"  ·  {setup_provider or 'choose a provider'}"),
                    ("class:footer.message", f"  ·  {message}" if message else "")]
        project_name = selected_project.name if selected_project else "No agent connected"
        run_count = len(runs)
        process_state = "Agent running" if launch_process and launch_process.poll() is None else "Ready"
        if chat_mode:
            config = model_config(store.path)
            model_name = config["model"] if config else "No model"
            run_number = next((i + 1 for i, item in enumerate(runs)
                               if item["id"] == chat_run_id), None)
            return [("class:home.command", model_name),
                    ("", f"  ·  run {run_number if run_number is not None else 'none'}"),
                    ("class:footer.message", f"  ·  {message}" if message else "")]
        return [("class:home.command", f"{project_name}"),
                ("", f"  ·  {run_count} run{'s' if run_count != 1 else ''}  ·  {process_state}"),
                ("class:footer.message", f"  ·  {message}" if message else "")]

    home_panel = HSplit([
        Window(FormattedTextControl(""), height=Dimension(weight=1)),
        VSplit([
            Window(FormattedTextControl(""), width=Dimension(weight=1)),
            Window(FormattedTextControl([("class:home.crow", HOME_CROW)]),
                   width=27, height=10, wrap_lines=False),
            Window(FormattedTextControl(""), width=Dimension(weight=1)),
        ], height=10),
        Window(FormattedTextControl(""), height=Dimension(weight=1)),
    ])
    def conversation_text() -> str:
        return "\n\n".join(("You" if item["role"] == "user" else "Mangekyo") + "\n" +
                           item["content"] for item in chat_log[-6:])

    def setup_text() -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = [
            ("class:setup.title", "Connect a model\n"),
            ("class:setup.muted", "Mangekyo uses your model to discuss runs and suggest evaluations.\n\n"),
        ]
        if setup_step == "provider":
            lines.append(("class:setup.label", "Choose a provider\n\n"))
        elif setup_step == "model":
            lines.extend([("class:setup.label", f"{setup_provider.title()} · Model name\n\n"),
                          ("class:setup.muted", "Enter the model ID configured with your provider.\n")])
        elif setup_step == "endpoint":
            lines.extend([("class:setup.label", "OpenAI-compatible endpoint\n\n"),
                          ("class:setup.muted", f"Press Enter for {PROVIDERS[setup_provider] or 'enter an HTTPS URL'}.\n")])
        elif setup_step == "auth":
            lines.append(("class:setup.label", "How should Mangekyo authenticate?\n\n"))
        elif setup_step == "key":
            lines.extend([("class:setup.label", "API key\n\n"),
                          ("class:setup.muted", "Input is hidden. The key is saved in your OS credential store.\n")])
        elif setup_step == "env":
            lines.extend([("class:setup.label", "Environment variable\n\n"),
                          ("class:setup.muted", f"Press Enter for {KEY_ENV.get(setup_provider) or 'MODEL_API_KEY'}.\n")])
        elif setup_step == "oauth_code":
            lines.extend([("class:setup.label", "OpenRouter sign in\n\n"),
                          ("class:setup.muted", "Your browser was opened. Authorize Mangekyo, then paste the code below.\n\n"),
                          ("class:setup.link", setup_link + "\n")])
        else:
            lines.extend([("class:setup.label", "Testing your connection…\n\n"),
                          ("class:setup.muted", "Mangekyo is checking the model and credentials.\n")])
        for index, choice in enumerate(setup_choices()):
            style = "class:setup.selected" if index == setup_choice else "class:setup.choice"
            lines.append((style, f"{'❯' if index == setup_choice else ' '}  {index + 1}  {choice}\n"))
        if setup_error:
            lines.append(("class:setup.error", "\n" + setup_error + "\n"))
        lines.append(("class:setup.muted", "\n↑↓ choose · Enter continue · /quit exit"))
        return lines

    setup_panel = HSplit([
        Window(FormattedTextControl(""), height=Dimension(weight=1)),
        VSplit([Window(FormattedTextControl(""), width=4),
                Window(FormattedTextControl(setup_text), wrap_lines=True)],
               height=Dimension(min=12, preferred=16, max=18)),
        Window(FormattedTextControl(""), height=Dimension(weight=1)),
    ])

    def menu_text() -> list[tuple[str, str]]:
        options = menu_options()
        selected = min(menu_index, len(options) - 1)
        start = max(0, min(selected - 7, len(options) - 8))
        visible = options[start:start + 8]
        lines: list[tuple[str, str]] = [("class:menu.header", f" Commands  {selected + 1}/{len(options)}  ·  ↑↓ scroll  ·  Enter choose\n")]
        for offset, (name, description) in enumerate(visible):
            style = "class:menu.selected" if start + offset == selected else "class:menu.item"
            lines.append((style, f"{'❯' if start + offset == selected else ' '}  {name:<20} {description}\n"))
        return lines

    root = HSplit([
        Window(FormattedTextControl(""), height=1),
        Window(FormattedTextControl([("class:banner", f"❯  Mangekyo Agent"),
                                     ("class:subtitle", f"  v{VERSION}")]), height=1),
        ConditionalContainer(setup_panel, filter=on_setup),
        ConditionalContainer(home_panel, filter=show_crow),
        ConditionalContainer(Window(FormattedTextControl(conversation_text),
                                    wrap_lines=True), filter=show_chat),
        ConditionalContainer(Window(FormattedTextControl(""), height=3), filter=on_inspector),
        ConditionalContainer(Window(FormattedTextControl(""), height=SINGLE_HEIGHT), filter=image_single),
        ConditionalContainer(Window(FormattedTextControl(""), height=IMAGE_STACKED_HEIGHT), filter=image_stacked),
        ConditionalContainer(banner, filter=large_banner),
        ConditionalContainer(stacked, filter=stacked_banner),
        ConditionalContainer(Window(FormattedTextControl([
            ("class:banner", "MANGEKYO-AGENT"),
            ("class:subtitle", "  /  use Windows Terminal for the Classic Scarlet artwork")
        ]), height=1), filter=on_inspector & ~image_single & ~image_stacked & ~large_banner & ~stacked_banner),
        ConditionalContainer(intro_panel, filter=show_intro),
        ConditionalContainer(history_panel, filter=on_inspector),
        ConditionalContainer(Window(FormattedTextControl(menu_text), height=9,
                                    wrap_lines=False), filter=show_menu),
        command,
        Window(FormattedTextControl(home_status), height=1),
        Window(FormattedTextControl(lambda: [("class:footer.hint",
            "↑↓ select  ·  ↵ continue  ·  /quit exit" if view == "setup" else
            "↵ run command  ·  / browse commands  ·  ↑↓ history")]), height=1),
    ])
    app: Application[Any] = Application(
        layout=Layout(root, focused_element=command), key_bindings=kb,
        after_render=lambda rendered_app: _draw_images(rendered_app, image_single, image_stacked, show_intro),
        style=Style.from_dict({"frame.border": "#95343D", "frame.label": "#F28A94",
                               "banner": "#FF343B bold", "banner.shadow": "#C43A44 bold",
                               "subtitle": "#B69DA1",
                               "box.border": "#A7525E", "box.title": "#FF6876 bold",
                               "home.section": "#F5A7AD bold", "home.command": "#D96C79 bold",
                               "home.crow": "#754047",
                               "setup.title": "#FF343B bold",
                               "setup.label": "#F5A7AD bold",
                               "setup.muted": "#A69A9D",
                               "setup.choice": "#E7D7DA",
                               "setup.selected": "bg:#812E3A #FFFFFF bold",
                               "setup.error": "#FF6876 bold",
                               "setup.link": "#D96C79 underline",
                               "menu.header": "bg:#30191D #F5A7AD bold",
                               "menu.item": "bg:#191315 #E7D7DA",
                               "menu.selected": "bg:#812E3A #FFFFFF bold",
                               "command.field": "bg:#2B2B2B #F2E8E9",
                               "command.placeholder": "#777777",
                               "footer.message": "#A6A6A6",
                               "footer.hint": "#888888",
                               "runs.heading": "#FF5A6B bold",
                               "timeline.heading": "#E48390 bold",
                               "inspector.heading": "#F5ADB4 bold"}),
        full_screen=True, mouse_support=True)
    app.run()
