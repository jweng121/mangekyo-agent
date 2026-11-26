# Agent failure to model improvement

The local workflow separates execution status from task correctness. An agent can
finish normally and still fail an expected-outcome check. Mangekyo does not host
a model: a configured project supplies any training, evaluation, and activation
commands used by `push`.

## Try the contained SQL flow

Install the optional `langgraph` extra in the Python environment, then run the
public CLI workflow end to end:

```sh
python scripts/run_sql_cli_acceptance.py --home .mangekyo-sql-cli-demo
```

To watch checkpoints and branches appear while the agent runs, use two terminals
from this checkout. Start the dashboard first:

```powershell
.\.venv\Scripts\python.exe -m mangekyo --home .mangekyo-sql-cli-live dashboard
```

Then start a paced copy of the SQL workflow in the second terminal:

```powershell
.\.venv\Scripts\python.exe scripts\run_sql_cli_acceptance.py --home .mangekyo-sql-cli-live --step-delay 2
```

The dashboard checks for new events about once a second. The newest node pulses
while a run is active, and new nodes appear as they are recorded. A branch is a
correction created from a checkpoint; it appears when the workflow creates it,
then its child run grows as resume records events. The delay only slows this
local fixture for viewing. A process-only agent run will show launch and exit
events; internal checkpoints require an adapter or explicit recording.

The fixture agent chooses `invoices` for a bookings question. The script checks
the wrong output, forks after the table choice, corrects the table to
`bookings`, verifies the output, compares the fork with a cold corrected run,
commits the corrected snapshot, and invokes a local test model pipeline. The
pipeline creates and activates a versioned JSON lookup model after the
committed and one held-out case pass. No provider request is made; the reported
model dollar saving uses illustrative fixture usage and prices.

`add . --graph sql=module:factory` saves a graph factory in the project config
for later `resume` commands. The factory must expose `resume_safe = True` and a
callable `validate_checkpoint(context)` for `add` to report live resume. The contained CLI demo registers this factory and
executes the graph under `mangekyo run`, so its process events, graph calls,
checkpoints, and output share one run ID.

## CLI contract

```text
mangekyo add .
mangekyo run -- python agent.py
mangekyo log
mangekyo show RUN_ID
mangekyo check RUN_ID --case expected.json
mangekyo mark RUN_ID --event EVENT_ID --reason "Wrong table choice"
mangekyo branch RUN_ID --at SNAPSHOT_ID -m correction --correction-file fix.json
mangekyo resume correction
mangekyo diff RUN_ID correction
mangekyo commit correction
mangekyo push COMMIT_ID --project .
```

Run these commands from the agent project root. `add` creates
`.mangekyo-agent.json` and reports detected stack, capture mode, and available
capabilities. For a Python project declaring LangGraph, `run` starts an opt-in
Python adapter that observes standard LangChain chat-model and tool invocations
and LangGraph `invoke`/`ainvoke` outputs without edits to individual nodes.
Custom calls, streaming methods, and resumable checkpoints require explicit
integration. `run` records the selected integration and passes the project
config path to the child as `MANGEKYO_PROJECT_CONFIG`; if the child uses
`RunRecorder`, it attaches its events to the same run. For a custom Python
agent, `trace_call(run, "model", model_function)` and
`trace_tool_dispatcher(run, dispatcher)` capture calls at shared boundaries.

```python
from mangekyo import RunRecorder, Store, trace_call, trace_tool_dispatcher

with Store() as store, RunRecorder(store, "sql-agent", "Bookings question") as run:
    call_model = trace_call(run, "model", model_client.responses.create)
    call_tool = trace_tool_dispatcher(run, dispatch_tool)
    # The agent's normal loop calls call_model(...) and call_tool(name, args).
```
Live resume still requires a compatible runtime adapter. The current LangGraph
adapter expects a registered graph factory. It captures standard LangChain tool
callbacks automatically; custom tool calls inside graph nodes can still be
reported as `tool_items`.

The check case is a JSON object. By default its `expected` object is compared
against the latest `output` event payload, with partial object matching. To
check a tool decision, supply `kind: "tool"` or an `event_id`:

```json
{"kind":"tool","expected":{"name":"select_table","result":{"table":"bookings"}}}
```

`check` exits with code 0 for pass and 2 for failed outcome. It records an
`eval_result` event linked to the checked event and does not change the run's
execution status. `mark` records the developer's selected divergence as
`verified` only when a failed check targets that exact event; otherwise it is
`suspected`. `commit` requires a completed corrected branch, a corrected
snapshot, and a passing check. It saves an immutable commit in the local store.

## Trace import for other languages

Any language can write a versioned JSON trace and import it:

```sh
mangekyo ingest trace.json
```

The [Node example](../examples/node-sql-agent.js) demonstrates this through
the launcher without a Python SDK in the agent:

```sh
mangekyo run -- node examples/node-sql-agent.js
```

```json
{
  "schema_version": 1,
  "agent": "typescript-sql-agent",
  "label": "Bookings question",
  "status": "completed",
  "events": [
    {"kind": "tool", "payload": {"name": "list_tables", "result": ["bookings"]}},
    {"kind": "snapshot", "name": "after-discovery", "context": {"tables": ["bookings"]}},
    {"kind": "output", "payload": {"output": {"table": "bookings"}}}
  ]
}
```

Imported snapshots are inspectable but cannot be live-resumed without an
adapter that can restore the original runtime and its environment.
When `ingest` runs inside a child launched by `mangekyo run`, it attaches these
events to that process run through `MANGEKYO_RUN_ID`. A trace can also include
an explicit `run_id` while that run is still active.

## User-owned `push` pipeline

The project config must identify the existing local model with
`current_model.version` and `current_model.artifact`, and may contain
`push.trainer`, `push.evaluator`, and
`push.activator`, each an argument list for a local executable. Mangekyo sends
JSON on stdin and expects one JSON object on stdout. The trainer receives the
commit and current model and returns `model_version` plus a
`candidate_artifact` path inside the project. The evaluator receives that
candidate and returns `model_version`, `committed_case_passed`,
`held_out_passed`, and a positive `held_out_count`. After those checks pass,
the activator receives the same candidate and returns `active_version` and an
`active_artifact` path. Mangekyo verifies that the active artifact matches the
evaluated candidate and that the candidate differs from the previous local
model before updating `current_model` in the project config. A missing
pipeline, failed check, or unchanged model cannot be reported as an update.

These commands run with the project's permissions. The project owns the model,
trainer, evaluation logic, and any compute cost. The supplied fixture pipeline
is an example of the contract, not a general model trainer.
