"""A fresh doctor check must not silently create the store it diagnoses."""

from __future__ import annotations

import json
from pathlib import Path

from mangekyo.cli import main


def test_doctor_missing_store_has_fix_and_no_side_effect(tmp_path: Path, capsys) -> None:
    home = tmp_path / "missing"
    assert main(["--home", str(home), "doctor"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["schema"] == "missing"
    assert "mangekyo setup" in result["fix"]
    assert not home.exists()


def test_setup_rerun_preserves_run_and_doctor_reports_integrity(tmp_path: Path, capsys) -> None:
    home = tmp_path / "store"
    assert main(["--home", str(home), "setup"]) == 0
    capsys.readouterr()
    assert main(["--home", str(home), "demo"]) == 0
    demo = json.JSONDecoder().raw_decode(capsys.readouterr().out)[0]
    assert demo["store_path"] == str(home.resolve())
    assert main(["--home", str(home), "setup"]) == 0
    capsys.readouterr()
    assert main(["--home", str(home), "doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["store_exists"] is True
    assert report["database_integrity"] == "ok"
    assert report["runs"] == 1
    assert demo["run_id"]
