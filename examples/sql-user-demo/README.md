# Interactive SQL agent walkthrough in the terminal UI

This local agent parses `booking-request.pdf`. Its initial model selects
`invoices` and answers `1` instead of the expected bookings count `3`.

Start Mangekyo from the repository root:

```text
.\.venv\Scripts\mangekyo.exe --home .test-tmp\sql-tui-manual --tui
```

In the TUI, type these commands. For `/event N`, use the number shown in the
timeline beside the event described. The inspector shows readable event details
and any checkpoint state; `/raw` toggles the full event data.

```text
/help
/add examples\sql-user-demo
/project
/launch
/run 1
/capture
/evidence
/check expected.json
/event N                  # select the tool event with name select_table
/check tool-expected.json selected
/mark Selected invoices for a bookings question
/event N                  # select the checkpoint named after-choose
/branch fix-bookings selected_table=bookings
/branches
/resume fix-bookings
/check expected.json
/commit fix-bookings
/quit
```

The `/capture` command reports what was actually recorded. `/evidence` shows the
agent's extracted PDF text. Selecting a
checkpoint shows `parsed_document_text` in its saved state. `/check` reports a
failed outcome without changing the run's completed execution status. The
tool-specific failed check makes the subsequent `/mark` verified. The branch
corrects this run only.

To fix future runs, change `table_for_bookings` to `bookings` in
`active-sql-model.json` with your editor or coding agent. Set its version to
`v2`. The TUI can stay open while you edit. Type `/launch` again, then `/run 1`
and `/check expected.json`. The new run should pass without a branch. The TUI
refreshes a run it launches while it executes; type `/refresh` for runs created
outside this TUI session.
