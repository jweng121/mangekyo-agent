# Capture completeness and recovery safety

`mangekyo show RUN_ID` and the local dashboard report what was **saved in that
run**. The report checks process lifecycle, optional process output, model inputs
and outputs, tool calls and results, context snapshots, evidence, and runtime
backed checkpoints. `captured` means the relevant saved events contain that
field; `partial` means only some do; `missing` means none was saved. A missing
field does not prove the agent did not make such a call. The report ignores
capabilities advertised by `mangekyo add` because configuration is not proof
that tracing worked. Capture failures are shown separately when the child can
report them to the launcher. A saved tool-start callback without a matching
result appears as a captured call with a missing or partial result.

For a batch command that prints its decision, opt in to bounded output capture:

```sh
mangekyo run --capture-output -- python agent.py
mangekyo show RUN_ID
mangekyo check RUN_ID --case expected.json
```

`--capture-output` preserves live terminal output and saves up to 256 KB from
each of stdout and stderr as a `process_output` event. A check case must set
`"kind": "process_output"` and assert the exact `stdout` or `stderr` value.
Use this option only when those streams may be saved locally: they can contain
credentials or personal data. Output capture does not reveal internal model
inputs, tool arguments, or checkpoints. For those, use an adapter or the Python
recording API. A process-only run has no checkpoint to branch from.

## Live resume contract

Recorded replay and context inspection do not execute an agent. Live resume
requires an adapter that can restore its runtime checkpoint. The bundled
simulation restores a disposable file; the LangGraph adapter requires a
registered graph factory with `resume_safe = True`, a matching graph version,
an explicit `validate_checkpoint(context)` function, and a materialized
LangGraph checkpoint. `runtime_backed` in the capture report means the saved
checkpoint exists, **not** that it is currently safe to resume. Reading a
capture report does not import or execute the graph factory.
The resume operation checks compatibility and side effects again. The
simulation restores each branch into a new disposable target, leaving the
failed run's target available for another independent branch.

An adapter that can perform consequential actions must record a stable action
key and `intent` **before** dispatch, then `completed` only after confirming the
external outcome. An interrupted or failed intent has an unknown outcome until
the operator checks the external system. Mangekyo stops resume in that state
with a reconciliation reason. It also stops if a consequential action completed
after the selected checkpoint, if the original run is still active, if a
runtime checkpoint is missing, or if an adapter's environment validator finds
changed source data. The simulation checks that its disposable target still
matches the recorded action result before restoring it.

For LangGraph, `validate_checkpoint` must check every external source or state
on which the resumed path relies, using evidence saved at the checkpoint. A
missing validator stops resume. This is an adapter contract: Mangekyo can
enforce that the validator runs, but cannot independently prove an arbitrary
validator is comprehensive or discover unreported side effects.

Branch claiming is atomic across local processes and occurs before a resumed
action. A second caller cannot execute the same branch. Once a branch is
claimed, a crash or failure during resumed execution leaves its child run for
inspection; do not create a fresh branch or rerun an external action until its
outcome is reconciled. Mangekyo does not infer that an unreported tool call was
safe, nor does it automatically undo external side effects. Adapters must
provide their own environment validation and idempotency or reconciliation
logic for those systems.
