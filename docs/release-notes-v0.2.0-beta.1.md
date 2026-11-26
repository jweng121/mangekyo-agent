# Mangekyo Agent v0.2.0-beta.1

This Windows x64 and Linux x64 beta lets you inspect a failed agent run, review its captured evidence, correct a checkpoint, resume execution, and compare the result with a cold rerun. The CLI, terminal UI, and local dashboard show the same run history. The bundled demo works offline and makes no model calls.

## Try the recovery flow

After installing the Windows release asset and running `mangekyo setup`:

```powershell
mangekyo demo
mangekyo show RUN_ID
mangekyo branch SNAPSHOT_ID -m fixed --replacement safe
mangekyo resume fixed
mangekyo benchmark RUN_ID
mangekyo --tui
mangekyo dashboard
```

`demo` prints the run and snapshot IDs to use above. In the dashboard, select the failed run and choose **Measure cold comparison** to populate the recovery summary. See the [reference walkthrough](https://github.com/jweng121/mangekyo-agent/blob/v0.2.0-beta.1/docs/example-workflow.md) for the inspection steps.

On Linux x64, download `mangekyo-linux-x64`, `SHA256SUMS-linux.txt`, and `install-linux.sh` from this release into one directory, then run:

```sh
sha256sum -c SHA256SUMS-linux.txt
bash install-linux.sh mangekyo-linux-x64
~/.local/bin/mangekyo demo
```

The Linux executable and installer were verified on Ubuntu under WSL. Other Linux distributions and macOS have not been verified.

The Python package is also prepared for PyPI as `mangekyo-agent` version `0.2.0b1`. Once published, an existing Python 3.11+ environment can install the CLI, terminal UI, and evidence features with:

```sh
python -m pip install "mangekyo-agent[tui,evidence]"
```

The wheel and source archive passed local metadata and isolated installation checks. PyPI publication is a separate job after the platform and GitHub release gates and requires an account-side Trusted Publisher.

## Measured model-backed example

In one Claude Haiku 5.5 invoice correction on November 24, 2026, both corrected paths returned `SAFE-ACCOUNT`. Resuming from the `after-read` checkpoint skipped `read_invoice`:

| Corrected path | Input tokens | Output tokens | Model cost | Elapsed |
| --- | ---: | ---: | ---: | ---: |
| Resumed branch | 53 | 74 | $0.0000423 | 0.767 s |
| Cold corrected run | 3,955 | 89 | $0.0004400 | 1.292 s |

The branch saved **$0.0003977** in incremental model cost and finished **0.525 s** sooner for this correction. The adapter required explicit cache counters, and both corrected paths reported zero cache-read and cache-write tokens. The request did not enable Anthropic prompt caching, so provider prompt-cache savings were **$0**; the saving came from skipped work. Costs use provider-reported usage and the configured published rates at the time, not reconciled billing. This single contained example does not predict savings for other agents. The [LangGraph evaluation](https://github.com/jweng121/mangekyo-agent/blob/v0.2.0-beta.1/docs/langgraph-evaluation.md) gives the setup, checkpoint, usage, and safety details.

An opt-in prompt-cache run of the same task showed the tradeoff: the cold rerun read 3,898 cached tokens, while the branch skipped that read. The cold path received the provider cache discount; the branch still saved **$0.00005338** in incremental model cost and finished **0.358 s** sooner at the configured rates.

## Scope

The standalone assets target Windows x64 and Linux x64. The bundled recovery demo is offline; model-backed evaluation needs separate provider credentials. Real agents need a compatible adapter and checkpoints to resume. The optional JSON/CSV read cache, browser evidence capture, run bundles, and self-hosted team API are documented in the [project guide](https://github.com/jweng121/mangekyo-agent/blob/v0.2.0-beta.1/README.md). Team sharing has been exercised between separate local processes over TLS; two physical computers have not yet been verified.
