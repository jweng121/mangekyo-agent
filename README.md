<p align="center">
  <img src="assets/github/mangekyo-agent-banner.png" alt="MANGEKYO-AGENT red pixel-art wordmark on a dark banner" width="100%">
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

The first working draft includes a standalone Windows command, terminal UI, local dashboard, and a reference recovery demo.

## Try the reference flow

For a published Windows release, install in PowerShell with one line, then run Mangekyo directly:

```powershell
irm https://raw.githubusercontent.com/jweng121/mangekyo-agent/refs/heads/main/install.ps1 | iex
mangekyo setup
mangekyo demo
```

The script downloads the latest Windows release, checks its SHA256 hash against the release manifest, installs it in your user profile, and adds `mangekyo` to your user PATH. Run it directly in PowerShell so the command is available in that session. A VS Code terminal opened before installation may need a PATH refresh or app restart.

On Windows, a locally built standalone executable is at `dist/mangekyo.exe`. Install it for your user once. This copies the executable into your user profile and adds that folder to your user PATH; it needs no administrator rights or Python installation. An already open VS Code or terminal keeps its old PATH. In that PowerShell session, run `$env:Path += ";$env:LOCALAPPDATA\Mangekyo\bin"`, or restart VS Code or Windows Terminal before using the bare command:

```powershell
.\install-windows.cmd
mangekyo setup
mangekyo demo
mangekyo --tui
mangekyo dashboard
```

Stop and restart an older dashboard process after updating the executable. The dashboard header shows its active store path. A custom store must use the same `--home` argument for both commands, before the subcommand: `mangekyo --home PATH demo` and `mangekyo --home PATH dashboard`.

To run from Python source instead, use Python 3.11 or newer and install the package in a virtual environment:

```sh
python -m pip install -e ".[tui,evidence]"
mangekyo setup
mangekyo demo
mangekyo --tui
mangekyo dashboard
```

If Python and `prompt-toolkit` are already available, you can try this checkout without installing the package by replacing `mangekyo` with `python -m mangekyo` in those commands.

The demo prints a run ID and a snapshot ID. It records a deliberately wrong write in a disposable target under `.mangekyo/simulation/`. To correct and resume it from the CLI:

```sh
mangekyo show RUN_ID
mangekyo branch SNAPSHOT_ID -m fixed --replacement safe
mangekyo resume fixed
mangekyo benchmark RUN_ID
```

`mangekyo dashboard` opens a browser at `http://127.0.0.1:8765` and reads the same store as the CLI and terminal UI. `mangekyo --tui` opens an interactive history inspector; type `help` inside it for navigation and branch commands. `MANGEKYO_HOME` selects another store path. `MANGEKYO_REDACT` accepts comma-separated literal secrets that are replaced before event and snapshot objects are persisted.

The TUI header uses the approved Classic Scarlet Unicode banner: a clean split between `#FF343B` and `#BD0718`, with a red shadow. It shows the full one-line wordmark in terminals at least 153 columns wide, a purpose-drawn, legible compact wordmark in medium-width terminals, and a text title in smaller windows. Set `NO_COLOR` to display the Unicode art without colors.

## Inspect documents and annotate them

Attach the exact PDF or image an agent used, and optionally the text it extracted:

```sh
mangekyo evidence add RUN_ID path/to/document.pdf --event EVENT_ID --parsed-text-file path/to/extracted.txt
mangekyo dashboard
```

Open the item under **Evidence**, switch PDF pages, enter a note, and drag a rectangle over the page to save an annotation. The dashboard displays the original captured file, the agent supplied parsed text, and saved page coordinates. If no parsed text was supplied, it says so; it does not infer what the agent read. Your own agent can call `run.artifact("path/to/document.pdf", parsed_text=extracted_text)` inside `RunRecorder`.

For a web page, run `mangekyo setup --browser` once, then `mangekyo evidence capture RUN_ID https://example.com`. This optional adapter uses Playwright and Chromium to save a full-page screenshot and the page text. PDF pages are rendered locally with PDFium; Playwright is used for browser pages. Evidence files are stored locally and are capped at 50 MB.

The offline benchmark compares an actual corrected cold run with the recorded resumed branch. It reports local elapsed time and shared context objects. Its reference agent makes no model calls, so provider prompt-cache savings are **not measured** by that fixture.

To make two real OpenAI Responses requests using the first snapshot's unchanged context, explicitly run `mangekyo benchmark RUN_ID --openai-model MODEL` with `OPENAI_API_KEY` set. The command reports provider-returned cached and written token counts and elapsed time for both calls. The short reference context may be below the provider's cache threshold, so a cache hit is not guaranteed. Prices are not assumed; pass all four `--input-price`, `--cached-price`, `--cache-write-price`, and `--output-price` rates (USD per million tokens) for an estimated request cost.

## Record a launched agent automatically

Run an agent through Mangekyo to create a named run without changing the agent's code:

```powershell
mangekyo run -- python agent.py
mangekyo run --label "Review invoice 42" -- python agent.py
mangekyo log
```

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

For a project with a `.venv`, `mangekyo setup --project PATH` installs the SDK into that environment and verifies the import. This supported project path avoids a manually typed `pip` command, although setup invokes the project's package installer internally. A standalone build bundles the SDK wheel and does not need a package download for this step. It does not edit the agent's source code; add the recording calls where you want real execution events captured.

## Standalone distribution

The planned user-facing flow starts with downloading a standalone launcher or installer, then running `mangekyo setup`; users would not have to type a `pip` command. A Windows standalone executable has been built locally in `dist/`; it is not yet a published installer. To rebuild it, install this package with its `tui,evidence` extras plus PyInstaller, then run `python scripts/build_standalone.py`. The build embeds the SDK wheel for offline project connection. Playwright's Chromium browser is a separate optional download. PyInstaller builds for its host OS, so macOS and Linux artifacts still require separate builds and verification.

## Terminal banner

The terminal UI uses the **Classic Scarlet** two-tone red banner. The [copyable Unicode version](assets/terminal/mangekyo-agent-banner.txt), [true-color ANSI version](assets/terminal/mangekyo-agent-banner.ans), and [transparent PNG](assets/terminal/mangekyo-agent-banner.png) are available in `assets/terminal`.

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
