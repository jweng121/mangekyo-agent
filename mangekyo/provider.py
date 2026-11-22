"""Optional OpenAI Responses cache probe for a recorded snapshot."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .store import Store


def probe_openai_cache(store: Store, run_id: str, model: str, *,
                       api_key_env: str = "OPENAI_API_KEY",
                       base_url: str = "https://api.openai.com/v1/responses",
                       prices: dict[str, float] | None = None) -> dict[str, Any]:
    key = os.environ.get(api_key_env)
    if not key:
        raise ValueError(f"Set {api_key_env} before requesting a provider-backed benchmark")
    snaps = store.snapshots(run_id)
    if not snaps:
        raise ValueError("Run has no snapshots")
    stable = json.dumps(store.context(snaps[0]["id"]), sort_keys=True, ensure_ascii=False)
    prompts = [
        "Identify the next safe step for this captured agent state.",
        "Identify the next safe step after correcting the agent's plan.",
    ]
    result: list[dict[str, Any]] = []
    for index, prompt in enumerate(prompts):
        request_body = {
            "model": model,
            "input": [
                {"role": "user", "content": "Captured unchanged context:\n" + stable},
                {"role": "user", "content": prompt},
            ],
            "max_output_tokens": 128,
            "prompt_cache_key": "mangekyo-" + run_id,
        }
        req = urllib.request.Request(base_url, data=json.dumps(request_body).encode(),
                                     headers={"Authorization": "Bearer " + key,
                                              "Content-Type": "application/json"}, method="POST")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode(errors="replace")
            raise ValueError(f"Provider request failed ({exc.code}): {detail}") from exc
        usage = body.get("usage", {})
        details = usage.get("input_tokens_details") or {}
        item = {"request": index + 1, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                "cached_tokens": details.get("cached_tokens", "not reported"),
                "cache_write_tokens": details.get("cache_write_tokens", "not reported")}
        if prices and all(isinstance(item[k], int) for k in ("input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens")):
            ordinary = item["input_tokens"] - item["cached_tokens"] - item["cache_write_tokens"]
            item["estimated_usd"] = round((ordinary * prices["input"] +
                                           item["cached_tokens"] * prices["cached"] +
                                           item["cache_write_tokens"] * prices["cache_write"] +
                                           item["output_tokens"] * prices["output"]) / 1_000_000, 6)
        store.event(run_id, "model_benchmark", {"model": model, "usage": item,
                                                 "stable_context_hash": snaps[0]["manifest_hash"]})
        result.append(item)
    comparison = {"latency_delta_ms_first_minus_second": round(result[0]["elapsed_ms"] - result[1]["elapsed_ms"], 2),
                  "second_request_cached_tokens": result[1]["cached_tokens"]}
    if all("estimated_usd" in item for item in result):
        comparison["estimated_cost_delta_usd_first_minus_second"] = round(
            result[0]["estimated_usd"] - result[1]["estimated_usd"], 6)
    return {"provider": "openai", "model": model, "snapshot": snaps[0]["id"],
            "stable_context_chars": len(stable), "requests": result, "comparison": comparison,
            "note": "Two real provider requests. Cache hits are provider-reported; the small reference context may be ineligible."}
