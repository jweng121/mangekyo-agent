"""Exercise the demo dashboard in a real browser, from source or a launcher."""

import argparse
import tempfile
import sys
import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mangekyo.demo import run_demo
from mangekyo.store import Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, help="Packaged Mangekyo executable to inspect")
    args = parser.parse_args()
    command = ([str(args.executable.resolve())] if args.executable
               else [sys.executable, "-m", "mangekyo"])
    with tempfile.TemporaryDirectory() as home:
        with Store(home) as store:
            demo = run_demo(store)
        subprocess.run(
            [*command, "--home", home, "branch",
             demo["snapshot_id"], "-m", "fixed", "--replacement", "safe"],
            capture_output=True, text=True, check=True, timeout=120,
        )
        subprocess.run(
            [*command, "--home", home, "resume", "fixed"],
            capture_output=True, text=True, check=True, timeout=120,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        process = subprocess.Popen(
            [*command, "--home", home,
             "dashboard", "--port", str(port), "--no-open"],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(200):
                if process.poll() is not None:
                    raise RuntimeError("Dashboard exited before serving")
                try:
                    with urllib.request.urlopen(base + "/api/runs", timeout=1):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("Dashboard did not start")
            inspect_browser(base, demo, home, command)
            print("Dashboard browser smoke passed: recovery, evidence, branch, and resume")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def inspect_browser(base: str, demo: dict, home: str, command: list[str]) -> None:
    with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            page.locator(".graph-node").first.wait_for()
            page.locator("#chat-toggle").click()
            page.locator("#chat-setup").wait_for(state="visible")
            assert "Connect a model" in page.locator("#chat-setup").inner_text()
            page.locator("#chat-close").click()
            capture_text = page.locator("#summary").inner_text()
            assert "Captured in this run" in capture_text
            assert "Model inputs missing" in capture_text
            assert "Restorable checkpoints candidate" in capture_text
            assert page.locator("#store-path").count() == 0
            assert page.locator(".brand-banner").evaluate("image => image.naturalWidth") > 0
            assert page.locator(".graph-node.corrected").count() > 0
            assert page.locator(".graph path.feedback").count() > 0
            assert "Steps skipped" in page.locator("#benchmark-summary").inner_text()
            assert "Not measured" in page.locator("#benchmark-summary").inner_text()
            page.locator("#measure-cold").click()
            page.locator("#measure-cold").wait_for(state="detached")
            assert "Recovery vs cold" in page.locator("#benchmark-summary").inner_text()
            assert "Not measured" not in page.locator("#benchmark-summary").inner_text()
            assert page.locator("#artifacts .item").count() == 2
            page.locator("#artifacts .item").first.click()
            page.locator("#evidence-image").wait_for()
            assert page.locator("#annotations .annotation").count() == 1
            for _ in range(100):
                if page.locator("#evidence-image").evaluate("image => image.naturalWidth") > 0:
                    break
                page.wait_for_timeout(100)
            else:
                raise AssertionError("PDF preview did not load")
            page.screenshot(path=str(Path(home) / "dashboard-smoke.png"), full_page=True)
            page.locator("#artifacts .item").nth(1).click()
            page.locator("#inspector h2").get_by_text("demo-target.png").wait_for()
            assert page.locator("#annotations .annotation").count() == 1
            assert "Current value: original" in page.locator("#inspector").inner_text()
            page.locator("#view-toggle").click()
            assert page.locator("#events .item").count() > 0
            page.locator("#view-toggle").click()
            page.locator('.graph-node[data-graph-event]').filter(
                has_text="checkpoint " + demo["snapshot_id"][:6]).first.click()
            page.locator("#create-branch").wait_for()
            page.locator("#branch-name").fill("second-fix")
            page.locator("#replacement").fill("safe")
            page.locator("#create-branch").click()
            page.locator('[data-branch="second-fix"]').click()
            cli_log = json.loads(subprocess.run(
                [*command, "--home", home, "log"],
                capture_output=True, text=True, check=True, timeout=120,
            ).stdout)
            assert any(branch["name"] == "second-fix" for branch in cli_log["branches"])
            page.locator("#resume").click()
            page.locator("#graph.playing").wait_for(state="attached")
            page.locator("#graph.success").wait_for()
            assert page.locator("#graph path.feedback").count() == 2
            with Store(home) as store:
                live_run = store.create_run("live-smoke-agent", "Live checkpoint smoke")
            page.locator(f'[data-run="{live_run}"]').wait_for(timeout=5000)
            page.locator(f'[data-run="{live_run}"]').click()
            page.locator("#live-indicator").get_by_text("Live", exact=False).wait_for(timeout=5000)
            with Store(home) as store:
                first_event = store.event(live_run, "tool", {"name": "read_schema", "result": ["bookings"]})
            page.locator(f'[data-graph-event="{first_event}"].fresh').wait_for(timeout=5000)
            page.locator(f'[data-graph-event="{first_event}"]').click()
            with Store(home) as store:
                checkpoint = store.snapshot(live_run, "after-read", {"schema": ["bookings"]})
                checkpoint_event = store.events(live_run)[-1]["id"]
            page.locator(f'[data-graph-event="{checkpoint_event}"].fresh').wait_for(timeout=5000)
            assert checkpoint[:6] in page.locator("#graph").inner_text()
            assert first_event in page.locator("#inspector").inner_text()
            with Store(home) as store:
                store.status(live_run, "completed")
            page.locator("#live-indicator").get_by_text("Live").wait_for(state="detached", timeout=5000)
            assert not errors, errors
            browser.close()


if __name__ == "__main__":
    main()
