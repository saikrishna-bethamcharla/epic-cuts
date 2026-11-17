# AutoCut

[![CI](https://github.com/saikrishna-bethamcharla/epic-cuts/actions/workflows/ci.yml/badge.svg)](https://github.com/saikrishna-bethamcharla/epic-cuts/actions/workflows/ci.yml)

Order a folder of numbered video clips by filename, cut out silence and pauses,
and hand the result to Premiere Pro, DaVinci Resolve, Final Cut Pro or a
rendered file.

The core is a **library** with a thin CLI on top. Editor panels (Premiere UXP,
Resolve, FCP) will talk to the same engine later; no UI code lives in the core.

> **Status: M0 (setup) and M1 (ordering) are complete.** `autocut doctor`,
> `autocut order` and `autocut run --dry-run` work. Silence detection (M2),
> rendering (M3) and timeline exports (M4) are not implemented yet, and
> `analyze`/`export`/`run` say so explicitly. See [Roadmap](#roadmap).

## Requirements

- Python 3.11 or newer (the project is developed on 3.12)
- FFmpeg and ffprobe on `PATH` — `autocut doctor` verifies both and lists the
  hardware encoders your build supports
- Windows, macOS or Linux

## Install

```bash
git clone git@github.com:saikrishna-bethamcharla/epic-cuts.git
cd epic-cuts
uv venv --python 3.12
uv pip install -e ".[dev]"      # or: pip install -e .
```

Run the environment check first:

```bash
autocut doctor
```

```
AutoCut 0.1.0
python: 3.12.16
platform: Windows 11 (AMD64)

ffmpeg: ffmpeg version 9.0.2-full_build-www.gyan.dev
    C:\tools\ffmpeg\bin\ffmpeg.exe
ffprobe: ffprobe version 9.0.2-full_build-www.gyan.dev
    C:\tools\ffmpeg\bin\ffprobe.exe

hardware encoders:
  h264_nvenc             NVENC H.264 (NVIDIA)
  hevc_nvenc             NVENC HEVC (NVIDIA)
  h264_qsv               Quick Sync H.264 (Intel)
  ...

status: ready
```

## Quick start

```bash
# What order will the clips be in? Nothing is processed or written.
autocut order ./footage

# Same report, plus both machine- and human-readable files in ./out
autocut run ./footage -o ./out --dry-run
```

```
AutoCut 0.1.0 - ordering report
inputs: footage
found:  6 clip(s), 0 ignored file(s)

  #  file                                   number        length  status
  1  01 - intro.mp4                        1             00:42.3  ok
  2  clip_2.mp4                            2             01:04.0  ok
  3  clip_2b.mp4                           2 (letter b)  00:51.7  ok
  4  clip_10.mov                           10            02:11.8  ok
  5  outro.mp4                             -             00:18.2  no-number
  6  notes.mp4                             -             00:03.1  unreadable

problems:
  no number   outro.mp4 (placed at the end)
  unreadable  notes.mp4: could not read media file ...: Invalid data found

summary: 6 clip(s), total source length 05:11.1, 1 unnumbered, 1 unreadable
hint: --strict aborts on these problems, --strict-warnings exits 1
```

`run` writes `ordering_report.txt` and `ordering.json` before any processing, so
the ordering decision is always reviewable and diffable.

## Commands

| Command | Purpose |
| --- | --- |
| `autocut doctor` | Check FFmpeg, ffprobe, versions and hardware encoders |
| `autocut order INPUT...` | Ordering report only |
| `autocut run INPUT... -o OUT` | Ordering, then analysis and export |
| `autocut analyze INPUT...` | Cut list JSON only (M2) |
| `autocut export CUTLIST.json --format xmeml\|fcpxml\|edl\|render` | Export (M3-M4) |

`INPUT` may be a folder, several folders, or explicit files. Folders are scanned
non-recursively unless `--recursive` is given. Hidden files and folders are
skipped, and non-media files are listed as ignored rather than silently dropped.

Key options: `--number-rule first|last|regex`, `--number-regex`,
`--recursive`, `--json-out`, `--config`, `--log-level`, `--strict`,
`--strict-warnings`, `--dry-run`.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Finished, but warnings were reported (`--strict-warnings`) |
| 2 | User input error (missing path, bad config, `--strict` abort) |
| 3 | Processing error (unreadable media, missing FFmpeg, unsupported request) |

## Ordering rules

The clip number is read from the filename with its known media extension removed
(`.mp4 .mov .mkv .avi .webm .mxf .m4v`, case-insensitive). A number token is
`digits` + optional `.fraction` + optional 1-2 letter suffix + optional `-sub`.

1. **Every number in the name is compared** by default (natural order), left to
   right, so `S01E01` comes before `S01E02` and `Scene2_Shot1` before
   `Scene2_Shot3`. `--number-rule first` uses only the first number,
   `--number-rule last` the last one, and
   `--number-rule regex --number-regex 'E(\d+)'` the capture group (a group named
   `number` is preferred when present).
2. Numbers are compared **numerically**, so `2` comes before `10`.
3. Sub-numbers sort after the bare number:
   `1 < 1a < 1b < 1.5 < 1-2 < 2`. Fractions are normalised, so `1.50` equals `1.5`.
4. Files with no number go **last, in natural alphabetical order**, and are
   reported. `--strict` aborts instead.
5. Gaps and duplicates are reported, never hidden. A duplicate means two files
   parse to the same number; the tie is broken alphabetically for determinism.

| # | Input files | Resulting order |
| --- | --- | --- |
| 1 | `1.mp4`, `2.mp4`, `10.mp4` | 1, 2, 10 |
| 2 | `10.mp4`, `2.mp4`, `1.mp4` | 1, 2, 10 |
| 3 | `01.mp4`, `02.mp4` | 01 (1), 02 (2) |
| 4 | `clip_2.mp4`, `clip_10.mp4` | clip_2, clip_10 |
| 5 | `Take 10.mov`, `Take 2.mov` | Take 2, Take 10 |
| 6 | `02 - intro.mp4`, `01 - intro.mp4` | 01, 02 |
| 7 | `Scene3_Shot12.mp4`, `Scene2_Shot1.mp4` | Scene2, Scene3 (first number) |
| 8 | `intro_part_2_final.mp4`, `intro_part_1_final.mp4` | part_1, part_2 |
| 9 | `1.mp4`, `1a.mp4`, `1b.mp4`, `1.5.mp4`, `1-2.mp4`, `2.mp4` | 1, 1a, 1b, 1.5, 1-2, 2 |
| 10 | `2.mp4`, `1.5.mp4`, `1b.mp4` | 1b, 1.5, 2 |
| 11 | `S01E02.mp4`, `S01E01.mp4` | S01E01, S01E02 (both numbers compared); `--number-rule first` would report a duplicate |
| 12 | `3.mp4`, `3b.mp4`, `4.mp4` | 3, 3b, 4 |
| 13 | `1.mp4`, `3.mp4` | 1, 3 with a **gap** at 2 |
| 14 | `intro.mp4`, `outro.mov`, `1.mp4` | 1, intro, outro (unnumbered last, alphabetical) |
| 15 | `1.5.mp4`, `1.50.mp4` | same number: duplicate reported, deterministic order |

Containers are confirmed by ffprobe, not by extension, and clips that cannot be
read are kept in the report and flagged so sequence gaps stay honest.

## Configuration

A single TOML file, overridden by any CLI flag:

```toml
[ordering]
number_rule = "natural"   # natural | first | last | regex
number_regex = ""         # required when number_rule = "regex"
recursive = false
unnumbered_policy = "end" # end | error

[run]
strict = false
strict_warnings = false

[log]
level = "info"            # debug | info | warning | error | critical
# file = "autocut.log"
```

Unknown keys are rejected, so a typo is an error instead of a silently ignored
setting. Named presets (`podcast`, `tutorial`, `vlog`, `aggressive`, `gentle`)
arrive with the detection settings in M5.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ffmpeg was not found on PATH` | Install FFmpeg and reopen the terminal; `autocut doctor` shows the resolved paths |
| `status: NOT READY` | Same as above — both `ffmpeg` and `ffprobe` are required |
| Clips are in the wrong order | Check the `number` column, then try `--number-rule last` or `--number-regex` |
| Everything is unreadable | The files may be corrupt or have no video stream; `doctor` plus a manual `ffprobe` on one file will tell you |
| Two clips swapped | They share a clip number (duplicate warning); rename one |
| `error: strict mode: ...` | `--strict` aborts by design; drop it to continue with warnings |

## Roadmap

| Milestone | State |
| --- | --- |
| M0 Setup: repo, tooling, CI, `doctor` | done |
| M1 Ordering: parser, report, `order`, `--dry-run` | done |
| M2 Detection: energy + VAD, post-processing, cache | next |
| M3 Cut list + FFmpeg renderer | planned |
| M4 Timeline exports: xmeml, FCPXML, EDL | planned |
| M5 Robustness, performance, presets, structured logs | planned |
| M6 Single-file executable, release workflow | planned |
| M7 Review UI | planned |
| M8 Premiere UXP panel | planned |

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers, data flow, extension points
- [docs/CUTLIST_SPEC.md](docs/CUTLIST_SPEC.md) — the Cut List data contract
- [docs/DECISIONS.md](docs/DECISIONS.md) — every non-obvious choice and why
- [docs/LICENSES.md](docs/LICENSES.md) — dependencies and compliance notes
- [docs/PLUGIN_PLAN.md](docs/PLUGIN_PLAN.md) — editor plugin plan
- [docs/MANUAL_QA.md](docs/MANUAL_QA.md) — import checklist for real NLEs

## Development

```bash
pytest                # tests (unit + integration)
pytest --cov          # with the coverage gate (85%)
ruff check .          # lint
ruff format .         # format
mypy                  # strict type check
```

Source media is never modified: every output goes to the folder you pass with
`-o`.
