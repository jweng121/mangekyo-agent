"""Classic Scarlet Unicode wordmark for the terminal history inspector."""

from __future__ import annotations

import os
from importlib.resources import files


BANNER_LINES = tuple(
    (files("mangekyo") / "static" / "terminal-banner.txt")
    .read_text(encoding="utf-8")
    .splitlines()
)
BANNER_WIDTH = max(map(len, BANNER_LINES))
BANNER_HEIGHT = len(BANNER_LINES) + 1

# The compact art is drawn from complete glyphs. Slicing BANNER_LINES[::2]
# removes strokes and merges the letter faces with their shadow.
_GLYPHS = {
    "M": ("#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "G": (".####", "#....", "#....", "#.###", "#...#", "#...#", ".###."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
}


def _compact_lines() -> tuple[str, ...]:
    word = "MANGEKYO-AGENT"
    pixels = [[] for _ in range(7)]
    for index, letter in enumerate(word):
        for y, pattern in enumerate(_GLYPHS[letter]):
            pixels[y].extend(ch == "#" for ch in pattern)
            if index < len(word) - 1:
                pixels[y].append(False)

    width = len(pixels[0])
    face = []
    for y in range(4):
        line = []
        for x in range(width):
            upper = pixels[2 * y][x] if 2 * y < 7 else False
            lower = pixels[2 * y + 1][x] if 2 * y + 1 < 7 else False
            line.append("█" if upper and lower else "▀" if upper else "▄" if lower else " ")
        face.append(line)

    canvas = [[" " for _ in range(width + 2)] for _ in range(6)]
    for offset, char in ((2, "░"), (1, "▓")):
        for y, line in enumerate(face):
            for x, cell in enumerate(line):
                if cell != " ":
                    canvas[y + offset][x + offset] = char
    for y, line in enumerate(face):
        for x, cell in enumerate(line):
            if cell != " ":
                canvas[y][x] = cell
    return tuple("".join(line).rstrip() for line in canvas)


COMPACT_LINES = _compact_lines()
COMPACT_WIDTH = max(map(len, COMPACT_LINES))
COMPACT_HEIGHT = len(COMPACT_LINES) + 1

TOP_RED = "#FF343B"
BOTTOM_RED = "#BD0718"
SHADOW_RED = "#C43A44"
EXTRUSION_RED = "#87202C"
OUTLINE_RED = "#E44750"


def fragments(compact: bool = False) -> list[tuple[str, str]]:
    """Return prompt-toolkit fragments of the full or compact wordmark."""
    color = "NO_COLOR" not in os.environ
    result: list[tuple[str, str]] = []
    lines = COMPACT_LINES if compact else BANNER_LINES
    split = 2 if compact else 3

    for row, line in enumerate(lines):
        for character in line:
            if character in "█▀▄":
                style = f"fg:{TOP_RED if row < split else BOTTOM_RED}" if color else ""
            elif character == "▓":
                style = f"fg:{EXTRUSION_RED}" if color else ""
            elif character == "░":
                style = f"fg:{OUTLINE_RED if compact else SHADOW_RED}" if color else ""
            else:
                style = ""
            if result and result[-1][0] == style:
                previous_style, previous_text = result[-1]
                result[-1] = (previous_style, previous_text + character)
            else:
                result.append((style, character))
        result.append(("", "\n"))

    result.append(("class:subtitle", "  MANGEKYO AGENT  /  LOCAL EXECUTION HISTORY"))
    return result
