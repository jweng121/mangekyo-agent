"""The approved Classic Scarlet Unicode wordmark used in the README."""

from __future__ import annotations

import os
from importlib.resources import files

from prompt_toolkit.formatted_text import ANSI


_static = files("mangekyo") / "assets"
_plain = (_static / "terminal-banner.txt").read_text(encoding="utf-8")
_colored = (_static / "terminal-banner.ans").read_text(encoding="utf-8")
_stacked_plain = (_static / "terminal-banner-stacked.txt").read_text(encoding="utf-8")
_stacked_colored = (_static / "terminal-banner-stacked.ans").read_text(encoding="utf-8")
BANNER_LINES = tuple(_plain.splitlines())
BANNER_WIDTH = max(map(len, BANNER_LINES))
BANNER_HEIGHT = len(BANNER_LINES) + 1
STACKED_LINES = tuple(_stacked_plain.splitlines())
STACKED_WIDTH = max(map(len, STACKED_LINES))
STACKED_HEIGHT = len(STACKED_LINES) + 1


def fragments(stacked: bool = False) -> list[tuple[str, str]]:
    """Return the unmodified approved wordmark, with its original ANSI colors."""
    if "NO_COLOR" in os.environ:
        result = [("", _stacked_plain if stacked else _plain)]
    else:
        result = list(ANSI(_stacked_colored if stacked else _colored).__pt_formatted_text__())
    result.append(("class:subtitle", "  MANGEKYO AGENT  /  LOCAL EXECUTION HISTORY"))
    return result
