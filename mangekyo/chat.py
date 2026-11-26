"""Launch the terminal debugging chat and its in-app model setup."""

from __future__ import annotations

from pathlib import Path

from .store import Store
from .tui import run_tui


def configure_model(home: Path) -> bool:
    from .store import Store
    with Store(home) as store:
        run_tui(store, start_view="setup", chat_mode=True)
    return True


def run_chat(store: Store) -> None:
    run_tui(store, start_view="home", chat_mode=True)
