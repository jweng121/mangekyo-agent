# Mangekyo Agent

Mangekyo Agent records local Python agent runs, preserves the evidence and context behind a failure, and supports correction and resume when a compatible checkpoint is available.

## Install

Use Python 3.11 or newer. Install the CLI, terminal UI, and document evidence support:

```sh
python -m pip install "mangekyo-agent[tui,evidence]"
mangekyo setup
mangekyo demo
mangekyo --tui
mangekyo dashboard
```

The `langgraph` extra adds the optional LangGraph integration. The base `mangekyo-agent` package provides the recording SDK and core CLI without those optional dependencies. Standalone Windows and Linux launchers are also being prepared for users who do not want to install Python.

## Try recovery offline

`mangekyo demo` creates a disposable failed run and prints its run ID, checkpoint ID, and local store path. Use those IDs to inspect, correct, resume, and compare the run:

```sh
mangekyo show RUN_ID
mangekyo branch SNAPSHOT_ID -m fixed --replacement safe
mangekyo resume fixed
mangekyo benchmark RUN_ID
```

The demo needs no account, API key, model, or external service. It reports skipped steps and shared local snapshot objects. It does not claim provider prompt-cache savings without provider usage data.

## Record your own agent

```python
from mangekyo import RunRecorder, Store

with Store() as store, RunRecorder(store, "my-agent", "example task") as run:
    run.record("tool", name="read-file", result="observed value")
    run.checkpoint("before-next-step", runtime_state={"step": 2})
```

Generic recorded runs support inspection, diffs, and recorded replay. Live resume requires a compatible runtime adapter and a checkpoint that passes environment and side-effect checks. The bundled demo and documented LangGraph example provide supported recovery paths.

For the full walkthrough, model-backed cost measurements, platform status, and limitations, see the [project documentation](https://github.com/jweng121/mangekyo-agent/tree/main/docs) and [LangGraph evaluation](https://github.com/jweng121/mangekyo-agent/blob/main/docs/langgraph-evaluation.md).
