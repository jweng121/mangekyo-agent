# macOS standalone preparation

`install-macos.sh` stages a candidate executable in the chosen bin directory, verifies an optional SHA256 with `shasum -a 256`, runs `setup`, and replaces any existing installation only when setup succeeds. It defaults to `~/.local/bin`; set `MANGEKYO_BIN_DIR` or `XDG_BIN_HOME` for another destination.

The release workflow has a macOS job that runs source and wheel checks, builds `dist/darwin/mangekyo`, and runs packaged recovery and installer smoke checks. It has not run on a macOS runner. The installer behavior was checked with a mock executable on Ubuntu under WSL; this does not verify a macOS build.

No macOS release asset is published by the workflow. A native build, installer smoke, and an appropriate signing and distribution path must pass before a macOS download is offered.
