# AutoCut

[![CI](https://github.com/saikrishna-bethamcharla/epic-cuts/actions/workflows/ci.yml/badge.svg)](https://github.com/saikrishna-bethamcharla/epic-cuts/actions/workflows/ci.yml)

Order a folder of numbered video clips by filename, cut out silence and pauses,
and hand the result to Premiere Pro, DaVinci Resolve, Final Cut Pro or a
rendered file.

The core is a **library** with a thin CLI on top. Editor panels (Premiere UXP,
Resolve, FCP) will talk to the same engine later; no UI code lives in the core.

> **Status: M0-M4 are complete.** `autocut doctor`, `order`, `analyze`, `run`
> and `export` work end to end: numbered clips are ordered, silence is removed,
> the Cut List is written, and the result is either rendered to one file or
> exported as an xmeml, FCPXML or EDL timeline. See [Roadmap](#roadmap).

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
| `autocut presets` | List the built-in workflow presets |
| `autocut order INPUT...` | Ordering report only |
| `autocut run INPUT... -o OUT` | Order, analyse, write the Cut List and render `OUT/autocut.mp4` |
| `autocut analyze INPUT...` | Detect silences and write the Cut List JSON only |
| `autocut export CUTLIST.json --format xmeml\|fcpxml\|edl\|render` | Export a saved Cut List as a timeline or video |

`INPUT` may be a folder, several folders, or explicit files. Folders are scanned
non-recursively unless `--recursive` is given. Hidden files and folders are
skipped, and non-media files are listed as ignored rather than silently dropped.

Key options: `--number-rule first|last|regex`, `--number-regex`,
`--recursive`, `--json-out`, `--config`, `--profile`, `--log-level`, `--log-json`,
`--strict`, `--strict-warnings`, `--dry-run`, `--render/--no-render`, `--codec`,
`--crf`, `--preset`, `--encoder`, `--hardware/--no-hardware`, `--crossfade-ms`.
`--preset` is the encoder speed preset; `--profile` is the workflow preset below.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Finished, but warnings were reported (`--strict-warnings`) |
| 2 | User input error (missing path, bad config, `--strict` abort) |
| 3 | Processing error (unreadable media, missing FFmpeg, unsupported request) |

## Presets

`--profile NAME`, or `profile = "NAME"` at the top of the config file, applies a
starting point for detection and render settings:

| Profile | Best for | What it changes |
| --- | --- | --- |
| `podcast` | Interviews, two-person shows | VAD, 0.45 s silences, longer tail padding, CRF 20 |
| `tutorial` | Screen recordings, walkthroughs | VAD, 0.8 s silences, keeps pauses followable, CRF 20 |
| `vlog` | Handheld footage with a music bed | Energy detector, -32 dBFS, 0.4 s silences |
| `aggressive` | Short-form, maximum removal | Energy, -30 dBFS, 0.25 s, shortest pads, CRF 22 |
| `gentle` | A conservative first pass | VAD, 1.0 s silences, 0.3 s / 0.5 s pads |

A preset is a set of values, not a mode. Precedence, strongest last: built-in
defaults, the preset, the config file, explicit CLI flags. So
`--profile podcast --pad-after 0.6` keeps the podcast starting point and extends
the tail, and a `[analysis]` value in the config file still beats the preset when
`--profile` is passed. `autocut presets` prints the same list, and the chosen
profile is recorded in the Cut List's `settings.profile`.

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

## Detection

Two detectors behind one interface, both returning *keep* segments:

| Detector | Needs | Character |
| --- | --- | --- |
| `vad` (default) | `vad` extra (`onnxruntime`, `numpy`); Silero VAD v5 model ships with the package | Accurate on speech, catches short pauses |
| `energy` | only ffmpeg | Fast, no heavy dependencies, only removes longer silences |

```bash
uv pip install -e ".[vad]"      # enable the VAD detector
autocut analyze ./footage -o cutlist.json                       # Silero VAD
autocut analyze ./footage -o cutlist.json --detector energy     # ffmpeg only
```

Shared post-processing runs in a fixed order: merge gaps shorter than
`--min-silence`, drop speech shorter than `--min-speech`, pad with
`--pad-before`/`--pad-after`, optionally cap pauses
(`--shrink-pauses-to 0.3`), then optionally `--trim-head-tail`. Head and tail
silence is kept unless you ask for it.

Clips without audio, or entirely silent ones, follow `--no-audio-policy`
(`keep`, `skip`, `error`) and the reason is attached to the clip's warnings.

Analysis is cached by file fingerprint + detector + version + settings, so a
second run is effectively instant (`--no-cache` to bypass, `--cache-dir` to
move it, `--full-hash` for content identity instead of the fast fingerprint).
`--jobs N` analyses clips in parallel processes, and one broken clip never stops
the batch unless `--strict`.

## Rendering and timeline export

`autocut run` writes `OUT/autocut.mp4` as well as `cutlist.json`. Pass
`--no-render` to stop after the Cut List, or `--dry-run` to stop before analysis.
A Cut List written earlier can be exported again at any time:

```bash
autocut export out/cutlist.json --format edl -o out/assembly.edl
autocut export out/cutlist.json --format xmeml -o out/assembly.xml
autocut export out/cutlist.json --format fcpxml -o out/assembly.fcpxml
autocut export out/cutlist.json -o out/again.mp4        # format from the extension
```

| Format | Target | Notes |
| --- | --- | --- |
| `render` | any player | Frame-accurate `trim`/`concat`; one re-encode pass |
| `xmeml` | Premiere Pro, DaVinci Resolve | FCP7 XML, native in/out per source |
| `fcpxml` | Final Cut Pro, Resolve | FCPXML 1.10, rational time values |
| `edl` | All three | CMX 3600; drop-frame at 29.97/59.94 by default |

`--format` is inferred from the output extension when omitted. Every exporter
refuses a Cut List that is newer than this build and validates the frame
invariants first, so a hand-edited file cannot silently produce a broken
timeline.

The renderer rebuilds the timeline with FFmpeg's `trim`/`atrim` and `concat`
filters, using integer source frames rather than seek seconds, so cuts land on
exactly the frame the Cut List records. Sources are conformed to the sequence
resolution and rate, and audio joins get a 10 ms fade (`--crossfade-ms`) to avoid
clicks. Hardware encoders are used when `autocut doctor` lists them and fall
back to `libx264` if the GPU rejects the encode. The EDL is single-rate by
definition, so mixed-rate clips are conformed into the sequence's timecode;
xmeml and FCPXML keep each clip's native frame positions.

Use `--codec`, `--crf`, `--preset` and `--audio-bitrate` for quality, or
`--encoder h264_nvenc` to force one encoder. Render progress is printed at 10%
steps.

## Configuration

A single TOML file, overridden by any CLI flag:

```toml
# profile = "podcast"      # optional workflow preset; --profile wins over this

[ordering]
number_rule = "natural"   # natural | first | last | regex
number_regex = ""         # required when number_rule = "regex"
recursive = false
unnumbered_policy = "end" # end | error

[analysis]
detector = "vad"          # vad | energy
threshold_db = -35.0      # energy threshold, dBFS
min_silence = 0.5         # ignore pauses shorter than this
min_speech = 0.15         # drop speech shorter than this
speech_probability = 0.5  # VAD threshold per 32 ms frame
pad_before = 0.18         # tuned in DECISIONS D26
pad_after = 0.28
trim_head_tail = false
no_audio_policy = "keep"  # keep | skip | error

[render]
codec = "libx264"         # libx264 | libx265 | prores_ks | hardware encoder
crf = 18                  # quality; lower is better
audio_bitrate = "192k"
preset = "medium"
crossfade_ms = 10          # audio fade at every join
hardware = true            # try hardware encoders, fall back to software
faststart = true           # +faststart for MP4/MOV
# encoder = "h264_nvenc"   # force one encoder

[export]
# edl_drop_frame = true    # default: on at 29.97/59.94, off otherwise
# title = "Episode 12"

[run]
strict = false
strict_warnings = false
jobs = 0                  # 0 = one worker per core
full_hash = false

[cache]
enabled = true
# directory = "D:/autocut-cache"

[log]
level = "info"            # debug | info | warning | error | critical
format = "text"           # text | json (one JSON object per line)
# file = "autocut.log"
```

Unknown keys are rejected, so a typo is an error instead of a silently ignored
setting. `--log-json` switches to JSON Lines for a log collector; every record
carries `ts`, `level`, `logger`, `message` and stage fields such as `clips`,
`cuts` and `removed_percent`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ffmpeg was not found on PATH` | Install FFmpeg and reopen the terminal; `autocut doctor` shows the resolved paths |
| `status: NOT READY` | Same as above — both `ffmpeg` and `ffprobe` are required |
| Clips are in the wrong order | Check the `number` column, then try `--number-rule last` or `--number-regex` |
| Everything is unreadable | The files may be corrupt or have no video stream; `doctor` plus a manual `ffprobe` on one file will tell you |
| Two clips swapped | They share a clip number (duplicate warning); rename one |
| `error: strict mode: ...` | `--strict` aborts by design; drop it to continue with warnings |
| `the VAD detector needs onnxruntime` | `uv pip install -e ".[vad]"`, or use `--detector energy` |
| VAD finds no speech in quiet recordings | Lower `--speech-probability`-equivalent via `[analysis] speech_probability = 0.35` |
| Cuts sound abrupt | Raise `--pad-before`/`--pad-after`, or use `--shrink-pauses-to 0.3` |
| Cuts feel too tight overall | Try `--profile gentle`, or start from `autocut presets` |
| Logs need to feed a collector | `--log-json`, or `[log] format = "json"` with `file` |
| Render is slower than expected | Try `--encoder h264_nvenc` (or another from `doctor`), raise `--preset`, or check that `--hardware` is on |
| `error: source clip(s) not found` | The Cut List was moved away from its footage; keep `cutlist.json` beside the media or rerun `analyze` |
| Timeline imports with media offline | The source files moved since the Cut List was written; export again from the same folder or relink in the editor |
| EDL timecodes drift at 29.97 | Drop-frame is the default; pass `--edl-non-drop` only if your editor expects non-drop timecode |

## Roadmap

| Milestone | State |
| --- | --- |
| M0 Setup: repo, tooling, CI, `doctor` | done |
| M1 Ordering: parser, report, `order`, `--dry-run` | done |
| M2 Detection: energy + VAD, post-processing, cache | done |
| M3 Cut list + FFmpeg renderer | done |
| M4 Timeline exports: xmeml, FCPXML, EDL | done |
| M5 Robustness, performance, presets, structured logs | done |
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
