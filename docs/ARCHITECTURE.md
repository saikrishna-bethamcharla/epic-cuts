# Architecture

Five layers. Each depends only on the layers below it, so the engine can be
called by a CLI today and by a local service or editor panel later without
rewriting the core.

```
5  interface   cli.py            (later: local service, GUI, Premiere panel)
4  export      export/*          xmeml, fcpxml, edl, render           done
3  planning    planning/*        cut list, loader + frame timebase   done
2  analysis    analysis/*        detectors, postprocess, cache, pool done
1  media       media/*           ffprobe, fingerprint, tools        done
0  ordering    ordering/*        filename numbers, discovery, report done
```

`ordering` sits beside the media layer: it needs only filenames and, optionally,
ffprobe facts.

## Data flow

```
INPUT paths
   │  ordering.discovery.discover()          candidate files, ignored files
   ▼
ordering.parser.parse_filename()              ParsedNumber (major, kind, sub)
   │
   ▼
ordering.plan.build_ordering()                OrderingResult: sorted OrderedItems
   │                                          + gaps, duplicates, unnumbered, unreadable
   ├── ordering.report.render_*()             human table / ordering.json
   ▼
analysis.audio.stream_pcm()                   16 kHz mono, chunked ffmpeg pipe
   ▼
analysis.{energy,vad}.detect()                raw keep segments per clip
   ▼
analysis.postprocess.postprocess()            merge, drop blips, pad, cap pauses, trim
   ▼
analysis.cache + runner                       JSON cache hit, process-pool isolation
   ▼
planning.cutlist.build_cutlist()              Cut List: integer source/rec frames
   ▼
planning.loader.load_cutlist()                validated frames, resolved sources
   ▼
exporters.* / render.ffmpeg                   xmeml / FCPXML / EDL / rendered file
```

The **Cut List** is the contract between planning, export and every editor
integration. It is defined in [CUTLIST_SPEC.md](CUTLIST_SPEC.md) and versioned;
exporters never reach back into analysis or media state.

## Modules

| Module | Responsibility |
| --- | --- |
| `autocut.errors` | Expected failures and their exit codes |
| `autocut.logging_utils` | Logging setup (`--log-level`, later JSON lines) |
| `autocut.config` | Validated settings (pydantic), TOML loading, CLI overrides |
| `autocut.media.tools` | Locating ffmpeg/ffprobe, versions, hardware encoders |
| `autocut.media.probe` | ffprobe JSON → `MediaInfo`; container support rules |
| `autocut.media.fingerprint` | Fast (size/mtime/head+tail blake2b) or full SHA-256 |
| `autocut.analysis.audio` | Chunked 16 kHz mono PCM pipe; never loads a whole file |
| `autocut.analysis.energy` | `silencedetect` → keep segments |
| `autocut.analysis.vad` | Silero v5 ONNX (64-sample context) or webrtcvad |
| `autocut.analysis.postprocess` | The shared, ordered segment pipeline |
| `autocut.analysis.cache` | Keyed analysis results on disk |
| `autocut.analysis.runner` | Policies, cache use, parallel batch, isolation |
| `autocut.planning.timebase` | Rational frame rate math |
| `autocut.planning.cutlist` | Cut List model, frame conforming, JSON |
| `autocut.planning.loader` | Validated Cut List loading; source resolution |
| `autocut.exporters.timecode` | SMPTE non-drop/drop-frame conversion |
| `autocut.exporters.edl` | CMX 3600 events and text |
| `autocut.exporters.xmeml` | FCP7 XML sequence |
| `autocut.exporters.fcpxml` | FCPXML 1.10 project |
| `autocut.exporters` | Format dispatch, extension inference |
| `autocut.render.ffmpeg` | Filter-graph render, encoders, progress |
| `autocut.ordering.parser` | Number extraction and the sort key |
| `autocut.ordering.discovery` | Which files are candidates |
| `autocut.ordering.plan` | Sorting, probing, problem collection |
| `autocut.ordering.report` | Human and JSON ordering reports |
| `autocut.doctor` | Environment report |
| `autocut.cli` | Argument parsing, exit codes, wiring |

## Invariants

- **Source media is read-only.** Outputs go to the `-o` folder.
- **Deterministic output.** Sorting is total: number key, then natural filename,
  then path. The same input and settings give an identical report.
- **No shell strings.** Every subprocess receives an argument list.
- **Problems are data.** Gaps, duplicates, unnumbered and unreadable clips are
  reported in the result object, not just printed, so the service API and UI can
  consume the same facts.
- **No UI in the core.** Nothing below `cli.py` prints or prompts.

## Adding a detector

1. Implement `detect(path, *, duration, settings) -> list[Segment]` in
   `analysis/`, returning **raw** keep segments in seconds.
2. Register the name in `analysis.runner.make_detector` so `--detector <name>`
   resolves, and give it a `version` string (it is part of the cache key).
3. Reuse `analysis.postprocess`; never re-implement merging or padding.
4. Add a synthetic fixture with known boundaries and assert within 50 ms, plus a
   unit test for the pure parsing/framing helpers.

## Adding an exporter

1. Take a `LoadedCutList`; never re-analyse media.
2. Return bytes from a pure `build_<format>()` function so it can be tested
   without touching disk, and register the format in `exporters/__init__.py`
   with a default suffix.
3. Add a structure test plus a line in the manual QA checklist.
4. Never trust extra keys; fail loudly on a newer `schema_version`.

## Engine API (M7 and later)

The CLI is a thin wrapper over `build_ordering`, the analysis runner, the
renderer and the exporters. A local service exposes `order`, `analyze`, `export`,
`progress` and `cancel`; progress and cancellation must be threaded through
these functions,
not bolted onto the CLI.
