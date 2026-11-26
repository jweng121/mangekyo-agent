# Browser target evidence example

This contained example serves a local invoice review page, records a decision
event, and captures the `#approve-invoice` button with Playwright. Mangekyo
saves the actual full-page screenshot, page URL, extracted body text, selector,
target coordinates, and an annotation around the button. The screenshot links
to the decision event in the same run.

Install the evidence extra and Chromium once, then run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[evidence]'
.\.venv\Scripts\python.exe -m mangekyo setup --browser
.\.venv\Scripts\python.exe scripts/run_browser_target.py
.\.venv\Scripts\python.exe -m mangekyo --home .mangekyo-browser-demo dashboard
```

Select **Inspect invoice approval target**, then select **Browser capture.png**
under Evidence. The marked button shows exactly which element was captured.
Select the `browser_observation` event in List view to inspect its URL,
selector, coordinates, and action result. The local server stops after capture;
the saved evidence remains available in the dashboard.

For your own run, use
`mangekyo evidence capture RUN_ID https://example.com --event EVENT_ID --selector '#target'`.
The selector is optional. If a target is missing, capture fails rather than
claiming to have observed it.

Use repeated `--mask-selector '#sensitive-region'` options to cover page regions
before saving a screenshot. A missing mask target fails the capture. When masks
are used, Mangekyo omits extracted page text and target text from the saved
evidence; the screenshot records the masked regions as black rectangles. Check
the resulting image before sharing it, since selectors cover only the regions
they match. `MANGEKYO_REDACT` disables browser capture entirely because literal
text replacement cannot erase pixels in an image.

The opt-in browser test is `python -m pytest tests/browser_target.py -q`.
