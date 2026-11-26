# Fresh installation against an existing agent function

This local onboarding check used a new Windows Python virtual environment and a
wheel built from the current worktree. The agent decision came from
`tranche_client.workflow.choose_item` in the separate Tranche project. Its
source was not changed. A small entry script supplied a fixed, simulated
catalog and called that existing function; no service, provider key, or payment
was involved. The expected case deliberately asked for a different SKU to
exercise Mangekyo's outcome diagnosis. It is **not** evidence of a defect in
Tranche's selection logic.

1. Built the Mangekyo wheel, created a fresh `.venv`, and installed only that
   wheel into it. `mangekyo setup --project .` initially failed because a wheel
   installation has no source tree or embedded SDK wheel. Setup now accepts a
   matching Mangekyo package already installed in the project environment.
   A second fresh project environment was also connected from the CLI's local
   wheel without a package download.
2. `mangekyo add .` reported a Python boundary integration with no live resume.
   `mangekyo run --capture-output -- python agent_entry.py` recorded the
   process and `{"selected_sku": "webcam"}` output. Its run report correctly
   showed missing model calls, tool events, context, and checkpoints despite
   the project's advertised trace capability.
3. An entry wrapper added `RunRecorder` calls around the unchanged Tranche
   function. It saved the catalog result, a `before-selection` context snapshot,
   and the selected SKU as an `output` event. A JSON check expecting `mouse`
   failed even though execution exited normally; `mark` linked that failed
   check to the selected output event.
4. Branching from the snapshot succeeded for inspection. Live resume correctly
   refused because the snapshot uses the generic record-only adapter. The CLI
   previously printed a misleading `Next: mangekyo resume` after such a branch;
   it now states that a compatible runtime adapter is required.

The unmodified Tranche code supplied the decision function. Mangekyo captured
its process and printed result automatically only because the batch command
opted into output capture. The wrapper supplied tool, context, and output
events. No change to the Tranche library was needed; a full Tranche purchase
workflow and live resume were outside this offline check.
