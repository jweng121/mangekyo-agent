# Linux standalone release

The local x64 Linux candidate was built on Ubuntu under WSL with Python 3.12 and PyInstaller. It has not been published. The build script writes the executable to `dist/linux/mangekyo`, separate from Windows build output.

From a Linux checkout, install the build locally:

```sh
python -m pip install -e '.[tui,evidence,langgraph]' pyinstaller
python scripts/build_standalone.py
hash=$(sha256sum dist/linux/mangekyo | cut -d ' ' -f 1)
bash install-linux.sh dist/linux/mangekyo "$hash"
~/.local/bin/mangekyo demo
```

`install-linux.sh` accepts a source executable and an optional expected SHA256. It stages the executable in the destination directory, runs `setup`, and replaces the existing installation only after setup succeeds. The destination defaults to `~/.local/bin` and can be set with `MANGEKYO_BIN_DIR` or `XDG_BIN_HOME`. Add that directory to `PATH` to run `mangekyo` by name.

Local verification on Ubuntu under WSL: `60 passed, 2 skipped` in the current source test suite. The executable rebuilt after the LangGraph resume safety fix passed packaged recovery, fresh-project SDK setup, real pseudo-terminal TUI smoke with the cold comparison visible, and real-browser dashboard smoke with Playwright Chromium. Its staged copy passed the installer smoke: bad checksum rejection, preservation of an existing installation when setup failed, then setup and demo. The staged SHA256 manifest passed `sha256sum -c`. This does not establish compatibility with other Linux distributions or architectures. macOS has not been built or tested.
