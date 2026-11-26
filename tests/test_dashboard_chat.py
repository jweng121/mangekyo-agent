"""Dashboard project launch and chat work through real loopback HTTP routes."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

from mangekyo.sample_project import create_sample


ROOT = Path(__file__).resolve().parents[1]


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_dashboard_model_free_project_launch_and_chat(tmp_path):
    model_requests = []

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            model_requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            data = b'{"choices":[{"message":{"content":"Check the agent answer against expected.json."}}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    port = _port()
    home = tmp_path / "history"
    project = tmp_path / "agent"
    project.mkdir()
    (project / "agent.py").write_text("print('agent answer')\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    process = subprocess.Popen([sys.executable, "-m", "mangekyo", "--home", str(home),
                                "dashboard", "--port", str(port), "--no-open"],
                               cwd=ROOT, env=environment, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)

    def request(path, body=None):
        raw = None if body is None else json.dumps(body).encode()
        req = Request(f"http://127.0.0.1:{port}{path}", data=raw,
                      headers={"Content-Type": "application/json"} if raw else {})
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                assert request("/api/chat/model")["model"] is None
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.1)
        assert request("/api/project")["project"] is None
        connected = request("/api/project", {"path": str(project)})
        assert connected["launch"] == ["{python}", "agent.py"]
        request("/api/project/launch", {})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            runs = request("/api/runs")["runs"]
            if runs and runs[0]["status"] == "completed":
                break
            time.sleep(.1)
        assert runs and runs[0]["status"] == "completed"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#chat-toggle").click()
            page.locator("#chat-setup").wait_for(state="visible")
            page.locator("#chat-provider").select_option("local")
            page.locator("#chat-model").fill("fixture")
            page.locator("#chat-endpoint").fill(f"http://127.0.0.1:{model.server_port}/v1")
            page.locator("#chat-connect").click()
            page.locator("#chat-workspace").wait_for(state="visible")
            page.locator("#chat-run").select_option(runs[0]["id"])
            page.locator("#chat-input").fill("What happened?")
            page.locator("#chat-send").click()
            page.locator("#chat-messages").get_by_text("Check the agent answer").wait_for()
            assert not errors
            browser.close()
        assert request("/api/chat/model")["model"]["model"] == "fixture"
        answer = request("/api/chat", {"prompt": "What happened?", "run_id": runs[0]["id"]})
        assert answer["run_id"] == runs[0]["id"]
        assert len(request("/api/chat/sessions")["sessions"]) == 2
        assert "agent answer" in str(model_requests[-1])
    finally:
        process.terminate()
        process.wait(timeout=10)
        model.shutdown()
        model.server_close()


def test_dashboard_pdf_agent_correction_to_commit_and_future_fix(tmp_path):
    port = _port()
    home = tmp_path / "history"
    project = create_sample(tmp_path / "agent")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    environment["MANGEKYO_SQL_STEP_DELAY"] = "0"
    process = subprocess.Popen([sys.executable, "-m", "mangekyo", "--home", str(home),
                                "dashboard", "--port", str(port), "--no-open"],
                               cwd=ROOT, env=environment, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)

    def request(path, body=None):
        raw = None if body is None else json.dumps(body).encode()
        req = Request(f"http://127.0.0.1:{port}{path}", data=raw,
                      headers={"Content-Type": "application/json"} if raw else {})
        with urlopen(req, timeout=20) as response:
            return json.load(response)

    def wait_for_run(exclude=None):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            runs = request("/api/runs")["runs"]
            match = next((run for run in runs if run["id"] != exclude and
                          run["status"] == "completed"), None)
            if match:
                return match["id"]
            time.sleep(.1)
        raise AssertionError("Dashboard launch did not complete")

    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                request("/api/project")
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.1)
        request("/api/project", {"path": str(project)})
        request("/api/project/launch", {})
        source = wait_for_run()
        data = request("/api/run/" + source)
        assert data["artifacts"][0]["name"] == "booking-request.pdf"
        tool = next(event for event in data["events"] if event["kind"] == "tool" and
                    event["payload"].get("payload", {}).get("name") == "select_table")
        checkpoint = next(event for event in data["events"] if event["kind"] == "checkpoint" and
                          event["payload"].get("name") == "after-choose")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator(f'#runs [data-run="{source}"]').click()
            page.locator('#artifacts .item').first.click()
            page.locator('#inspector').get_by_text('Question: Count Toronto bookings').wait_for()
            page.locator('#check-run').click()
            page.locator('#notice').get_by_text('Check failed').wait_for()
            page.locator('#view-toggle').click()
            page.locator(f'#events [data-event="{tool["id"]}"]').click()
            page.locator('#check-file').fill('tool-expected.json')
            page.locator('#check-event').click()
            page.locator('#notice').get_by_text('Check failed').wait_for()
            page.locator('#mark-reason').fill('Selected invoices for bookings')
            page.locator('#mark-event').click()
            page.locator('#notice').get_by_text('verified').wait_for()
            page.locator(f'#events [data-event="{checkpoint["id"]}"]').click()
            page.locator('#branch-name').fill('dashboard-bookings')
            assert page.locator('#replacement').input_value() == 'selected_table=bookings'
            page.locator('#create-branch').click()
            page.locator('#resume').click()
            deadline = time.monotonic() + 20
            child = None
            while time.monotonic() < deadline:
                branches = request('/api/runs')['branches']
                child = next((branch['result_run'] for branch in branches
                              if branch['name'] == 'dashboard-bookings'), None)
                if child:
                    break
                time.sleep(.1)
            assert child
            page.locator('#summary').get_by_text(child).wait_for()
            page.locator('#check-file').fill('expected.json')
            page.locator('#check-run').click()
            page.locator('#notice').get_by_text('Check passed').wait_for()
            page.locator('#branches [data-branch="dashboard-bookings"]').click()
            page.locator('#commit-branch').click()
            page.locator('#notice').get_by_text('Committed dashboard-bookings').wait_for()
            model_path = project / "active-sql-model.json"
            model_path.write_text(json.dumps({"version": "v2", "table_for_bookings": "bookings"}),
                                  encoding="utf-8")
            page.locator('#project-launch').click()
            deadline = time.monotonic() + 25
            future = None
            while time.monotonic() < deadline:
                future = next((run['id'] for run in request('/api/runs')['runs']
                               if run['id'] not in {source, child} and run['status'] == 'completed'), None)
                if future:
                    break
                time.sleep(.1)
            assert future
            page.locator(f'#runs [data-run="{future}"]').click()
            page.locator('#check-run').click()
            page.locator('#notice').get_by_text('Check passed').wait_for()
            assert not errors
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
