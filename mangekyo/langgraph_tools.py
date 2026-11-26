"""Capture standard LangChain tool callbacks into a Mangekyo run."""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .instrument import _json_value
from .store import Store


class MangekyoToolHandler(BaseCallbackHandler):
    def __init__(self, store_path, run_id: str):
        self.store_path = store_path
        self.run_id = run_id
        self.pending: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()

    def _write(self, kind: str, payload: dict[str, Any]) -> None:
        # LangGraph may execute tool callbacks on worker threads.
        with self.write_lock, Store(self.store_path) as store:
            store.event(self.run_id, kind, payload)

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, *,
                      run_id, parent_run_id=None, inputs=None, **kwargs: Any) -> None:
        item = {"name": serialized.get("name") or serialized.get("id") or "tool",
                "input": _json_value(inputs if inputs is not None else input_str),
                "framework_run_id": str(run_id),
                "parent_framework_run_id": str(parent_run_id) if parent_run_id else None}
        with self.lock:
            self.pending[str(run_id)] = item
        self._write("tool_start", item)

    def on_tool_end(self, output: Any, *, run_id, **kwargs: Any) -> None:
        with self.lock:
            item = self.pending.pop(str(run_id), {"framework_run_id": str(run_id)})
        self._write("tool", {**item, "result": _json_value(output)})

    def on_tool_error(self, error: BaseException, *, run_id, **kwargs: Any) -> None:
        with self.lock:
            item = self.pending.pop(str(run_id), {"framework_run_id": str(run_id)})
        self._write("tool", {**item, "error": {"type": type(error).__name__,
                                               "message": str(error)}})
