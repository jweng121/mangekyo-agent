"""Interactive terminal history inspector."""

from __future__ import annotations

import json
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea

from .demo import benchmark, resume
from .store import Store
from .banner_art import BANNER_HEIGHT, BANNER_WIDTH, COMPACT_HEIGHT, COMPACT_WIDTH, fragments as logo_fragments


def run_tui(store: Store) -> None:
    runs: list[dict[str, Any]] = []
    selected_run = 0
    selected_event = 0
    override_detail: str | None = None
    message = "Select a run, then inspect events or enter a command."
    command = TextArea(height=1, prompt="> ", multiline=False)

    def refresh() -> None:
        nonlocal runs, selected_run, selected_event
        runs = store.runs()
        selected_run = min(selected_run, max(0, len(runs) - 1))
        selected_event = 0

    def current() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        run = runs[selected_run] if runs else None
        return run, store.events(run["id"]) if run else []

    def run_text() -> str:
        if not runs:
            return "No runs yet. Exit and run: mangekyo demo"
        return "\n".join(f"{'❯' if i == selected_run else ' '} {r['id']}\n   {r['status']} · {r['label']}"
                         for i, r in enumerate(runs))

    def event_text() -> str:
        _, events = current()
        return "\n".join(f"{'❯' if i == selected_event else ' '} {e['seq']:02} {e['kind']}\n   {e['id']}"
                         for i, e in enumerate(events)) or "No events"

    def detail_text() -> str:
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
        return json.dumps(detail, indent=2, ensure_ascii=False, default=str)

    def do_command(raw: str) -> None:
        nonlocal selected_run, selected_event, message, override_detail
        parts = raw.strip().split()
        if not parts:
            return
        action = parts[0].lower()
        try:
            run, events = current()
            if action in {"help", "?"}:
                message = "run N | event N | branches | branch NAME [safe] | resume NAME | diff A B | benchmark | refresh | quit"
            elif action == "run":
                selected_run = max(0, min(int(parts[1]) - 1, len(runs) - 1))
                selected_event = 0
                override_detail = None
                message = f"Selected run {selected_run + 1}"
            elif action == "event":
                selected_event = max(0, min(int(parts[1]) - 1, len(events) - 1))
                override_detail = None
                message = f"Selected event {selected_event + 1}"
            elif action == "branches":
                override_detail = json.dumps(store.branches(), indent=2, ensure_ascii=False)
                message = f"Showing {len(store.branches())} branches"
            elif action == "branch":
                if not events or not events[selected_event]["snapshot_id"]:
                    raise ValueError("Select a checkpoint event first")
                name = parts[1]
                store.branch(events[selected_event]["snapshot_id"], name,
                             {"replacement": parts[2] if len(parts) > 2 else "safe"})
                override_detail = json.dumps(store.one("branches", name), indent=2)
                message = f"Created branch {name}; type resume {name}"
            elif action == "resume":
                result = resume(store, parts[1])
                refresh()
                override_detail = json.dumps(result, indent=2)
                message = f"Resumed as {result['run_id']}; skipped {result['skipped_steps']} steps"
            elif action == "diff":
                a, b = store.context(parts[1]), store.context(parts[2])
                changes = {k: {"before": a.get(k), "after": b.get(k)} for k in a.keys() | b.keys()
                           if a.get(k) != b.get(k)}
                override_detail = json.dumps(changes, indent=2, ensure_ascii=False)
                message = "Changed context: " + (", ".join(sorted(changes)) or "none")
            elif action == "benchmark":
                if not run:
                    raise ValueError("No run selected")
                report = benchmark(store, run["parent_run"] or run["id"])
                override_detail = json.dumps(report, indent=2, ensure_ascii=False)
                message = "Benchmark report (no provider call)"
            elif action == "refresh":
                refresh()
                override_detail = None
                message = "Refreshed"
            elif action in {"quit", "exit", "q"}:
                app.exit()
            else:
                message = "Unknown command. Type help."
        except (IndexError, ValueError, KeyError) as exc:
            message = f"Error: {exc}"
        app.invalidate()

    kb = KeyBindings()

    @kb.add("c-c")
    @kb.add("c-q")
    def _quit(_event: Any) -> None:
        app.exit()

    @kb.add("enter")
    def _submit(_event: Any) -> None:
        raw = command.text
        command.text = ""
        do_command(raw)

    @kb.add("up")
    def _up(_event: Any) -> None:
        nonlocal selected_event, override_detail
        selected_event = max(0, selected_event - 1)
        override_detail = None
        app.invalidate()

    @kb.add("down")
    def _down(_event: Any) -> None:
        nonlocal selected_event, override_detail
        _, events = current()
        selected_event = min(max(0, len(events) - 1), selected_event + 1)
        override_detail = None
        app.invalidate()

    refresh()
    large_banner = Condition(lambda: app.output.get_size().columns >= BANNER_WIDTH
                             and app.output.get_size().rows >= 21)
    compact_banner = Condition(lambda: COMPACT_WIDTH <= app.output.get_size().columns < BANNER_WIDTH
                               and app.output.get_size().rows >= 21)
    banner = Window(FormattedTextControl(logo_fragments), height=BANNER_HEIGHT, wrap_lines=False)
    small_banner = Window(FormattedTextControl(lambda: logo_fragments(compact=True)),
                          height=COMPACT_HEIGHT, wrap_lines=False)
    root = HSplit([
        ConditionalContainer(banner, filter=large_banner),
        ConditionalContainer(small_banner, filter=compact_banner),
        ConditionalContainer(Window(FormattedTextControl([
            ("class:banner", "MANGEKYO-AGENT"), ("class:subtitle", "  /  local execution history")
        ]), height=1), filter=~large_banner & ~compact_banner),
        Window(FormattedTextControl("↑↓ events · type 'run N' to switch runs · 'help' for commands"), height=1),
        VSplit([
            Frame(Window(FormattedTextControl(run_text), wrap_lines=True), title="Runs", width=24),
            Frame(Window(FormattedTextControl(event_text), wrap_lines=True), title="Timeline", width=27),
            Frame(Window(FormattedTextControl(detail_text), wrap_lines=True), title="Inspector"),
        ]),
        Window(FormattedTextControl(lambda: message), height=1),
        command,
    ])
    app: Application[Any] = Application(
        layout=Layout(root, focused_element=command), key_bindings=kb,
        style=Style.from_dict({"frame.border": "#8b1a1a", "frame.label": "#ff5555",
                               "banner": "#FF343B bold", "banner.shadow": "#C43A44 bold",
                               "subtitle": "#a69a9f"}),
        full_screen=True, mouse_support=True)
    app.run()
