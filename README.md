<p align="center">
  <img src="assets/github/mangekyo-agent-banner.png" alt="MANGEKYO-AGENT red pixel-art wordmark on a dark gray banner" width="100%">
</p>

<h1 align="center">Mangekyo Agent</h1>

<p align="center">
  <a href="https://github.com/jweng121/mangekyo-agent">GitHub</a> ·
  <a href="docs/README.md">Documentation</a>
</p>

<p align="center">
  <a href="docs/README.md"><img alt="Docs: Read the docs" src="https://img.shields.io/badge/DOCS-READ%20THE%20DOCS-FF343B?style=for-the-badge&labelColor=444444"></a>
  <a href="docs/README.md#language"><img alt="Language: English" src="https://img.shields.io/badge/LANG-ENGLISH-BD0718?style=for-the-badge&labelColor=444444"></a>
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/LICENSE-APACHE%202.0-BD0718?style=for-the-badge&labelColor=444444"></a>
  <a href="https://github.com/jweng121"><img alt="Built by James Weng" src="https://img.shields.io/badge/BUILT%20BY-JAMES%20WENG-FF343B?style=for-the-badge&labelColor=444444"></a>
</p>

**Local execution history and recovery for Python agents.** Mangekyo Agent captures runs, preserves evidence, and supports contained recovery from checkpoints.

The [agent improvement workflow](docs/agent-improvement-workflow.md) documents
portable JSON trace import, outcome checks, corrected-snapshot commits, and a
user-owned local model pipeline. Its keyless SQL example exercises the full
failure-to-correction path with fixture model usage.

The [complete user walkthrough](docs/complete-user-workflows.md) gives three
manual paths through a PDF-backed sample agent: debugging Chat, the model-free
terminal inspector, and the dashboard. Start with `mangekyo sample` to create
an isolated agent project.

The first working draft includes standalone Windows and Linux commands, a terminal UI, a local dashboard, and a reference recovery demo.

## Try the reference flow

For a published Windows beta release, the PowerShell quick start installs Mangekyo and initializes local history without asking for a model, provider, fallback, config path, or terminal backend:

```powershell
irm https://raw.githubusercontent.com/jweng121/mangekyo-agent/refs/heads/main/install.ps1 | iex
```

The script selects the most recently published Windows release, including betas, checks its SHA256 hash against the release manifest, installs it in your user profile, adds `mangekyo` to your user PATH, and runs `mangekyo setup`. It then offers to open the terminal run inspector (`mangekyo --tui`). Declining leaves setup complete. Run the installer directly in PowerShell so the command is available in that session. A VS Code terminal opened before installation may need a PATH refresh or app restart. For unattended installation, run the script with `-NoPrompt`; use `-LaunchTui` to open the inspector explicitly.

On Windows, a locally built standalone executable is at `dist/mangekyo.exe`. Install it for your user once. This copies the executable into your user profile and adds that folder to your user PATH; it needs no administrator rights or Python installation. An already open VS Code or terminal keeps its old PATH. In that PowerShell session, run `$env:Path += ";$env:LOCALAPPDATA\Mangekyo\bin"`, or restart VS Code or Windows Terminal before using the bare command:

```powershell
.\install-windows.cmd
mangekyo demo
mangekyo --tui
mangekyo dashboard
```

The release workflow requires a trusted code signature before publishing the Windows executable. An unsigned local build was blocked by Windows Smart App Control during release validation; the Python source and SDK remain available for local development.

On Linux, a locally built x64 executable is at `dist/linux/mangekyo`. From this checkout, install it in your user profile with its SHA256 hash, then run the reference flow:

```sh
hash=$(sha256sum dist/linux/mangekyo | cut -d ' ' -f 1)
bash install-linux.sh dist/linux/mangekyo "$hash"
~/.local/bin/mangekyo demo
~/.local/bin/mangekyo --tui
~/.local/bin/mangekyo dashboard
```

The installer runs setup before replacing any existing executable. Set `MANGEKYO_BIN_DIR` to choose another installation directory. The packaged build and installer have been verified on Ubuntu under WSL; other Linux environments and macOS still need verification. See the [Linux release guide](docs/linux-release.md).

For a PyPI distribution, the Python package can be installed in an existing Python 3.11+ environment. The `tui` and `evidence` extras enable both local interfaces and document previews; `langgraph` adds the optional integration:

```sh
python -m pip install "mangekyo-agent[tui,evidence]"
mangekyo setup
mangekyo demo
mangekyo --tui
mangekyo dashboard
```

The Python package is being prepared locally for PyPI and has not been uploaded. The standalone installers above remain the route that does not ask users to install Python or run `pip`.

For TypeScript and Node.js agents, the [npm package source](npm/README.md) provides a framework independent recorder plus integrations for the OpenAI Agents SDK and Claude Agent SDK. It imports model, tool, and output events into the same local run history. The npm package is prepared locally and has not been published.

Stop and restart an older dashboard process after updating the executable. A custom store must use the same `--home` argument for both commands, before the subcommand: `mangekyo --home PATH demo` and `mangekyo --home PATH dashboard`.

To run from Python source instead, use Python 3.11 or newer and install the package in a virtual environment:

```sh
python -m pip install -e ".[tui,evidence]"
mangekyo setup
mangekyo demo
mangekyo --tui
mangekyo dashboard
```

If Python and `prompt-toolkit` are already available, you can try this checkout without installing the package by replacing `mangekyo` with `python -m mangekyo` in those commands.

Run `mangekyo doctor` to check an existing local store. If the store is missing, doctor reports the `setup` command to run without creating files; it also checks SQLite integrity for an existing store.

The demo prints a run ID, snapshot ID, and resolved store path. It records a deliberately wrong write in a disposable target under `.mangekyo/simulation/`. To correct and resume it from the CLI:

The demo also records a synthetic PDF instruction and image preview as actual read events. The dashboard shows the parsed text supplied by the reference agent and saved boxes over the fields it read.

```sh
mangekyo show RUN_ID
mangekyo branch SNAPSHOT_ID -m fixed --replacement safe
mangekyo resume fixed
mangekyo benchmark RUN_ID
```

`mangekyo dashboard` opens a browser at `http://127.0.0.1:8765` and reads the same store as the CLI and terminal UI. Its Chat panel uses the same debugging model and conversations as `mangekyo chat`. `mangekyo --tui` opens the run inspector directly with no model requirement. Type `/` to browse commands with ↑↓, or `/help` for the full list. `mangekyo chat` opens the full-screen interface and guides first-time model setup inside it. `/model` reopens setup. `MANGEKYO_HOME` selects another store path. `MANGEKYO_REDACT` accepts comma-separated literal secrets that are replaced before event and snapshot objects are persisted.

The TUI can register and run an existing Python agent without a shell setup sequence. Start `mangekyo --tui`, then type `/add PATH` and `/launch`. `/add` detects the project, connects the SDK to its `.venv` when present, and remembers the active project. It discovers `agent.py`, `run_agent.py`, or `main.py` as a default entrypoint. For another entrypoint, type `/launch COMMAND` once; the command is saved in the project config for later `/launch` calls. A LangGraph project can use `/add PATH --graph NAME=module:factory` to register a resumable graph. Each launch records the agent while the TUI stays open. Type `/launch --capture-output` to also save bounded stdout and stderr from a short batch run. Type `/capture` to see what was actually recorded. New events appear as the run progresses; `/refresh` also reloads runs created outside that TUI session. Up/Down recalls submitted commands; Ctrl-P/Ctrl-N moves through events. The [interactive SQL example](examples/sql-user-demo/README.md) uses this flow for a PDF-backed agent and performs checking, branching, resume, and commit inside the TUI.

After resuming the demo, the dashboard's recovery summary shows skipped steps and shared objects. Select **Measure cold comparison** to run the offline baseline and see the measured time difference. It may be faster or slower for this tiny local task; the summary does not claim provider model savings for the offline fixture.
The TUI's `benchmark` command runs the same cold comparison once and keeps the full report in its detail panel. For LangGraph runs, it displays a saved comparison without rerunning a model.

The TUI renders the approved Classic Scarlet artwork as SIXEL graphics in Windows Terminal and as a PNG with the Kitty graphics protocol in VS Code's integrated terminal (with `terminal.integrated.enableImages` enabled). At 153 columns or wider it shows the original one-line wordmark. At 70–152 columns it stacks MANGEKYO above AGENT, left aligned with a small gap, using pixels cut from that same wordmark. Terminals without image support show a plain title; set `MANGEKYO_BANNER=unicode` to opt into the approximate character-cell artwork. `NO_COLOR` affects only the Unicode mode.

## Inspect documents and annotate them

Attach the exact PDF or image an agent used, and optionally the text it extracted:

```sh
mangekyo evidence add RUN_ID path/to/document.pdf --event EVENT_ID --parsed-text-file path/to/extracted.txt
mangekyo dashboard
```

Open the item under **Evidence**, switch PDF pages, enter a note, and drag a rectangle over the page to save an annotation. The dashboard displays the original captured file, the agent supplied parsed text, and saved page coordinates. If no parsed text was supplied, it says so; it does not infer what the agent read. Your own agent can call `run.artifact("path/to/document.pdf", parsed_text=extracted_text)` inside `RunRecorder`.

For a web page, run `mangekyo setup --browser` once, then `mangekyo evidence capture RUN_ID https://example.com`. This optional adapter uses Playwright and Chromium to save a full-page screenshot and the page text. PDF pages are rendered locally with PDFium; Playwright is used for browser pages. Evidence files are stored locally and are capped at 50 MB.

Add `--selector '#approve-button'` to a browser capture to record that element's page coordinates and highlight it on the screenshot. The [local browser-target example](docs/browser-target.md) shows the captured page, linked decision event, and annotation without accessing an external site.
Use `--mask-selector '#private-field'` for a visual region that must be hidden; masked captures omit extracted page and target text. When `MANGEKYO_REDACT` is set, browser capture is disabled because literal redaction cannot erase screenshot pixels.

The offline benchmark compares an actual corrected cold run with the recorded resumed branch. It reports local elapsed time and shared context objects. Its reference agent makes no model calls, so provider prompt-cache savings are **not measured** by that fixture.

`mangekyo cache stats` reports physical object storage and snapshot context reuse. `context_saved_bytes` is the sum of repeated context object bytes avoided by content-addressed sharing; it excludes manifest, event, and artifact bytes and is separate from tool-result or provider prompt-cache savings.

For a model-backed comparison, the [LangGraph invoice walkthrough](docs/langgraph-evaluation.md) records a wrong result, flags it, forks from the `after-read` checkpoint, resumes the corrected branch, and compares it with a cold corrected run. In a Claude Haiku 5.5 run on November 24, 2026, both corrected paths produced `SAFE-ACCOUNT`; the branch skipped `read_invoice`, saved **$0.0003977** in incremental model cost, and finished **0.525 s** sooner. The adapter required explicit provider cache counters, which were zero on both paths. The request did not enable Anthropic prompt caching, so the saving came from skipped work. This is one contained task, with cost calculated from provider usage at configured rates rather than reconciled billing. Run `python scripts/run_langgraph_invoice.py --home .mangekyo-test` for the deterministic version, then open that store in the dashboard.

Set `MANGEKYO_PROMPT_CACHE=1` for an opt-in Anthropic cache comparison. The example records hashes for stable and changing request segments, places an ephemeral cache breakpoint on the stable prefix, and reports provider cache reads and writes separately. In one measured opt-in run, the cold rerun read 3,898 cached tokens and the branch still saved $0.00005338 in incremental model cost; see the [evaluation](docs/langgraph-evaluation.md) for the full comparison.

The file-backed LangGraph example can opt into a validated JSON/CSV read cache with `python scripts/run_langgraph_file_invoice.py --tool-cache-home .mangekyo-tool-cache`. Its tool events report cache reuse or recomputation separately from model and provider prompt-cache savings.

Use `mangekyo bundle export RUN_ID run-history.json` and `mangekyo --home OTHER_HOME bundle import run-history.json` to move captured history between local stores. The [bundle guide](docs/run-bundles.md) explains the contents and limits. The optional [self-hosted team API](docs/team-sharing.md) accepts bundles into authenticated workspaces for shared inspection and review.

To make two real OpenAI Responses requests using the first snapshot's unchanged context, explicitly run `mangekyo benchmark RUN_ID --openai-model MODEL` with `OPENAI_API_KEY` set. The command reports provider-returned cached and written token counts and elapsed time for both calls. The short reference context may be below the provider's cache threshold, so a cache hit is not guaranteed. Prices are not assumed; pass all four `--input-price`, `--cached-price`, `--cache-write-price`, and `--output-price` rates (USD per million tokens) for an estimated request cost.

## Record a launched agent automatically

Run an agent through Mangekyo to create a named run without changing the agent's code:

```powershell
mangekyo run -- python agent.py
mangekyo run --label "Review invoice 42" -- python agent.py
mangekyo log
```

For a short batch command whose printed result matters, use `mangekyo run --capture-output -- python agent.py`. This saves at most 256 KB each of stdout and stderr as a `process_output` event while keeping the live terminal output. `mangekyo show RUN_ID` and the dashboard show a per-run capture report based on saved evidence, including missing fields and reported capture failures. A check case can target `"kind": "process_output"` with an exact expected `stdout` or `stderr` value. See the [capture and recovery contract](docs/capture-and-recovery.md) for limits and privacy considerations.

Mangekyo prints the run ID, records the command, working directory, process ID, and exit status, and shows the agent name and start time in the dashboard. It passes `MANGEKYO_RUN_ID` and `MANGEKYO_HOME` to the child process. This process-level recording does not capture internal model calls, tool calls, or snapshots; those require an agent adapter or the Python recording API below. Mangekyo does not detect processes started outside `mangekyo run`.

## Recording your agent

```python
from mangekyo import RunRecorder, Store

with Store() as store:
    with RunRecorder(store, "my-agent", "example task") as run:
        run.record("model", request={"messages": ["..."]}, response="...", usage={"input_tokens": 10})
        run.record("tool", name="read-file", result="...")
        run.checkpoint("before-next-step", messages=["..."], runtime_state={"step": 2})
```

`RunRecorder` also has `arecord` and `acheckpoint` for async code. Generic recorded runs support inspection, diffs, and recorded replay. Live resume currently works only for the included simulation adapter. Agent-context snapshots do not reverse changes to external systems.

### How a run and branch map to an agent

A **run** is one execution attempt by one named agent. Its ordered events are the agent's reads, decisions, tool calls, and checks. A **checkpoint** captures the context at a point before a consequential action. A **branch** names a correction to one checkpoint; a successful resume creates a new child run linked to the original through `parent_run` and to the exact checkpoint through `source_snapshot`. The dashboard's default snapshot track shows that fork, while **List view** exposes the full event log. Selecting a read opens the captured PDF or image and its saved annotations.

Wrap the agent's task entry point and record each tool boundary. Pass the same event ID when attaching the exact document or image the agent read:

```python
from mangekyo import RunRecorder, Store

with Store() as store, RunRecorder(store, "invoice-agent", "Review invoice 42") as run:
    read_id = run.record("read", tool="extract_pdf", path="invoice.pdf")
    run.artifact("invoice.pdf", event_id=read_id, parsed_text=extracted_text)
    run.checkpoint("before-payment", messages=messages, runtime_state={"step": "pay"})
    run.record("decision", action="hold", reason="Amount needs review")
```

`RunRecorder` works with synchronous or asynchronous Python agents and does not require a particular agent framework. An integration with another framework calls these methods from its model and tool hooks. To execute a corrected branch for a real agent, its adapter must restore both the agent context and the relevant environment, reconcile any pending actions, and resume from the saved step. The bundled simulation is the working example; generic recorded runs can be inspected and branched but cannot yet execute a live resume.

For a project with a `.venv`, `mangekyo setup --project PATH` installs the SDK into that environment, verifies the import, and prints a small recording example to paste into the agent. This supported project path avoids a manually typed `pip` command, although setup invokes the project's package installer internally. A standalone build bundles the SDK wheel and does not need a package download for this step. It does not edit the agent's source code; add the recording calls where you want real execution events captured.

## Standalone distribution

The planned user-facing flow starts with downloading a standalone launcher or installer, then running `mangekyo setup`; users would not have to type a `pip` command. Windows and Linux standalone executables have been built locally in `dist/` and `dist/linux/`; neither is published. To rebuild on the host OS, install this package with its `tui,evidence` extras plus PyInstaller, then run `python scripts/build_standalone.py`. The build embeds the SDK wheel for offline project connection. Playwright's Chromium browser is a separate optional download. PyInstaller builds for its host OS; macOS still needs a build and verification.

## Terminal banner

The terminal UI uses the **Classic Scarlet** two-tone red artwork in terminals that support SIXEL images. The [approved one-line PNG](assets/terminal/mangekyo-agent-banner.png), [stacked PNG](assets/terminal/mangekyo-agent-banner-stacked.png), [copyable Unicode approximation](assets/terminal/mangekyo-agent-banner.txt), and [true-color ANSI approximation](assets/terminal/mangekyo-agent-banner.ans) are available in `assets/terminal`.

<details>
<summary>Show Unicode banner</summary>

```text
██      ██     ██████   ██    ██     ██████   ████████   ██    ██   ██    ██     ████                ██████     ██████   ████████   ██    ██   ████████
████  ████░  ██ ░░░██░  ████  ██░  ██ ░░░░░░  ██░░░░░░░  ██░ ██ ░░  ██░   ██░  ██ ░░░██            ██ ░░░██░  ██ ░░░░░░  ██░░░░░░░  ████  ██░   ░████░░░
██░░██ ░██░░ ████████░░ ██░░████░░ ██░ ████░░ ██████░░░░ ████ ░░ ░░  ░████ ░░░ ██░ ░░██░  ██████   ████████░░ ██░ ████░░ ██████░░░░ ██░░████░░   ████░░░░
██░░░░░ ██░░ ██░░░░██░░ ██░░░░██░░ ██░░ ░██░  ██░░░░░    ██░░██░░     ████░ ░░ ██░░  ██░░  ░░░░░░  ██░░░░██░░ ██░░ ░██░  ██░░░░░    ██░░░░██░░   ████░░
██░░  ░░██░░ ██░░░░██░░ ██░░  ██░░  ░██████░░ ████████   ██░░░░██     ████░░    ░████ ░░░   ░░░░░░ ██░░░░██░░  ░██████░░ ████████   ██░░  ██░░   ████░░
 ░░░     ░░░  ░░░   ░░░  ░░░   ░░░   ░░░░░░░░  ░░░░░░░░   ░░░  ░░░     ░░░░░     ░░░░░ ░░           ░░░   ░░░   ░░░░░░░░  ░░░░░░░░   ░░░   ░░░    ░░░░░
  ░░      ░░   ░░    ░░   ░░    ░░     ░░░░░░   ░░░░░░░░   ░░    ░░     ░░░░       ░░░░              ░░    ░░     ░░░░░░   ░░░░░░░░   ░░    ░░     ░░░░
```

</details>

## Documentation

Start with the [documentation overview](docs/README.md). The [brand asset guide](assets/README.md) identifies the approved terminal, dashboard, and GitHub artwork.

## License

Licensed under [Apache License 2.0](LICENSE).

## Built by

[James Weng](https://github.com/jweng121).
