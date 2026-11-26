# PyPI package preparation

The local package name is `mangekyo-agent`, version `0.2.0b1`. The source archive and pure Python wheel are built from `pyproject.toml`. They include the Apache 2.0 license, `PYPI_README.md` as the PyPI description, the `mangekyo` command, the SDK, and bundled static demo assets. The base package supports the core CLI and SDK; install `mangekyo-agent[tui,evidence]` for the terminal UI, dashboard evidence previews, and browser capture, or add `langgraph` for that integration.

To prepare and check distributions locally:

```sh
python -m pip install build twine
python -m build --outdir release/pypi-candidate
python -m twine check release/pypi-candidate/*
python scripts/smoke_wheel.py --wheel release/pypi-candidate/mangekyo_agent-0.2.0b1-py3-none-any.whl
```

The local isolated build and metadata check passed on Windows. The built wheel and a second wheel rebuilt from the source archive each installed in a fresh environment and passed the offline failure, correction, resume, benchmark, bundle, and static asset smoke. Archive inspection found no `.env.local`, local history, audit, release, or distribution output. The package has not been uploaded to PyPI or TestPyPI.

The tag release workflow builds and checks the Python distributions separately. The GitHub release waits for those checks along with Windows, Linux, and macOS validation. Its PyPI job then waits for the GitHub release. It uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/) with a short lived OIDC credential instead of a stored API token. The account owner must register a [pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) for project `mangekyo-agent`, owner `jweng121`, repository `mangekyo-agent`, workflow filename `release-windows.yml`, and environment `pypi`. A pending publisher does not reserve the name; recheck name availability immediately before the first upload. The workflow has not run, and the publisher has not been configured through this checkout.

The package version must match the intended release tag. PyPI versions cannot be overwritten after upload, so a changed release requires a new version and tag. The user's no-push instruction keeps the local workflow dormant.
