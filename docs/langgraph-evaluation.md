# LangGraph integration and branch cost contract

These tests were written before the integration. The ordinary tests use a
deterministic fake model and make no provider requests. They should fail if an
endpoint or branch invariant regresses.

## Endpoints to implement

The dashboard remains bound to `127.0.0.1`. A server operator explicitly
registers allowed graphs with `MANGEKYO_LANGGRAPH_GRAPHS`, a JSON object mapping
graph names to Python factory paths. An HTTP request cannot import an arbitrary
module. The test registration is
`{"invoice":"mangekyo.examples.invoice:build_graph"}`.
Each factory takes a LangGraph checkpointer and returns a compiled graph. It
must expose `resume_safe = True` before Mangekyo can fork it, and separately
`benchmark_safe = True` before Mangekyo can perform a cold rerun. The graph's
tool layer must enforce the underlying sandbox and idempotency rules; these
declarations are operator assertions, not an automatic rollback mechanism.
Set a stable `graph_version` string on the factory; Mangekyo refuses a fork if
the configured version differs from the one recorded on the source run.
Nodes report actual model usage in a `usage_items` state update. Graphs without
that convention remain traceable but cannot demonstrate model cost savings.

| Method and path | Purpose |
| --- | --- |
| `POST /api/v1/langgraph/runs` | Register an agent task and return a Mangekyo run ID. |
| `POST /api/v1/langgraph/runs/{run_id}/events` | Ingest a model or tool event, with provider usage when reported. |
| `POST /api/v1/langgraph/runs/{run_id}/checkpoints` | Store an immutable state snapshot with LangGraph `thread_id`, `checkpoint_id`, and `checkpoint_ns`. |
| `POST /api/v1/langgraph/runs/{run_id}/execute` | Run the registered graph to completion under its thread. |
| `GET /api/v1/runs/{run_id}` | Read the run, events, snapshots, output, and review status. |
| `GET /api/v1/snapshots/{snapshot_id}` | Read the state and LangGraph checkpoint locator. |
| `POST /api/v1/runs/{run_id}/flags` | Mark a plausible but wrong result for review without rewriting its execution status. |
| `POST /api/v1/runs/{run_id}/branches` | Create a correction branch from a checkpoint belonging to that run. |
| `POST /api/v1/branches/{branch_id}/resume` | Fork the original graph from that checkpoint and create a linked child run. |
| `POST /api/v1/branches/{branch_id}/benchmark` | Execute a matched cold corrected run and measure both paths. |
| `GET /api/v1/branches/{branch_id}/benchmark` | Retrieve the saved comparison without rerunning the model. |

Mutation endpoints should reject invalid or mismatched graph/checkpoint IDs. A
resume must reject unresolved actions before starting a child run. The price
rates passed to a benchmark are explicitly configured USD per million tokens;
the benchmark must use provider-reported token counts, not a character-count
estimate. A zero or unverified difference is reported as **no demonstrated
saving**. The initial failed run's cost is common to both correction strategies
and should be shown separately from the incremental rerun comparison.

The contained task reviews a synthetic invoice with a deliberately wrong
proposed account (`WRONG-ACCOUNT`). The expected correction is `SAFE-ACCOUNT`.
It proposes a payment but never sends one. The checkpoint named `after-read`
must let a corrected branch reuse the completed read while a cold corrected
run performs that read again. The fake model reports deterministic token usage.

## Run the contained task yourself

```powershell
.\.venv\Scripts\python.exe scripts/run_langgraph_invoice.py --home .mangekyo-test
.\.venv\Scripts\python.exe -m mangekyo --home .mangekyo-test dashboard
```

The first command prints the original wrong account, the corrected child run,
the skipped read step, and the matched cold-versus-branch cost report. The
second opens the same run history. The demo uses fake model usage by default;
its prices are illustrative and do not represent a provider invoice.

## Run the contract tests

From the repository root, make a development environment once:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[tui,evidence,langgraph]' pytest
```

Then run each contract separately or the full suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_langgraph_api.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_langgraph_checkpoint.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_langgraph_branch.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_langgraph_cost.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_langgraph_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_langgraph_provider.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

Each file command targets one contract independently. The last command
includes existing unit tests and excludes the opt-in live provider test.
GitHub Actions runs that deterministic full suite on Windows and Linux for
pushes and pull requests; it does not spend provider tokens.

## Opt-in provider-backed check

Set `OPENAI_API_KEY`, `MANGEKYO_LANGGRAPH_MODEL`, and the four explicit price
variables below to the rates for the model you chose. Then run:

```powershell
$env:MANGEKYO_LANGGRAPH_MODEL = 'YOUR_MODEL'
$env:MANGEKYO_TEST_PRICE_INPUT_USD_PER_M = 'YOUR_RATE'
$env:MANGEKYO_TEST_PRICE_CACHED_INPUT_USD_PER_M = 'YOUR_RATE'
$env:MANGEKYO_TEST_PRICE_CACHE_WRITE_USD_PER_M = 'YOUR_RATE'
$env:MANGEKYO_TEST_PRICE_OUTPUT_USD_PER_M = 'YOUR_RATE'
.\.venv\Scripts\python.exe -m pytest tests/live_langgraph.py -q
```

This test uses a real provider call and is excluded from the normal suite so CI
does not require an API key. It must fail if the branch does not demonstrate a
net saving at the supplied rates; a provider prompt-cache hit is measured
separately and is never assumed.
