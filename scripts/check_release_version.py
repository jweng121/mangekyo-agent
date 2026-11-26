"""Refuse a release tag that differs from the package being built."""

from __future__ import annotations

import argparse
import tomllib
from importlib.metadata import version
from pathlib import Path

from packaging.version import Version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Git tag, such as v0.2.0b1 or v0.2.0-beta.1")
    args = parser.parse_args()
    if not args.tag.startswith("v"):
        parser.error("Release tag must start with v")
    project = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    declared = Version(project["project"]["version"])
    installed = Version(version("mangekyo-agent"))
    tagged = Version(args.tag[1:])
    if declared != installed or declared != tagged:
        parser.error(f"Version mismatch: tag={tagged}, pyproject={declared}, installed={installed}")
    print(f"Release version verified: {args.tag} matches package {declared}")


if __name__ == "__main__":
    main()
