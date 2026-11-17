# Decisions

Every non-obvious choice, with the reason. Newest last.

## D1 — Files live at the repository root

The brief sketches `autocut/pyproject.toml` inside a wrapper folder. The GitHub
repository *is* the project, so `pyproject.toml`, `src/`, `tests/` and `docs/`
sit at its root. The package name stays `autocut` (the repo is `epic-cuts`).

## D2 — Custom number tokenizer instead of natsort for clip numbers

`natsort` cannot express `1 < 1a < 1b < 1.5 < 2`: it has no notion of a letter
suffix ranking before a fractional sub-number. Clip numbers therefore use an
explicit token grammar and sort key, and `natsort` is kept for what it does
well — natural ordering of *unnumbered* filenames and as a deterministic
tiebreak between duplicate numbers.

## D3 — Sort key: `(major, kind, sub_value, sub_text)`

- `kind` is `BARE=0 < LETTER=1 < NUMERIC=2`, which yields
  `1 < 1a < 1b < 1.5`.
- Fractions are normalised as their value (`0.5` for both `1.5` and `1.50`) so
  padding zeroes cannot reorder clips.
- `1.5` (sub value 0.5) sorts before `1-2` (sub value 2). The brief fixes only
  `1a < 1b < 1.5 < 2`; comparing the sub-part numerically is the most
  predictable reading of `1-2` as "clip 1, part 2".

## D4 — A letter suffix is 1-2 letters not followed by another letter

`1b` is a sub-number; `clip1final` is clip 1. The negative lookahead stops a
letter suffix from swallowing the start of an ordinary word.

## D5 — Strip only known media extensions before parsing

`Path.stem` turns `1.5` into `1` plus a `.5` suffix, losing the sub-number. Only
the documented container extensions are removed (case-insensitively); anything
else stays part of the name, so an extensionless `1.5` parses as `1.5`.

## D6 — Gaps are computed from major numbers only

`1, 1a, 3` reports a gap at 2. Sub-numbers never close a gap, because the next
*clip* is still missing. Gaps are merged into ranges (`2-4`, `6-8`).

## D7 — A duplicate is two files with the same sort key

`1.mp4` and `01.mp4` are duplicates; `1.mp4` and `1a.mp4` are not. Duplicates are
reported, never silently renamed or dropped, and their order is fixed
alphabetically so reports are reproducible.

## D8 — Unreadable clips stay in the report, flagged

Dropping a corrupt clip would silently renumber the sequence. Instead the item
keeps its slot, gets `status: unreadable` and its ffprobe reason, and is reported
under `problems.unreadable`. `--strict` makes it fatal; without it the run
continues (the M5 error-isolation acceptance criterion).

## D9 — Unnumbered clips go last, alphabetically, with a warning

`--strict` aborts instead, and `ordering.unnumbered_policy = "error"` gives the
same behaviour from the config file.

## D10 — Extensions decide what to *probe*; ffprobe decides what is supported

Scanning a folder cannot probe every file (a `node_modules` tree would be
miserable), so candidates are files with a known media extension or no extension
at all. Every candidate is then probed, and the container is confirmed from
`format_name` tokens, never from the extension. Non-media files are listed as
`ignored` instead of vanishing.

## D11 — Config rejects unknown keys

`extra="forbid"` in every settings model. A misspelled key is an input error
instead of a setting the user believes is applied. Only settings implemented in
this build are modelled; later milestones add their own groups.

## D12 — Milestone stubs fail loudly

`analyze`, `export` and `run` without `--dry-run` exit 3 with a message naming
the milestone that will implement them. This is the opposite of silently
pretending to work, and it keeps the CLI contract stable for scripts.

## D13 — Exit codes follow section 7 exactly

0 success, 1 warnings under `--strict-warnings`, 2 user input, 3 processing.
Typer's own usage errors also use 2, which matches the contract.

## D14 — Python via `uv`, requires-python >= 3.11

The machine had no system Python; `uv` provisions 3.12 cleanly. The lower bound
stays 3.11 because nothing needs 3.12 and `tomllib` is available from 3.11.

## D15 — MIT licence, FFmpeg optional at runtime

AutoCut is MIT. FFmpeg is not bundled in M0-M1: it is invoked as an external
program, which keeps distribution simple regardless of whether the user's build
is LGPL or GPL. Packaging a binary arrives in M6 and must re-check the licence of
the exact build shipped (see LICENSES.md).

## D16 — Coverage gate starts at 85%

The brief targets 85% on core packages. `fail_under = 85` is enforced through
`pytest --cov`, so a coverage regression fails CI rather than being noticed later.

## D17 — Presets are not shipped in M1

Named presets (`podcast`, `tutorial`, ...) are collections of *detection*
settings. Shipping them before detectors exist would mean documenting flags that
do nothing, so they land with M5 and the README says so.
