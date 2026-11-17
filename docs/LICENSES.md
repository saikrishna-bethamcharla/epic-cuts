# Dependencies and licensing

AutoCut is MIT licensed. This file records every dependency, why it is needed,
and what must be checked before commercial distribution.

## Runtime (installed)

| Dependency | Licence | Purpose |
| --- | --- | --- |
| Python 3.11+ | PSF-2.0 | Interpreter |
| `typer` | MIT | CLI |
| `click` | BSD-3-Clause | CLI engine under typer |
| `rich` | MIT | Terminal formatting used by typer |
| `shellingham` | ISC | Typer shell detection |
| `pydantic` | MIT | Validated settings |
| `pydantic-core` | MIT | Rust core of pydantic |
| `annotated-types` | MIT | Typing helpers used by pydantic |
| `typing-extensions` | PSF-2.0 | Backports for 3.11 |
| `typing-inspection` | MIT | pydantic introspection helper |
| `natsort` | MIT | Natural sort for unnumbered filenames |

## Development only

| Dependency | Licence | Purpose |
| --- | --- | --- |
| `pytest` | MIT | Test runner |
| `pytest-cov` | MIT | Coverage plugin |
| `coverage` | Apache-2.0 | Coverage measurement |
| `hypothesis` | MPL-2.0 | Property tests |
| `sortedcontainers` | Apache-2.0 | Hypothesis dependency |
| `ruff` | MIT | Lint + format |
| `mypy` | MIT | Strict type checking |
| `iniconfig`, `packaging`, `pluggy`, `colorama` | MIT / Apache-2.0 / MIT / BSD-3 | Tooling dependencies |

MPL-2.0 (hypothesis) and Apache-2.0 (coverage) are development-only and do not
affect the distributed package.

## External programs (not bundled)

| Program | Licence | Note |
| --- | --- | --- |
| FFmpeg / ffprobe | LGPL-2.1+ or GPL-2.0+/GPL-3.0, depending on the build | Invoked as a separate process, never linked |

AutoCut calls `ffmpeg`/`ffprobe` through the user's `PATH`, so no FFmpeg code is
redistributed. This is compatible with shipping AutoCut commercially even when
the user's FFmpeg build is GPL (the common `gyan.dev` full build is GPLv3).

**Before M6 packaging:** if an FFmpeg binary is bundled for a single-file
executable, that binary's licence governs the bundle. Options are (a) ship an
LGPL build with dynamic linking and the LGPL notice, or (b) ship a GPL build and
licence the whole bundle accordingly. Verify the exact build's `--enable-gpl`
flags and include the corresponding notices and source offer. Do not assume.

## Planned (not yet installed)

| Dependency | Licence | Milestone | Note |
| --- | --- | --- | --- |
| `numpy` | BSD-3-Clause | M2 | Audio analysis |
| `soundfile` | BSD-3-Clause | M2 | Reading extracted audio |
| `silero-vad` (ONNX) | MIT | M2 | Preferred VAD |
| `onnxruntime` | MIT | M2 | VAD inference; check wheel size for packaging |
| `webrtcvad` | MIT | M2 | Fallback VAD |
| `pyinstaller` or `nuitka` | GPL-2.0 with exception / Apache-2.0 | M6 | Single-file executable |
| `tauri` | MIT / Apache-2.0 | M7 | Optional review UI shell |

Silero VAD model weights and the ONNX runtime are the two items the brief flags
for verification (section 13); confirm the licence and the packaged size before
M2 ships them.
