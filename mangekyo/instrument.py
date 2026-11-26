"""Small opt-in wrappers for custom Python agent call boundaries."""

from __future__ import annotations

import functools
import inspect
import json
from typing import Any, Callable

from .store import RunRecorder


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json")
        except (TypeError, ValueError):
            pass
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return repr(value)


def trace_call(run: RunRecorder, kind: str, function: Callable[..., Any], *,
               name: str | None = None) -> Callable[..., Any]:
    """Wrap a sync or async model/tool function and record observed execution."""
    if kind not in {"model", "tool"}:
        raise ValueError("Trace kind must be model or tool")
    label = name or getattr(function, "__name__", type(function).__name__)

    def emit(args: tuple[Any, ...], kwargs: dict[str, Any], *,
             result: Any = None, error: BaseException | None = None) -> None:
        observed_name = args[0] if label == "tool_dispatcher" and args and isinstance(args[0], str) else label
        payload: dict[str, Any] = {"name": observed_name, "input": {"args": _json_value(args),
                                                                     "kwargs": _json_value(kwargs)}}
        if error is None:
            payload["result"] = _json_value(result)
        else:
            payload["error"] = {"type": type(error).__name__, "message": str(error)}
        run.record(kind, **payload)

    if inspect.iscoroutinefunction(function):
        @functools.wraps(function)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = await function(*args, **kwargs)
            except Exception as exc:
                emit(args, kwargs, error=exc)
                raise
            emit(args, kwargs, result=result)
            return result
        return async_wrapper

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = function(*args, **kwargs)
        except Exception as exc:
            emit(args, kwargs, error=exc)
            raise
        emit(args, kwargs, result=result)
        return result
    return wrapper


def trace_tool_dispatcher(run: RunRecorder, dispatcher: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap the one function that actually dispatches named agent tools."""
    wrapped = trace_call(run, "tool", dispatcher, name="tool_dispatcher")
    return wrapped
