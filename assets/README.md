# Mangekyo Agent brand assets

| Placement | Asset | Use |
| --- | --- | --- |
| Terminal UI | `terminal/mangekyo-agent-banner.png` | Approved one-line Classic Scarlet artwork. The TUI renders these pixels with SIXEL in Windows Terminal. |
| Terminal UI | `terminal/mangekyo-agent-banner-stacked.png` | MANGEKYO above AGENT, assembled from the same approved pixels for narrower terminals. |
| Terminal fallback | `terminal/mangekyo-agent-banner.ans` and `.txt` | Simplified Unicode approximations for terminals without image support. These do not reproduce the PNG outlines and extrusion. |
| Dashboard | `dashboard/mangekyo-logo.png` | Transparent red Mangekyo emblem in place of dashboard header text. |
| Original crow resource | `dashboard/mangekyo-crow.png` | Original transparent crow art with its original eye; packaged for the TUI at `mangekyo/assets/crow-tui-image.png`. |
| Optional dashboard crow concept | `dashboard/mangekyo-crow-sharingan.png` | Crow with a detailed Mangekyō eye. The TUI still uses its original crow asset. |
| GitHub | `github/mangekyo-agent-wordmark.png` | Transparent, full `MANGEKYO-AGENT` Classic Scarlet wordmark for the repository README or social preview. |

Classic Scarlet uses a clean two-tone split: upper red `#FF343B`, lower red `#BD0718`. The approved letter geometry and offset outline remain unchanged.

The installable package keeps only the media needed at runtime in `mangekyo/assets/`.
Dashboard HTML and JavaScript live in `mangekyo/static/`. Keep both directories
in the wheel when changing package data or the standalone build.
