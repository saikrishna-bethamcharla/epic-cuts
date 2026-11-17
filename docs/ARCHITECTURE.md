# Architecture

Five layers. Each depends only on the layers below it, so the engine can be
called by a CLI today and by a local service or editor panel later without
rewriting the core.

```
5  interface   cli.py            (later: local service, GUI, Premiere panel)
4  export      export/*          (xmeml, fcpxml, edl, render)      [M3-M4]
3  planning    planning/*        (Cut List, timeline builder)      [M3]
2  analysis    analysis/*        (detectors, postprocess, cache)   [M2]
1  media       media/*           (ffprobe, audio extraction, timebase)
0  ordering    ordering/*        (filename numbers, discovery, report)
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
analysis (M2)                                 speech segments per clip
   ▼
planning (M3)                                 Cut List (schema_version 1)
   ▼
export (M3-M4)                                xmeml / FCPXML / EDL / rendered file
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

## Adding a detector (M2)

1. Implement `detect(audio: AudioSource, settings: DetectorSettings) -> list[Segment]`
   in `analysis/`, returning *keep* segments in seconds.
2. Register it in the detector factory so `--detector <name>` resolves.
3. Reuse `analysis.postprocess` (merge, drop short, pad, shrink pauses); do not
   re-implement it per detector.
4. Add fixtures with synthetic tone/silence and assert boundaries within 50 ms.

## Adding an exporter (M4)

1. Take a validated Cut List object; never re-analyse media.
2. Emit the format into the output folder and return the written path.
3. Add a golden-file test plus a line in the manual QA checklist.

## Engine API (M7 and later)

The CLI is a thin wrapper over `build_ordering` and, from M3, the cut-list
builder. A local service exposes `order`, `analyze`, `export`, `progress` and
`cancel`; progress and cancellation must be threaded through these functions,
not bolted onto the CLI.
