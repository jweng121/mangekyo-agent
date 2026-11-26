"""Display the approved Classic Scarlet artwork in SIXEL-capable terminals."""

from __future__ import annotations

import os
import base64
from functools import lru_cache
from importlib.resources import files
from typing import Any


SINGLE_HEIGHT = 7
STACKED_HEIGHT = 14
SINGLE_WIDTHS = (640, 800, 960, 1120, 1280)
STACKED_WIDTHS = (480, 560)
KITTY_IMAGE_ID = 314159


def unicode_requested() -> bool:
    """Opt into the approximate character-cell artwork explicitly."""
    return os.environ.get("MANGEKYO_BANNER", "").lower() == "unicode"


def protocol() -> str | None:
    """Select the image protocol used by the active terminal."""
    mode = os.environ.get("MANGEKYO_BANNER", "").lower()
    if unicode_requested():
        return None
    if os.environ.get("TERM_PROGRAM", "").lower() == "vscode":
        return "kitty"
    if os.environ.get("WT_SESSION") or mode == "image":
        return "sixel"
    return None


def supported() -> bool:
    return protocol() is not None


@lru_cache(maxsize=7)
def _sixel(kind: str, width: int) -> str:
    name = f"classic-scarlet-two-layer-{kind}-{width}.sixel"
    return (files("mangekyo") / "assets" / name).read_bytes().decode("ascii")


@lru_cache(maxsize=2)
def _kitty_png(stacked: bool) -> str:
    kind = "stacked" if stacked else "single"
    name = f"classic-scarlet-two-layer-{kind}-crop.png"
    return base64.b64encode((files("mangekyo") / "assets" / name).read_bytes()).decode("ascii")


def _draw_kitty(output: Any, columns: int, stacked: bool) -> None:
    """Transmit the lossless approved PNG using the Kitty graphics protocol."""
    cell_width = min(columns - 2, 80 if stacked else 153)
    cell_height = min(STACKED_HEIGHT if stacked else SINGLE_HEIGHT,
                      max(1, round(cell_width / (5.69 if stacked else 20.48))))
    output.write_raw(f"\x1b_Ga=d,d=i,i={KITTY_IMAGE_ID},q=2\x1b\\")
    payload = _kitty_png(stacked)
    chunks = [payload[i:i + 4096] for i in range(0, len(payload), 4096)]
    for index, chunk in enumerate(chunks):
        first = f"a=T,f=100,t=d,i={KITTY_IMAGE_ID},q=2,c={cell_width},r={cell_height},C=1," if index == 0 else ""
        more = 1 if index < len(chunks) - 1 else 0
        output.write_raw(f"\x1b_G{first}m={more};{chunk}\x1b\\")


def draw(output: Any, columns: int, stacked: bool, *, top: int = 2) -> None:
    """Overlay the actual PNG pixels after prompt-toolkit draws its text grid."""
    # after_render also fires for prompt_toolkit's final redraw, after it has
    # restored the shell screen. Drawing then leaves the banner over the shell.
    from prompt_toolkit.application.current import get_app_or_none

    app = get_app_or_none()
    if app is not None and app.is_done:
        return
    if protocol() == "kitty":
        output.write_raw(f"\x1b7\x1b[{top};2H")
        _draw_kitty(output, columns, stacked)
        output.write_raw("\x1b8")
        output.flush()
        return
    widths = STACKED_WIDTHS if stacked else SINGLE_WIDTHS
    target = columns * 8
    width = max((value for value in widths if value <= target), default=widths[0])
    kind = "stacked" if stacked else "single"
    output.write_raw(f"\x1b7\x1b[{top};2H" + _sixel(kind, width) + "\x1b8")
    output.flush()
