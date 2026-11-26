import asyncio

from mangekyo import RunRecorder, Store, trace_call, trace_tool_dispatcher


def test_wrappers_capture_real_dispatch_and_model_result(tmp_path):
    with Store(tmp_path) as store, RunRecorder(store, "sql-agent", "question") as run:
        model = trace_call(run, "model", lambda prompt: {"tool": "list_tables"},
                           name="choose-tool")
        dispatch = trace_tool_dispatcher(run, lambda name, args: ["bookings"])
        assert model("Find bookings")["tool"] == "list_tables"
        assert dispatch("list_tables", {}) == ["bookings"]
        events = store.events(run.run_id)
        assert [event["kind"] for event in events] == ["model", "tool"]
        assert events[1]["payload"]["name"] == "list_tables"
        assert events[1]["payload"]["result"] == ["bookings"]


def test_async_tool_errors_are_recorded(tmp_path):
    async def failing_tool(_name):
        raise LookupError("missing")

    with Store(tmp_path) as store, RunRecorder(store, "agent", "task") as run:
        wrapped = trace_call(run, "tool", failing_tool)
        try:
            asyncio.run(wrapped("lookup"))
        except LookupError:
            pass
        else:
            raise AssertionError("Expected the tool error")
        assert store.events(run.run_id)[0]["payload"]["error"]["type"] == "LookupError"
