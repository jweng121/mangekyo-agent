"""Draw the approved perched crow at a small size inside the TUI info box."""

from __future__ import annotations

import base64
from functools import lru_cache
from importlib.resources import files
from typing import Any

from .banner_image import protocol

IMAGE_ID = 314160


@lru_cache(maxsize=1)
def _png_payload() -> str:
    path = files("mangekyo") / "assets" / "crow-tui-image.png"
    return base64.b64encode(path.read_bytes()).decode("ascii")


@lru_cache(maxsize=1)
def _sixel() -> str:
    path = files("mangekyo") / "assets" / "crow-tui-image.sixel"
    return path.read_bytes().decode("ascii")


def draw(output: Any, row: int) -> None:
    """Overlay the scaled original crow, leaving the TUI's text grid intact."""
    mode = protocol()
    if mode is None:
        return
    output.write_raw(f"\x1b7\x1b[{row};4H")
    if mode == "kitty":
        output.write_raw(f"\x1b_Ga=d,d=i,i={IMAGE_ID},q=2\x1b\\")
        data = _png_payload()
        chunks = [data[i:i+4096] for i in range(0,len(data),4096)]
        for index, chunk in enumerate(chunks):
            first = f"a=T,f=100,t=d,i={IMAGE_ID},q=2,c=22,r=12,C=1," if index == 0 else ""
            output.write_raw(f"\x1b_G{first}m={int(index < len(chunks)-1)};{chunk}\x1b\\")
    else:
        output.write_raw(_sixel())
    output.write_raw("\x1b8")
    output.flush()
