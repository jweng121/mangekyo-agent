"""First chat launch configures a model and later launches reuse it."""

import json
import threading
import time
from unittest.mock import patch

from prompt_toolkit.application import Application
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout import Window

from mangekyo.chat import run_chat
from mangekyo.chat_service import model_config
from mangekyo.cli import main
from mangekyo.store import Store
from mangekyo.tui import run_tui


def test_chat_launch_opens_full_screen_setup(tmp_path):
    with patch("mangekyo.chat.run_tui") as tui:
        with Store(tmp_path / "history") as store:
            run_chat(store)
    tui.assert_called_once()
    assert tui.call_args.kwargs == {"start_view": "home", "chat_mode": True}
    assert model_config(tmp_path / "history") is None


def test_setup_runs_inside_tui(tmp_path):
    ready = threading.Event()
    state = {}
    with create_pipe_input() as pipe:
        def make_app(**kwargs):
            app = Application(**kwargs, input=pipe, output=DummyOutput())
            state["app"] = app
            ready.set()
            return app

        def verified(home):
            config = model_config(home)
            config["verified"] = True
            (home / "debug-model.json").write_text(json.dumps(config), encoding="utf-8")
            return "OK"

        def worker():
            with patch("mangekyo.tui.Application", side_effect=make_app), \
                 patch("mangekyo.tui.verify_model", side_effect=verified):
                with Store(tmp_path / "history") as store:
                    run_tui(store, start_view="home", chat_mode=True)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert ready.wait(10)
        pipe.send_text("4\r")
        pipe.send_text("fixture\r")
        pipe.send_text("http://127.0.0.1:1234/v1\r")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            config = model_config(tmp_path / "history")
            if config and config.get("verified"):
                break
            time.sleep(.05)
        assert config["provider"] == "local"
        assert config["verified"]
        pipe.send_text("/quit\r")
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_slash_menu_opens_and_scrolls(tmp_path):
    ready = threading.Event()
    state = {}
    with create_pipe_input() as pipe:
        def make_app(**kwargs):
            app = Application(**kwargs, input=pipe, output=DummyOutput())
            state["app"] = app
            ready.set()
            return app

        def worker():
            with patch("mangekyo.tui.Application", side_effect=make_app):
                with Store(tmp_path / "history") as store:
                    run_tui(store, start_view="home")

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert ready.wait(10)
        pipe.send_text("/")
        time.sleep(.2)
        menu = next(child for child in state["app"].layout.container.children
                    if isinstance(child, ConditionalContainer) and
                    isinstance(child.content, Window) and
                    callable(getattr(child.content.content, "text", None)) and
                    getattr(child.content.content.text, "__name__", "") == "menu_text")
        assert menu.filter()
        assert "1/" in menu.content.content.text()[0][1]
        pipe.send_text("\x1b[B" * 10)
        time.sleep(.2)
        assert "11/" in menu.content.content.text()[0][1]
        assert "/capture" in "".join(fragment for _, fragment in menu.content.content.text())
        pipe.send_text("\x03")
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_chat_up_arrow_recalls_previous_prompt(tmp_path):
    ready = threading.Event()
    state = {}
    with create_pipe_input() as pipe:
        def make_app(**kwargs):
            app = Application(**kwargs, input=pipe, output=DummyOutput())
            state["app"] = app
            ready.set()
            return app

        def fake_answer(_home, prompt, **_kwargs):
            state["question"] = prompt
            return {"session": "fixture", "run_id": None, "reply": "Answer",
                    "messages": [{"role": "user", "content": prompt},
                                 {"role": "assistant", "content": "Answer"}]}

        def worker():
            with patch("mangekyo.tui.Application", side_effect=make_app), \
                 patch("mangekyo.tui.ask_model", side_effect=fake_answer), \
                 patch("mangekyo.tui.model_config", return_value={"provider": "local", "model": "fixture", "verified": True}):
                with Store(tmp_path / "history") as store:
                    run_tui(store, start_view="home", chat_mode=True)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert ready.wait(10)
        pipe.send_text("What went wrong?\r")
        deadline = time.monotonic() + 5
        while "question" not in state and time.monotonic() < deadline:
            time.sleep(.05)
        assert state["question"] == "What went wrong?"
        pipe.send_text("\x1b[A")
        time.sleep(.2)
        assert state["app"].layout.current_buffer.text == "What went wrong?"
        pipe.send_text("\x1b[B")
        time.sleep(.1)
        pipe.send_text("Suggest an eval\r")
        time.sleep(.2)
        pipe.send_text("\x1b[A\x1b[A")
        time.sleep(.2)
        assert state["app"].layout.current_buffer.text == "What went wrong?"
        pipe.send_text("\x1b[B\x1b[B")
        time.sleep(.2)
        assert state["app"].layout.current_buffer.text == ""
        pipe.send_text("/quit\r")
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_tui_cli_opens_without_model_or_setup(tmp_path):
    home = tmp_path / "fresh-history"
    with patch("mangekyo.tui.run_tui") as tui:
        assert main(["--home", str(home), "--tui"]) == 0
    tui.assert_called_once()
    assert not (home / "debug-model.json").exists()
