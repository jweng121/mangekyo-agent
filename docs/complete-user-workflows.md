# Try Mangekyo as a user

These three flows use the same contained PDF-backed SQL agent. The PDF asks for
the number of Toronto bookings. The agent initially selects `invoices` and
answers `1`; the correct table is `bookings`, with count `3`. Each flow creates
its own project and history so you can repeat it without changing the source
fixture.

Run the commands from the Mangekyo repository root. For a source checkout,
install the example's dependencies once with
`python -m pip install -e ".[tui,evidence,langgraph]"`. A packaged installation
needs the equivalent extras. The agent itself uses a deterministic fixture;
Chat requires your own debugging model. No debugging model is needed for the
inspector, run capture, dashboard timeline, or deterministic checks.

## Flow 1: Chat, then inspect and fix

1. In a terminal, create the isolated agent and open Chat:

   ```text
   mangekyo sample chat-sample
   mangekyo --home .mangekyo-chat-demo chat
   ```

2. On the first launch, the full-screen Chat interface opens its model setup.
   Use ↑↓ and Enter to choose OpenAI API, OpenRouter API, OpenRouter sign in,
   a local model, or a custom endpoint. Enter a model ID available to your
   account. For OpenRouter sign in, Mangekyo opens the authorization page;
   paste the code into the Chat input. API key input is hidden and saved in
   the OS credential store. Mangekyo tests the connection before opening
   Chat. If the test fails, choose a provider again on the same screen.
   Later Chat launches reuse the verified provider; `/model` changes it.

3. At the crow screen, enter the following commands one at a time:

   ```text
   /add chat-sample
   /launch
   /runs
   /run 1
   /capture
   /evidence
   ```

   `/add` connects the Python agent. `/launch` starts it from Mangekyo and
   opens the inspector. The run should finish with an answer from `invoices`.
   `/evidence` shows the extracted text from `booking-request.pdf`, including
   `Question: Count Toronto bookings`.

4. Return to Chat, attach the latest run, and ask about the mismatch:

   ```text
   /home
   /use 1
   Why did this agent answer 1 instead of 3? Cite the PDF and the table-selection event.
   Suggest a deterministic eval that would catch the wrong table.
   ```

   The answer should use the selected run's events, checkpoints, and parsed
   PDF text. It may suggest a check; its prose is not a pass/fail result.
   Press **Up** to restore the last submitted prompt. Repeated Up/Down moves
   through prompt history.

5. Run the actual checks and correction inside the inspector:

   ```text
   /runs
   /check expected.json
   /event N
   /check tool-expected.json selected
   /mark Selected invoices for a bookings question
   /event M
   /branch chat-bookings selected_table=bookings
   /resume chat-bookings
   /check expected.json
   /commit chat-bookings
   ```

   For `N`, use the number beside the `tool` event whose details name
   `select_table`. The tool check should **fail** and `/mark` should classify
   the divergence as verified. For `M`, use the number beside the `checkpoint`
   named `after-choose`. The resumed branch should answer `3`; its check should
   **pass** before the commit. Use `/raw` if you need the complete event JSON.

6. Fix future runs by opening `chat-sample/active-sql-model.json` in your editor
   and changing it to:

   ```json
   {"version": "v2", "table_for_bookings": "bookings"}
   ```

   Back in Chat, enter `/launch`, then `/run 1` and `/check expected.json`.
   The fresh run should answer `3` and pass without a branch. This file edit
   changes the agent's future behavior; the branch corrected only one run.

## Flow 2: Terminal inspector without a model

1. Create another isolated agent and open the inspector directly:

   ```text
   mangekyo sample tui-sample
   mangekyo --home .mangekyo-tui-demo --tui
   ```

   There is no model or sign-in prompt. `mangekyo setup` is not required.

2. In the inspector command field, enter:

   ```text
   /add tui-sample
   /launch
   /run 1
   /capture
   /evidence
   /check expected.json
   ```

   You should see the PDF's extracted question and a failed expected-output
   check. **Up/Down** recalls submitted commands. **Ctrl-P/Ctrl-N** moves
   between events; `/event N` selects an event by its timeline number.

3. Select the `select_table` tool event and the `after-choose` checkpoint from
   the timeline, substituting their displayed numbers for `N` and `M`:

   ```text
   /event N
   /check tool-expected.json selected
   /mark Selected invoices for a bookings question
   /event M
   /branch tui-bookings selected_table=bookings
   /resume tui-bookings
   /check expected.json
   /commit tui-bookings
   ```

   The tool check fails, the mark becomes verified, and the resumed branch
   passes the output check. The branch commit saves that passing correction.

4. Edit `tui-sample/active-sql-model.json` to
   `{"version":"v2","table_for_bookings":"bookings"}`. Return to the
   inspector and enter `/launch`, `/run 1`, `/check expected.json`. The new
   source run should pass. Enter `/quit` to leave the inspector.

## Flow 3: Dashboard, including browser Chat

1. Create a third isolated agent and open the dashboard:

   ```text
   mangekyo sample dashboard-sample
   mangekyo --home .mangekyo-dashboard-demo dashboard
   ```

   The browser opens on the local dashboard. The timeline, PDF evidence, and
   checks work even if no debugging model is connected.

2. In **Agent project**, enter `dashboard-sample` as the project folder, click
   **Connect agent**, then **Launch run**. The run appears in **Runs and
   branches** and updates as the agent executes. Select it. The execution
   summary should show a completed process; its output uses `invoices`.

3. Under **Evidence**, open `booking-request.pdf`. The inspector shows the PDF
   preview and the text the agent parsed. The text should say
   `Question: Count Toronto bookings`.

4. Optionally click **Chat**. On a fresh store, the Chat panel asks for a
   provider, model ID, and key or local endpoint. Select **OpenRouter** and
   **Sign in with OpenRouter** for the official browser authorization flow, or
   use an API key or local endpoint and click **Save and test connection**.
   Once connected, choose the run in the **Run** picker and ask:

   ```text
   Why did this run choose invoices when the PDF asked for bookings?
   Suggest an eval for the table-selection event.
   ```

   The conversation is saved in the same local history used by terminal Chat.
   Closing Chat leaves the run inspector available. If you do not have a
   debugging model, skip this step and continue with deterministic checks.

5. In the right-hand inspector controls, leave **Expected case file** as
   `expected.json` and click **Check run**. It should report **failed**.
   Click **List view** on the timeline, select the `tool` event with
   `select_table` in its details, change the case file to
   `tool-expected.json`, and click **Check selected event**. That check should
   also fail. Enter `Selected invoices for a bookings question` in the reason
   field and click **Mark event**. The notice should say **verified**.

6. Select the `checkpoint` event named `after-choose`. Enter a unique branch
   name such as `dashboard-bookings`, leave the correction
   `selected_table=bookings`, and click **Create branch**. In the branch view,
   click **Resume corrected branch**. Select the new run, change the case file
   back to `expected.json`, and click **Check run**. It should pass. Select
   `dashboard-bookings` under **Branches**, then click **Commit passing
   correction**.

7. Edit `dashboard-sample/active-sql-model.json` to
   `{"version":"v2","table_for_bookings":"bookings"}`. Click **Launch run**
   again, select the newest run, and click **Check run** with `expected.json`.
   The new run should pass without using a branch. Stop the dashboard with
   Ctrl-C in the terminal that launched it.

The terminal Chat and dashboard Chat share a model and conversations only when
they use the same `--home` path. These three flows intentionally use separate
paths so each begins with a fresh failing run.
