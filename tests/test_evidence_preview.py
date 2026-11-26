"""The public demo's bundled PDF must render in an evidence installation."""

from pathlib import Path

import pytest

from mangekyo.evidence import capture_url, render_pdf_page
from mangekyo.store import Store


def test_bundled_pdf_preview_renders_png():
    document = Path(__file__).resolve().parents[1] / "mangekyo" / "assets" / "demo-instruction.pdf"
    png, count = render_pdf_page(document.read_bytes(), 0)
    assert count == 1
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 1000


def test_literal_redaction_disables_pixel_capture_before_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGEKYO_REDACT", "private-token")
    with Store(tmp_path / "history") as store:
        run_id = store.create_run("browser", "sensitive page")
        with pytest.raises(ValueError, match="cannot remove screenshot pixels"):
            capture_url(store, run_id, "http://127.0.0.1:1/")
        assert store.events(run_id) == []
        assert store.artifacts(run_id) == []
