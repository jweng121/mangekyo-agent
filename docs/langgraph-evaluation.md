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
The invoice examples record SHA-256 hashes and byte lengths for the stable
prompt prefix and changing suffix in each model usage item. Raw prompt text is
not copied into that usage record. Set `MANGEKYO_PROMPT_CACHE=1` to opt in to
an Anthropic ephemeral cache breakpoint on the stable prefix. A correction is
sent afterward in a separate content block. Cache hits still depend on the
provider's minimum length and retained entry, so the benchmark relies only on
reported cache token counts. The prefix is sent to Anthropic's cache; use this
only for content approved for provider caching. The adapter rejects this opt-in
when `MANGEKYO_REDACT` is configured because local redaction does not change
the provider request.
Nodes may return `tool_items` to record completed tool observations in the run.
A tool item with `action_key` and `action_state` also enters the action ledger.
A graph that reuses external files can expose `validate_checkpoint(context)` on
its factory; Mangekyo calls it before creating a resumed child and before a
cold benchmark. The file-backed example uses SHA256 digests to reject a changed
invoice or supplier register. Saved branch comparisons report tool-call counts
for the source, cold, and resumed runs alongside provider token usage.

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
resume must reject unresolved actions (including failed actions) and completed
actions after the chosen checkpoint before starting a child run. A tool event
with `action_key` and `action_state` records that action for these checks. The
action ledger timestamps its latest state transition, so an intent recorded
before a checkpoint and completed afterward still blocks resume. Completion
events also protect older ledgers whose action timestamp was not updated. The price
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
Use `mangekyo --home .mangekyo-test benchmark PARENT_RUN_ID` to read the saved
LangGraph comparison without rerunning a graph or calling the provider.
`mangekyo --home .mangekyo-test show BRANCH_NAME` includes that branch's saved
report. In `mangekyo --tui`, select either the parent or corrected run and type
`benchmark` for the same saved comparison.

## File-backed integration example

This second graph reads an actual `invoice.json` and `suppliers.csv` from a
local workspace, records both read tools with their digests, then makes a
proposal. It never sends a payment or writes to the workspace. The parent
proposes `WRONG-ACCOUNT`; a branch from `after-load` reuses the file reads and
proposes the approved `SAFE-ACCOUNT`. The cold comparison rereads both files.
The graph requires an operator-set `MANGEKYO_FILE_INVOICE_ROOT` and refuses
workspaces outside it; the example script sets that root to its selected
workspace.

```powershell
.\.venv\Scripts\python.exe scripts/run_langgraph_file_invoice.py --home .mangekyo-file-demo
.\.venv\Scripts\python.exe -m mangekyo --home .mangekyo-file-demo dashboard
```

The default model reports deterministic fixture tokens, so its estimated
dollar saving is illustrative. Supply your own workspace with `--workspace`
only if it contains the two files in the same format as
[`examples/file-invoice`](../examples/file-invoice). With a real provider set
`MANGEKYO_LANGGRAPH_MODEL`, its API key, and all four explicit price arguments
to the script. A changed source file makes resume fail before creating a child
run. An unresolved or completed post-checkpoint action also blocks resume.

To opt in to caching parsed read results, add
`--tool-cache-home .mangekyo-tool-cache` to the script. The cache stores only
JSON and CSV parse results. Its key includes the tool version, relative path,
parser, relevant parsing context, and resolved workspace; it compares the
source file's SHA256 digest before every reuse and expires entries after one
hour by default. Tool events show `cache_status` as `miss`, `hit`,
`source_changed`, `expired`, or `disabled`, and the script prints parent and
cold-run statuses. It still reads file bytes to validate freshness and does
not cache model calls, writes, or payments. Set `MANGEKYO_TOOL_CACHE_TTL` to a
nonnegative number of seconds to change the expiry time. When
`MANGEKYO_REDACT` is configured, parsed read caching is disabled to avoid
persisting an unredacted copy of those values.

An opt-in live test also exercises this graph with the model configured in
`.env.local`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/live_file_invoice.py -q -s
```

On November 24, 2026, the test passed with Claude Haiku 5.5 using the adapter
that rejects missing cache counters. Source run `732613ab2c68` recorded two
real file reads and branched from snapshot `8b104fe15f33` (LangGraph
checkpoint `1f1e84f9-6b7d-65f5-8001-b900f5186d9a`). Both corrected runs
proposed `SAFE-ACCOUNT`; the branch skipped `load_documents`, avoided two tool
reads, and reported no duplicate side effects. At the locally configured rates
of $0.10 per million input tokens and $0.50 per million output tokens, the
branch used 52 input and 81 output tokens ($0.0000457) versus 131 input and
88 output tokens ($0.0000571) for the cold rerun. The resulting **incremental
model saving was $0.0000114**, and the branch finished 0.559 s sooner. Both
paths explicitly reported zero cache-read and cache-write tokens. The
configured rates were not checked against a provider invoice. This measures
one small local file workflow; it does not establish a general saving rate.

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
.\.venv\Scripts\python.exe -m pytest tests/test_langgraph_file_invoice.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

Each file command targets one contract independently. The last command
includes existing unit tests and excludes the opt-in live provider test.
GitHub Actions runs that deterministic full suite on Windows and Linux for
pushes and pull requests; it does not spend provider tokens.

## Opt-in provider-backed check

Set your Anthropic key, model, and current provider rates in your shell before
running the live test. The test also reads an optional `.env.local` file in the
repository root; that file is ignored by Git, and existing environment values
take precedence. Set `MANGEKYO_PROMPT_CACHE=0` for the uncached comparison or
`1` for an opt-in Anthropic cache comparison. The latter may charge for a cache
write on the original run; the benchmark prices writes and reads separately.
Check the current [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
before filling in the four rate variables.

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
$env:MANGEKYO_LANGGRAPH_MODEL = "claude-haiku-5-5"
$env:MANGEKYO_PROMPT_CACHE = "0"
$env:MANGEKYO_TEST_PRICE_INPUT_USD_PER_M = "current-input-rate"
$env:MANGEKYO_TEST_PRICE_CACHED_INPUT_USD_PER_M = "current-cached-input-rate"
$env:MANGEKYO_TEST_PRICE_CACHE_WRITE_USD_PER_M = "current-cache-write-rate"
$env:MANGEKYO_TEST_PRICE_OUTPUT_USD_PER_M = "current-output-rate"
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/live_langgraph.py -q -s
```

This test uses a real provider call and is excluded from the normal suite so CI
does not require an API key. It must fail if the branch does not demonstrate a
net saving at the supplied rates; a provider prompt-cache hit is measured
separately and is never assumed. The command prints the complete benchmark,
including the parent run and graph checkpoint IDs, provider-reported token
usage, configured-rate model costs, skipped steps, elapsed time, and the saving
verdict.

### Measured Claude run (2026-11-24)

The opt-in test passed again with Claude Haiku 5.5 after the adapter began
rejecting missing cache counters. Parent run `1deecd2359b0` branched from
snapshot `cab3f21fb380` (LangGraph checkpoint
`1f1e84f8-e556-660a-8001-7d38d5160ea6`). Both corrected paths produced
`SAFE-ACCOUNT`; the branch skipped `read_invoice` and reported no duplicate
side effect.

| Corrected path | Input tokens | Output tokens | Model cost | Elapsed |
| --- | ---: | ---: | ---: | ---: |
| Branch (`d0feaa22aafc`) | 53 | 74 | $0.0000423 | 0.767 s |
| Full rerun (`4ef7f24a4bb2`) | 3,955 | 89 | $0.0004400 | 1.292 s |

The **net incremental model saving was $0.0003977**, and the branch finished
0.525 s sooner. Both corrected paths explicitly reported zero cache-read and
cache-write tokens. The request had no `cache_control` field, so Anthropic
prompt caching was not enabled; the saving came from skipped model work.
Costs use provider-reported usage at configured rates, not reconciled
billing. This is one contained task, not a general saving rate.

### Opt-in prompt-cache comparison (2026-11-24)

With `MANGEKYO_PROMPT_CACHE=1`, the same contained task used an Anthropic
ephemeral breakpoint on the unchanged `read_invoice` prefix. Parent run
`903bc83f99fd` wrote 3,898 cache tokens; the matched cold corrected run read
3,898 cached tokens. The resumed branch skipped `read_invoice`, so it had no
cache read. Both corrected paths still produced `SAFE-ACCOUNT` with zero
duplicate side effects.

| Corrected path | Input tokens | Cache-read tokens | Output tokens | Model cost | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Branch (`2c6eb6b1bdf1`) | 53 | 0 | 52 | $0.0000313 | 0.949 s |
| Full rerun (`d291a85e9eae`) | 3,955 | 3,898 | 80 | $0.00008468 | 1.307 s |

The branch still saved **$0.00005338** in incremental model cost and finished
0.358 s sooner. The provider cache saving metric was **-$0.00035082** because
the cold rerun received a cache discount that the branch did not need. The
parent run's $0.00054145 model cost, including its cache write, is common to
both correction paths. These amounts use provider usage at the configured
rates, not reconciled billing. Cache availability and model output lengths can
change on another run.

### Earlier Claude run (2026-11-23)

The opt-in test passed against Claude Haiku 5.5 with thinking disabled for this
short extraction task, using provider-reported usage and the published rates
above. Parent run `b2833fe3d0f4` branched from snapshot `a5fd69a85848`,
whose LangGraph checkpoint ID was `1f1e6fe1-25e8-6ffd-8001-78aa27a444e7`;
the branch skipped `read_invoice`.
Both corrected runs produced `SAFE-ACCOUNT`, and neither reported a duplicate
side effect.

| Corrected path | Input tokens | Output tokens | Model cost | Elapsed |
| --- | ---: | ---: | ---: | ---: |
| Branch (`cb8f5b3af563`) | 53 | 86 | $0.0000483 | 0.788 s |
| Full rerun (`8b6d80808d85`) | 3,955 | 105 | $0.0004480 | 1.257 s |

The **net model saving was $0.0003997** for this one correction, and the branch
finished 0.470 s sooner. The cold run's skipped read step cost $0.0003972;
the small difference came from variable output token counts.
The recorded provider prompt-cache saving was **$0**. This example sent no
`cache_control` field, which [Anthropic requires to enable prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
so the saving came from skipped model work. The original adapter
normalized missing or null cache counters to zero; the raw response was not
retained, so the historical record cannot establish whether the provider
explicitly returned zeros. The adapter now rejects missing cache counters
before making a cost claim. The historical costs use recorded input and output
usage at the configured published rates, not reconciled Anthropic billing.
This result demonstrates a saving for the contained task; other graphs and
corrections need their own measurements.

For OpenAI instead, set `OPENAI_API_KEY` in `.env.local`, change the model there to `gpt-6-luna`, and
use its current [published rates](https://developers.openai.com/api/docs/models/gpt-6-luna).
The four example rate values above were the same for these two inexpensive
models when checked, but always verify the rate for your provider and tier.
