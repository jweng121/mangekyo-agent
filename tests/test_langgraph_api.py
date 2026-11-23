"""Expected HTTP contract for LangGraph run and event ingestion."""

from conftest import register_invoice_run


def test_register_and_ingest_events(langgraph_api):
    client, _ = langgraph_api
    run_id = register_invoice_run(client)
    status, model = client.post(f"/api/v1/langgraph/runs/{run_id}/events", {
        "kind": "model", "node": "read_invoice", "payload": {"result": "INV-42"},
        "usage": {"provider": "fake", "model": "fixture-v1", "input_tokens": 1000,
                  "cached_input_tokens": 0, "cache_write_tokens": 0, "output_tokens": 50},
    })
    assert status == 201, model
    assert model["event_id"]
    status, tool = client.post(f"/api/v1/langgraph/runs/{run_id}/events", {
        "kind": "tool", "node": "lookup_supplier", "payload": {"supplier_id": "SUP-42"},
    })
    assert status == 201, tool

    status, detail = client.get(f"/api/v1/runs/{run_id}")
    assert status == 200, detail
    assert detail["run"]["adapter"] == "langgraph"
    assert detail["run"]["label"] == "Review invoice 42"
    assert [event["kind"] for event in detail["events"]] == ["registration", "model", "tool"]
    assert detail["events"][1]["usage"]["input_tokens"] == 1000


def test_only_configured_graphs_can_register(langgraph_api):
    client, _ = langgraph_api
    status, body = client.post("/api/v1/langgraph/runs", {
        "graph": "os:system", "task_id": "invalid", "thread_id": "invalid",
        "label": "Do not import", "input": {},
    })
    assert status in {400, 422}, body
    assert "error" in body
