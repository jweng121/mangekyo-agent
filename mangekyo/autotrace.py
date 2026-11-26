"""Opt-in process instrumentation for standard LangChain model and tool calls.

The process launcher selects this adapter through ``MANGEKYO_AUTO_TRACE``.
It observes the actual call result or exception; it does not infer tool use
from an LLM's requested tool-call text.
"""

from __future__ import annotations

import functools
import os
from contextvars import ContextVar
from typing import Any, Callable

from .instrument import _json_value
from .capture import record_capture_failure
from .store import Store

_inside: ContextVar[frozenset[str]] = ContextVar("mangekyo_auto_inside", default=frozenset())


def _record(kind: str, name: str, input_value: Any, *, result: Any = None,
            error: BaseException | None = None) -> None:
    if os.environ.get("MANGEKYO_API_MANAGED") == "1":
        return
    run_id = os.environ.get("MANGEKYO_RUN_ID")
    home = os.environ.get("MANGEKYO_HOME")
    if not run_id or not home:
        return
    payload: dict[str, Any] = {"name": name, "input": _json_value(input_value),
                               "capture": "python-langchain-auto"}
    if error is None:
        payload["result"] = _json_value(result)
        if kind == "output":
            payload["output"] = payload["result"]
    else:
        payload["error"] = {"type": type(error).__name__, "message": str(error)}
    try:
        with Store(home) as store:
            store.event(run_id, kind, payload)
    except Exception as exc:
        # Tracing is observational and must not change agent behavior.
        record_capture_failure(f"{kind}:{name}", exc)


def _wrap(method: Callable, kind: str, name_of: Callable[[Any], str]) -> Callable:
    if getattr(method, "__mangekyo_auto_trace__", False):
        return method
    is_async = getattr(method, "__name__", "").startswith("a")

    if is_async:
        @functools.wraps(method)
        async def async_call(self: Any, input: Any, *args: Any, **kwargs: Any) -> Any:
            if kind in _inside.get():
                return await method(self, input, *args, **kwargs)
            token = _inside.set(_inside.get() | {kind})
            try:
                try:
                    result = await method(self, input, *args, **kwargs)
                except Exception as exc:
                    _record(kind, name_of(self), input, error=exc)
                    raise
                _record(kind, name_of(self), input, result=result)
                return result
            finally:
                _inside.reset(token)
        wrapped = async_call
    else:
        @functools.wraps(method)
        def sync_call(self: Any, input: Any, *args: Any, **kwargs: Any) -> Any:
            if kind in _inside.get():
                return method(self, input, *args, **kwargs)
            token = _inside.set(_inside.get() | {kind})
            try:
                try:
                    result = method(self, input, *args, **kwargs)
                except Exception as exc:
                    _record(kind, name_of(self), input, error=exc)
                    raise
                _record(kind, name_of(self), input, result=result)
                return result
            finally:
                _inside.reset(token)
        wrapped = sync_call
    wrapped.__mangekyo_auto_trace__ = True
    return wrapped


def install() -> None:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from langgraph.graph.state import CompiledStateGraph

    for cls, kind, name in (
        (BaseChatModel, "model", lambda obj: type(obj).__name__),
        (BaseTool, "tool", lambda obj: obj.name),
        (CompiledStateGraph, "output", lambda obj: obj.name or "LangGraph"),
    ):
        for method_name in ("invoke", "ainvoke"):
            original = getattr(cls, method_name)
            setattr(cls, method_name, _wrap(original, kind, name))
