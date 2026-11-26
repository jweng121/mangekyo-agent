"""Check Linux installation, checksum rejection, and prior-install preservation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    if sys.platform != "linux":
        raise RuntimeError("Run this smoke check on Linux")
    root = Path(__file__).resolve().parents[1]
    binary = Path(sys.argv[1]).resolve()
    installer = root / "install-linux.sh"
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="mangekyo-linux-install-") as directory:
        work = Path(directory)
        bindir = work / "bin"
        bindir.mkdir()
        prior = bindir / "mangekyo"
        prior.write_text("#!/bin/sh\necho prior-install\n", encoding="utf-8")
        prior.chmod(0o755)
        original = prior.read_bytes()
        env = {**os.environ, "MANGEKYO_BIN_DIR": str(bindir)}

        def install(source: Path, checksum: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["bash", str(installer), str(source), checksum],
                                  cwd=work, env=env, text=True, capture_output=True,
                                  timeout=120)

        bad_hash = install(binary, "0" * 64)
        assert bad_hash.returncode != 0 and "SHA256 mismatch" in bad_hash.stderr
        assert prior.read_bytes() == original

        bad_setup_binary = work / "bad-setup"
        bad_setup_binary.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
        bad_setup_binary.chmod(0o755)
        bad_setup_hash = hashlib.sha256(bad_setup_binary.read_bytes()).hexdigest()
        bad_setup = install(bad_setup_binary, bad_setup_hash)
        assert bad_setup.returncode != 0
        assert prior.read_bytes() == original

        installed = install(binary, expected)
        assert installed.returncode == 0, installed.stderr
        assert prior.read_bytes() == binary.read_bytes()
        assert (work / ".mangekyo" / "history.sqlite3").is_file()
        demo = subprocess.run([str(prior), "demo"], cwd=work, env=env,
                              text=True, capture_output=True, check=True, timeout=120)
        result = json.JSONDecoder().raw_decode(demo.stdout)[0]
        assert result["run_id"]
        print(f"Linux installer smoke passed: checksum, setup preservation, and demo {result['run_id']}")


if __name__ == "__main__":
    main()
