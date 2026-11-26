"""Browser evidence links a real page, target, screenshot, and event."""

from __future__ import annotations

import threading
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
import pytest
from mangekyo.evidence import capture_url
from mangekyo.store import Store


def test_browser_target_is_captured_and_highlighted(tmp_path):
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            body = (b"<html><body><h1>Invoice review</h1><button id='approve'>Approve invoice</button>"
                    b"<div id='secret' style='position:absolute;left:10px;top:100px;width:100px;height:50px;background:red'>Top secret 123</div>"
                    b"</body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with Store(tmp_path / "history") as store:
            run_id = store.create_run("browser-agent", "Inspect a local invoice review page")
            decision = store.event(run_id, "decision", {"next_step": "inspect approval"})
            url = f"http://127.0.0.1:{server.server_port}/"
            artifact_id = capture_url(store, run_id, url, event_id=decision, selector="#approve")
            artifact = store.one("artifacts", artifact_id)
            assert artifact["event_id"] == decision
            assert artifact["source"] == url
            assert store.get_blob(artifact["blob_hash"]).startswith(b"\x89PNG\r\n\x1a\n")
            assert "Approve invoice" in store.get(artifact["parsed_hash"])["text"]
            annotations = store.annotations(artifact_id)
            assert len(annotations) == 1
            assert "Approve invoice" in annotations[0]["note"]
            assert 0 <= annotations[0]["x"] < 1
            assert 0 < annotations[0]["width"] <= 1
            observations = [event["payload"] for event in store.events(run_id)
                            if event["kind"] == "browser_observation"]
            assert len(observations) == 1
            assert observations[0]["url"] == url
            assert observations[0]["selector"] == "#approve"
            assert observations[0]["action_result"] == "target located"
            assert observations[0]["target"]["width"] > 0
            masked_id = capture_url(store, run_id, url, event_id=decision,
                                    selector="#approve", mask_selectors=("#secret",))
            masked = store.one("artifacts", masked_id)
            assert masked["parsed_hash"] is None
            with Image.open(io.BytesIO(store.get_blob(masked["blob_hash"]))) as image:
                assert image.convert("RGB").getpixel((20, 110)) == (0, 0, 0)
            masked_observation = [event["payload"] for event in store.events(run_id)
                                  if event["kind"] == "browser_observation"][-1]
            assert masked_observation["visual_masks"] == ["#secret"]
            assert masked_observation["parsed_text_omitted"] is True
            assert masked_observation["target"]["text"] == "[MASKED]"
            before = len(store.artifacts(run_id))
            with pytest.raises(ValueError, match="matched no elements"):
                capture_url(store, run_id, url, event_id=decision,
                            mask_selectors=("#missing-sensitive-region",))
            assert len(store.artifacts(run_id)) == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
