# Example workflow: diagnose and rerun an agent

Here’s an end-to-end example you can run from this repository. It uses the bundled simulation, so the branch **actually resumes execution**. The commands use `python -m mangekyo`; if you have a working installation, you can use `mangekyo` instead.

## 1. Set up and run the example

```powershell
python -m mangekyo setup
python -m mangekyo demo
```

The demo acts as an agent that reads an instruction PDF and an image of a target file, then mistakenly writes `unsafe` where the instruction says `safe`. The command prints a `run_id` and a `snapshot_id`. Copy both.

## 2. Diagnose the failed run

```powershell
$run = "PASTE_RUN_ID"
$snapshot = "PASTE_SNAPSHOT_ID"

python -m mangekyo show $run
python -m mangekyo dashboard
```

Leave the dashboard running and use a second terminal for later commands. In the dashboard, select the failed run. The snapshot track shows the reads, decision, checkpoint, write, and verification error. Select each PDF or image read to see the captured file, the text the agent parsed, and the highlighted region. Select the checkpoint to inspect the context saved just before the wrong write.

## 3. Create and execute a correction

```powershell
python -m mangekyo branch $snapshot -m fix-safe --replacement safe
python -m mangekyo resume fix-safe
```

`resume` restores the simulation at that checkpoint, applies the correction, executes the remaining step, and prints a **new run ID**. Refresh the dashboard: the corrected child run forks from the checkpoint, while the failed path remains available for comparison.

## 4. Check the result

```powershell
python -m mangekyo show NEW_RUN_ID
python -m mangekyo show fix-safe
python -m mangekyo benchmark $run
```

The new run should show a completed verification with `safe`. The benchmark reports the steps skipped by resuming from the checkpoint. In the dashboard, select the source run and use **Measure cold comparison** in the recovery summary to run the baseline once. The summary then shows shared context objects, branch time, and whether this small local run was faster or slower than the cold run. The offline fixture makes no model calls, so it cannot measure provider prompt-cache savings.

For your own Python agent, start with `python -m mangekyo setup --project C:\path\to\agent` and launch it with `python -m mangekyo run --label "Review invoice 42" -- python agent.py`. That records the process as a run. Capturing its internal reads, decisions, and checkpoints requires `RunRecorder` calls in the agent. **Live branch resume currently works for the bundled simulation adapter**; a real agent needs an adapter that can restore its execution context and environment.
