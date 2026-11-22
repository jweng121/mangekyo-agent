# Mangekyo Agent — first draft goals

**Target:** A local, runnable Python demo that records an agent failure, shows the context behind it, accepts a correction on a new branch, and resumes from a compatible checkpoint without repeating completed work. The draft must also measure whether snapshot reuse and provider prompt caching actually reduce rerun time and cost.

These goals define the complete first working draft from [FEATURES.md](FEATURES.md). We will agree on the goals before building the draft as one project. Each goal has a runnable acceptance check.

## Setup and usability target

The first useful result should require no manual Python or `pip` setup, account, API key, database server, Docker, browser extension, or edit to an existing agent. A user first downloads a Mangekyo installer or standalone launcher for their operating system. That bootstrap step puts `mangekyo` on the command path and bundles the runtime needed for the CLI and UIs. The proposed first commands are:

```text
mangekyo setup
mangekyo demo
mangekyo dashboard
```

`mangekyo setup` should initialize local storage with safe defaults and offer to connect a Python project. If a project needs the SDK, setup should detect its environment and package manager, show the changes it proposes, and handle the dependency installation; the user should not have to type a `pip` command. It should then provide one small, copyable instrumentation example. `mangekyo demo` should generate a real, deliberately failing local run and print the run ID, storage path, and next commands. The demo must work before the user chooses a model provider or runtime adapter.

After the demo, `mangekyo --tui` should open the terminal interface and `mangekyo dashboard` should open the web dashboard. Both should find the same run without additional setup.

## What Hermes Agent teaches us

- Hermes offers a short install-to-first-run path and puts advanced choices behind later commands such as `hermes model`, `hermes tools`, and `hermes setup`. Its fresh setup asks for the essential provider choice, then applies recommended defaults. For Mangekyo, the equivalent essential choice is **which Python project or run to capture**; the local demo needs no choice at all. [Hermes quickstart](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart)
- Hermes exposes one `hermes` command through a Python package entry point, while its CLI entry point, setup wizard, and configuration code live in separate modules. Its desktop bundles include Python and prebuilt interfaces, so users need not set up the runtime themselves. Mangekyo should similarly ship one discoverable `mangekyo` command with simple subcommands and a bundled runtime for the CLI and UIs, while keeping the SDK usable independently. [Hermes package entry point](https://github.com/NousResearch/hermes-agent/blob/main/pyproject.toml) · [installation](https://hermes-agent.nousresearch.com/docs/getting-started/installation) · [setup implementation](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/setup.py)
- Hermes keeps user settings in a known home directory, provides `config get/set/check`, and offers `doctor` for problems. Mangekyo should print its resolved store path, use safe defaults, and offer `mangekyo doctor` with specific fixes for installation, permissions, schema, and adapter compatibility. [Hermes configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) · [Hermes quickstart recovery toolkit](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart)
- Hermes separates the agent loop, tool dispatch, and SQLite persistence behind defined modules. Mangekyo should keep a compact event format and storage interface so the demo, CLI, UI, and future adapters read the same history. [Hermes architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- Hermes gateway hooks report lifecycle events such as `agent:start`, `agent:step`, and `agent:end`. Those hooks alone do not document the complete model inputs, tool results, or restorable state Mangekyo promises. A future Hermes integration must check the actual capture and checkpoint points before claiming full inspection or live resume support. [Hermes hook implementation](https://github.com/NousResearch/hermes-agent/blob/main/gateway/hooks.py)

These are usability and architecture references, not a plan to copy Hermes's broad agent feature set. Mangekyo is a local execution history and recovery tool that can instrument agents, not a replacement agent runtime.

## Goal 0 — Reach a useful result quickly

Distribute a launcher or installer that makes `mangekyo` available without asking the user to install Python or run `pip`. Package the CLI and SDK together. Make `mangekyo setup` idempotent and safe to rerun: detect an existing store and Python project, explain any file or dependency it will change, and preserve user configuration. Make `mangekyo demo` create and inspect a local example with no provider configuration. Use a default project-local store with an explicit path override. Add `mangekyo doctor` and concise help for every command. In a noninteractive shell, print the equivalent flags or environment variables instead of prompting.

**Done when:** On Windows, macOS, and Linux, a new user can install the launcher or app, run the three commands above, and open the example history without manually installing Python dependencies. The CLI prints the next useful command after each step. A failed setup reports the exact problem and a fix; rerunning `setup` preserves existing history and settings. Connecting a supported Python project does not require a manually typed `pip` command.

## Goal 1 — Capture and keep a real run

Build a small reference agent that fails predictably. Provide sync and async instrumentation for ordered model, tool, context, checkpoint, artifact, and error events. Store metadata in SQLite and larger objects by content hash. Apply configured redaction before writing data. Keep the basic SDK usable without a framework adapter or hosted service.

**Done when:** The example runs offline; after closing and reopening the process, its failure, preceding context, and event order are still readable. An interrupted write leaves previously committed snapshots readable.

## Goal 2 — Inspect and branch from the failure

Create immutable snapshot manifests and named branches. Implement the core CLI commands: `log`, `show`, `diff`, `branch`, and recorded `replay`. Use stable IDs and provide JSON output for inspection commands. Branch corrections must create new objects and preserve their parent history.

**Done when:** A developer can locate the failing step, inspect the context it used, branch from its checkpoint, apply a correction, and see a clear diff. Shared objects are stored once; integrity checks detect a damaged object.

## Goal 3 — Resume one supported agent safely

Define a runtime adapter contract and implement it for the reference agent. Save adapter and runtime versions with checkpoints, validate compatibility and pending side effects before execution, and record resumed events on the new branch. Keep recorded replay, context reconstruction, and live resume visibly distinct. Record each consequential action's intent, result, and idempotency or reconciliation status so a restart cannot silently execute it twice.

**Done when:** The reference agent completes after a correction without repeating eligible completed steps or duplicating an external action. An incompatible checkpoint stops before any new action and explains why.

## Goal 4 — Measure snapshot and model-context reuse

Build `mangekyo benchmark <run>` around a repeatable comparison of the same reference task from the beginning and from a compatible snapshot. Assemble model requests with unchanged instructions, tool definitions, approved memory, and preserved history in a stable prefix; put the branch correction and other changing context afterward. Store the exact request structure or a safe hash of each segment so a changed prefix is visible. Capture the provider's reported cached input tokens and cache-write tokens where available. Show separately: work skipped by resume, local snapshot objects shared, prompt-cache reads, new model tokens, tool calls, wall-clock time, and estimated cost. Never infer a provider cache hit from a matching local snapshot hash alone. [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) · [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

**Done when:** A benchmark report compares a full rerun with snapshot-based recovery under the same model and task settings, identifies each source of reuse, and reports actual provider cache usage or `not reported`. The offline demo can measure skipped steps and storage sharing; a provider-backed run is required before claiming model-context caching saved time or money.

## Goal 5 — Explore history in a terminal UI and web dashboard

Add `mangekyo --tui` for an interactive terminal view of runs, events, snapshots, evidence, branches, and diffs. Add `mangekyo dashboard` for a web dashboard bound to localhost by default, with a run list, execution timeline, snapshot and evidence inspector, branch creation, correction input, and branch comparison. Both interfaces must read and write the same local store as the CLI. Show Resume only for a compatible checkpoint, with a clear explanation when it is unavailable. Starting either interface should require no separate server configuration or account.

Use the supplied [Mangekyo Agent logo](mangekyo-agent-logo.png) as the dashboard wordmark and as the visual reference for the terminal interface's colors and title. Keep the original asset intact, scale it without distortion, and use readable text branding where the image cannot be displayed in a terminal or narrow layout.

**Done when:** A run created by `mangekyo demo` appears in the CLI, terminal UI, and web dashboard. A branch created in any one appears in the others, and the failure-to-resume demo and benchmark report can be followed in both UIs. The supplied logo is legible in the dashboard, and the terminal UI has a readable text equivalent. Missing evidence is labeled rather than reconstructed or implied.

## Goal 6 — Recover safely in a simulated action environment

Support a disposable, authorized simulation in the reference demo: capture the agent checkpoint and ask an environment adapter to identify and snapshot the simulated workspace before a consequential action. Record the action and its outcome. If the action leaves unwanted changes, offer an explicit branch from the earlier agent snapshot and restore the simulation environment only when the adapter confirms that its checkpoint is compatible. Agent context snapshots do not by themselves undo files, browser state, network effects, or external systems; show `context only` when no environment snapshot exists. Never retry an unresolved action automatically.

**Done when:** In a contained example, the reference agent changes a disposable target and then fails. A user can inspect the prior state, branch, restore the target through the adapter, apply a correction, and continue without repeating the consequential action. If environment restoration is unavailable, the interfaces explain what remains changed and do not present the agent snapshot as a rollback.

## First-draft release check

Provide one documented command sequence and one example agent for the full **failure → inspection → correction → resume** flow, including the disposable simulation and benchmark report. Also document the separate three-command first look, the `mangekyo --tui` entry point, and one minimal SDK integration example. Record time from install to first inspected run, steps reused, storage shared, provider-reported cache usage, wall-clock and cost comparisons, and duplicate external actions. The duplicate action count must be zero.

## Document evidence added to this draft

The dashboard now accepts captured PDF and image files tied to a run and optional event, shows the exact agent supplied parsed text, renders PDF pages locally, and stores rectangle annotations with normalized page coordinates. An optional Playwright and Chromium adapter captures a web page screenshot and extracted body text. The UI must label missing parsed text clearly. A broader browser action trace and automated element highlighting remain later work.

## Later goals

After the first draft, add general-purpose safe tool-result caching, optional browser screenshots and element evidence, and team hosting and review. These are specified in `FEATURES.md` but are not required for the initial runnable demo.
