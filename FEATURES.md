# Mangekyo Agent — Product Requirements Document

**Status:** Draft for review  
**Version:** 0.1  
**Product:** Open-source, local-first execution history and recovery for AI agents

## 1. Product overview

Mangekyo Agent helps developers inspect and recover multistep AI agent runs.

It records what an agent saw, the context it used, the actions it took, and the state it reached. Developers can explore that history through a Git-like terminal interface or a local website inspired by GitHub Desktop. When an agent fails, they can inspect the relevant snapshot, create a branch, correct the problem, and resume if the agent’s runtime supports restoration.

**Core promise:** See what your agent saw. Find what went wrong. Correct it. Continue without repeating eligible work.

The CalHacks project informs visual evidence and investigation. Tranche informs durable execution and safe retry requirements. Mangekyo Agent will be built independently in `C:\Users\james\GitHub\mangekyo-agent`; neither existing project needs changes.

## 2. Users and problem

### Primary users

Developers building agents that perform long or consequential tasks, including browser agents, coding agents, research pipelines, and business workflow agents.

### Problem

A failure late in a run can leave a developer unable to answer:

- What exact context did the agent have?
- Which observation led to the wrong decision?
- Which steps completed successfully?
- Can the agent continue without repeating expensive work or external actions?

Logs can show events without enough context to reconstruct the decision. Rerunning from the beginning wastes time and may repeat side effects.

## 3. Product principles

1. **Faithful history:** Captured observations and outputs must come from the actual execution. Missing data is labeled.
2. **One store, two interfaces:** The website and CLI show the same runs, snapshots, and branches.
3. **Immutable snapshots:** Corrections create a branch; they never silently rewrite history.
4. **Honest recovery:** Recorded replay, context reconstruction, and live resumption are separate capabilities.
5. **Safe reuse:** A cache hit must never cause an unsafe external action to be skipped or duplicated.
6. **Local-first:** Initial capture and inspection work without a cloud account or external database.

## 4. Core workflow

1. A developer instruments an agent with Mangekyo’s SDK.
2. Mangekyo records model calls, tool actions, results, context changes, artifacts, and checkpoints.
3. The agent fails or makes a questionable decision.
4. The developer opens the run in the CLI or local website.
5. They inspect the relevant snapshot and compare it with earlier state.
6. They create a branch and provide a correction.
7. Mangekyo replays recorded history for inspection, or resumes execution through a compatible runtime adapter.
8. The developer compares the new branch with the original and sees what work was reused.

## 5. Feature requirements

### Feature A — Local setup and storage

**Goal:** A developer can get value without setting up infrastructure.

**Requirements**

- Provide an installer or standalone launcher that makes `mangekyo setup` available without requiring users to run `pip` or install Python for the CLI and local interfaces. Keep a Python SDK package for instrumented agents; `mangekyo setup` should handle its installation into a supported project environment after showing the proposed changes.
- Store metadata in local SQLite and large immutable objects in a content-addressed blob store.
- Keep run history readable after a process crash or interrupted write.
- Version the storage schema and support migrations.
- Make the storage location configurable.
- Redact configured secrets before persistence.

**Acceptance criteria:** A new project can record a run offline, close, reopen, and inspect the same history. An interrupted write does not corrupt earlier snapshots.

### Feature B — Agent instrumentation

**Goal:** Record a real execution with minimal changes to an agent.

**Requirements**

- Provide synchronous and asynchronous Python APIs.
- Capture run and agent IDs, event order, timestamps, model calls, messages, tool calls and results, errors, token usage, and artifact references.
- Provide explicit hooks for creating checkpoints.
- Preserve enough context to explain a decision while respecting redaction settings.
- Allow future framework adapters to produce the same event format.

**Acceptance criteria:** A reference agent produces an ordered trace containing its failing action and the context immediately before it.

### Feature C — Snapshots, branches, and diffs

**Goal:** Make agent context versionable without copying the full history at every step.

**Requirements**

- Represent each snapshot as an immutable manifest referencing context objects by hash.
- Store unchanged objects once and share them across snapshots and branches.
- Record parent relationships between snapshots.
- Support named checkpoints and branches.
- Compare instructions, messages, memory, tool results, artifacts, and runtime state.
- Verify object integrity when reading stored data.

**Acceptance criteria:** Branches with a shared history reuse the same stored objects. Changing one object produces a clear diff while leaving the parent snapshot intact.

### Feature D — Terminal interface

**Goal:** Let developers explore runs as naturally as they explore code history.

|Command|Purpose|
|---|---|
|`mangekyo log`|List runs, branches, and checkpoints|
|`mangekyo show <id>`|Inspect a run, event, or snapshot|
|`mangekyo diff <a> <b>`|Compare two snapshots|
|`mangekyo branch <snapshot> -m <name>`|Branch from a snapshot|
|`mangekyo replay <snapshot>`|Display recorded events without executing them|
|`mangekyo resume <branch>`|Resume through a compatible runtime adapter|
|`mangekyo cache stats`|Show measured storage and cache reuse|
|`mangekyo benchmark <run>`|Compare a full rerun with snapshot-based recovery and report measured reuse|
|`mangekyo --tui`|Open the terminal UI|
|`mangekyo dashboard`|Open the local web dashboard|

Commands should have stable identifiers, helpful errors, and JSON output where useful for scripts.

**Acceptance criteria:** A developer can locate a failed run, inspect it, branch, and compare the result entirely from the terminal.

### Feature E — Local website

**Goal:** Provide a visual, branch-oriented interface inspired by GitHub Desktop.

**Proposed layout**

- **Left panel:** Agents, runs, branches, search, and filters.
- **Center panel:** Execution timeline or branch graph with failures and checkpoints.
- **Right panel:** Selected snapshot’s context, model and tool activity, artifacts, and evidence.
- **Comparison view:** Original and corrected branches side by side.

**Requirements**

- Start with `mangekyo dashboard` and bind to localhost by default.
- Read and write the same local history as the CLI.
- Show copyable CLI commands for the selected snapshot.
- Let users inspect evidence directly from an event or decision.
- Support branch creation and correction input.
- Offer Resume only when a runtime adapter confirms the checkpoint is compatible.
- Keep long runs navigable through search, filtering, and incremental loading.

**Acceptance criteria:** A branch created in the CLI appears in the website, and one created in the website appears in `mangekyo log`.

### Feature F — Recovery and runtime adapters

**Goal:** Continue a supported agent from a real checkpoint.

Mangekyo must label three distinct operations:

- **Recorded replay:** Display saved events. No model or tool calls execute.
- **Context reconstruction:** Reassemble the recorded inputs at a snapshot. This does not restore hidden process state.
- **Live resume:** Restore a runtime-owned checkpoint and execute forward on a new branch.

**Requirements**

- Define an adapter contract for checkpointing, compatibility checks, restoration, and resumption.
- Ship one reference agent with a working resume path before claiming recovery support.
- Record adapter and runtime versions with each checkpoint.
- Check the environment and pending side effects before resuming.
- Keep an action ledger with intent, outcome, and idempotency or reconciliation status for consequential actions.
- Let a compatible environment adapter capture and restore a disposable simulation environment separately from the agent-context snapshot; label context-only recovery when environment restoration is unavailable.
- Record resumed work on a new branch.

**Acceptance criteria:** The reference agent fails after completing earlier steps, resumes, and finishes without repeating eligible completed work or duplicating an external action. An incompatible checkpoint fails before execution with a clear reason.

### Feature G — Caching and reuse

**Goal:** Save storage, time, and model cost without hiding what was reused.

**Requirements**

1. **Storage sharing:** Content-addressed snapshots store unchanged context once.
2. **Prompt-cache-aware construction:** Assemble model inputs with stable instructions, tool definitions, approved memory, and unchanged history first. Record actual cached-token usage reported by the provider.
3. **Benchmarking:** Compare a full rerun and snapshot-based recovery under the same task and model settings. Report skipped steps, shared local objects, provider-reported cache reads and writes, new tokens, tool calls, elapsed time, and estimated cost separately. Mark unavailable provider metrics as unreported rather than estimating cache hits from snapshot hashes.
4. **Tool-result caching (later):** Allow opt-in caching for eligible tools. Cache keys include the tool version, normalized inputs, relevant context, source version or freshness policy, and workspace scope.
5. Record why a result was reused or recomputed.
6. Never use a generic cache for payments, sent messages, writes, or other side effects. Those require adapter-specific idempotency and reconciliation.

**First-draft acceptance criteria:** The reference benchmark reports measured recovery time and cost against a full rerun, explains skipped steps and object sharing, and shows actual provider cache metrics when a provider reports them. An offline run does not claim provider cache savings. Later tool-result caching must show that a repeated eligible read reuses a validated result and changed or expired data causes a fresh read.

### Feature H — Evidence and visual capture

**Goal:** Show the observation behind an agent decision.

**Requirements**

- Support evidence references for tool text, files, screenshots, and structured fields.
- Offer an optional browser adapter that captures actual screenshots, page URL, target element, coordinates, and action result.
- Link evidence to the exact event and snapshot that used it.
- Make visual capture opt-in and apply redaction controls.

**Acceptance criteria:** A browser-agent example shows a real captured page and highlights the element used for a decision. Missing screenshots are identified as missing.

### Feature I — Team collaboration and self-hosting

**Goal:** Let teams share and review runs after the local product works.

**Requirements**

- Optional server ingestion and shared storage.
- Workspaces, authentication, and role-based access.
- Evidence-linked comments and review decisions.
- Audit logs for corrections and approvals.
- Preserve the local event format so agents do not need to be reinstrumented.

**Acceptance criteria:** Two authorized developers can inspect the same run from separate computers; users cannot access another workspace’s history.

## 6. First-draft scope and later work

The first draft will be built as one integrated project after its goals are agreed. It includes:

1. **Local foundation:** Installer or launcher, setup, storage, SDK, and a failing reference agent.
2. **Version history and recovery:** Snapshots, diffs, branches, an action ledger, one runtime adapter, and a disposable simulation environment adapter.
3. **Benchmarking:** Measured snapshot reuse and provider-reported prompt-cache usage against a full rerun.
4. **Interfaces:** CLI, terminal UI, and localhost web dashboard showing the same history and benchmark report.

Later work includes general tool-result caching, browser screenshot capture, and team collaboration. The first public release should demonstrate an actual **failure → inspection → correction → resume** flow and publish its measured benchmark.

## 7. v0.1 boundaries

- Resume support is specific to compatible runtime adapters.
- Mangekyo does not recreate hidden model state or guarantee provider cache hits.
- Agent-context snapshots do not roll back an external environment unless a compatible environment adapter supplies and restores a real checkpoint.
- Recorded replay does not execute tools.
- Side-effecting actions are not automatically cached.
- Local capture, CLI, and website do not require cloud services.
- Tranche and the CalHacks repositories remain separate.

## 8. Success measures

For the reference demo, measure:

- Time to capture a first run.
- Ability to locate the failing step and its evidence.
- Whether CLI and website show the same history.
- Physical storage saved through shared snapshot objects.
- Steps reused after recovery compared with a cold rerun.
- Actual provider cached tokens and cache writes, when reported.
- Recovery time and cost compared with a full rerun.
- Duplicate external actions after retry or recovery: **zero**.
