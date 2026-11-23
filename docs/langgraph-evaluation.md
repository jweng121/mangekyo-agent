# LangGraph integration and branch cost contract

These tests were written before the integration. The ordinary tests use a
deterministic fake model and make no provider requests. They should fail if an
endpoint or branch invariant regresses.

## Endpoint contract

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
resume must reject unresolved actions and completed actions after the chosen
checkpoint before starting a child run. A tool event with `action_key` and
`action_state` records that action for these checks. The price
rates passed to a benchmark are explicitly configured USD per million tokens;
the benchmark must use provider-reported token counts, not a character-count
estimate. A zero or unverified difference is reported as **no demonstrated
saving**. Flag the source run with a known expected result before a benchmark;
without that result Mangekyo refuses to spend tokens on a cold rerun. The
initial failed run's cost is common to both correction strategies and is shown
separately from the incremental rerun comparison.

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

Set `ANTHROPIC_API_KEY` in the PowerShell session without printing the key:

```powershell
$secureKey = Read-Host 'Anthropic API key' -AsSecureString
$env:ANTHROPIC_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
```

The example below uses the
published [Claude Haiku 5.5 rates](https://platform.claude.com/docs/en/about-claude/pricing)
for prompts below 100,000 tokens, checked in November 2026. Verify current
rates before using the result as a cost claim. Then run:

```powershell
$env:MANGEKYO_LANGGRAPH_MODEL = 'claude-haiku-5-5'
$env:MANGEKYO_TEST_PRICE_INPUT_USD_PER_M = '0.10'
$env:MANGEKYO_TEST_PRICE_CACHED_INPUT_USD_PER_M = '0.01'
$env:MANGEKYO_TEST_PRICE_CACHE_WRITE_USD_PER_M = '0.125'
$env:MANGEKYO_TEST_PRICE_OUTPUT_USD_PER_M = '0.50'
.\.venv\Scripts\python.exe -m pytest tests/live_langgraph.py -q -s
```

This test uses a real provider call and is excluded from the normal suite so CI
does not require an API key. It must fail if the branch does not demonstrate a
net saving at the supplied rates; a provider prompt-cache hit is measured
separately and is never assumed. The command prints the complete benchmark,
including provider-reported token usage, configured-rate model costs, skipped
steps, elapsed time, and the saving verdict.

For OpenAI instead, set `OPENAI_API_KEY`, change the model to `gpt-6-luna`, and
use its current [published rates](https://developers.openai.com/api/docs/models/gpt-6-luna).
The four example rate values above were the same for these two inexpensive
models when checked, but always verify the rate for your provider and tier.
