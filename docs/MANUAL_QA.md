# Manual QA checklist

Automated tests verify structure and frame maths, including that a rendered file
lasts as long as the Cut List says (within two frames). Only a real editor verifies
that a timeline actually imports. Run this list before releasing any milestone
that changes an exporter or the renderer.

## Fixtures

Prepare once, in a folder outside the repo:

| Fixture | Contents |
| --- | --- |
| `F1-basic` | 3 clips, 1080p30, tone bursts with 1 s silences, clearly spoken count ("one", "two", "three") |
| `F2-mixed` | one 1080p30, one 1080p25, one 720p30 clip |
| `F3-vfr` | phone footage, variable frame rate |
| `F4-edge` | one clip with no audio track, one entirely silent, one 0-byte file |
| `F5-long` | 30 minutes of talking-head footage |

## Per-export checks

For each format (`xmeml` → Premiere Pro, `fcpxml` → Resolve and FCP, `edl` → all
three, `render` → any player):

- [ ] The file imports without an error dialog or a "media offline" prompt.
- [ ] Clip order matches the ordering report, including sub-numbers (`1a`, `1b`).
- [ ] Every cut lands where the report says; scrub the joins frame by frame.
- [ ] Audio stays in sync for the whole `F5-long` assembly (check the last 30 s).
- [ ] Sequence frame rate and resolution equal `sequence` in the cut list.
- [ ] No audible click at joins with the 10 ms audio crossfade enabled.
- [ ] Markers (when enabled) sit at the start of each source clip and are named
      after the file.

## Render checks (M3)

- [ ] `autocut run` writes `cutlist.json` and `autocut.mp4`; the player shows the
      assembled duration from the Cut List, not the source duration.
- [ ] Each join is on the intended frame when stepped through frame by frame.
- [ ] No audible click or level jump at joins; `--crossfade-ms 0` should reintroduce
      clicks on hard cuts, proving the fades are active.
- [ ] A hardware encode (when `doctor` lists an encoder) produces the same
      duration as `--no-hardware`; force a failing encoder with
      `--encoder h264_nvenc` on a machine without a GPU to confirm the fallback
      warning and the successful software render.
- [ ] Mixed-resolution/rate fixture `F2-mixed` fills the frame without distortion
      (letterbox/pillarbox, square pixels).
- [ ] A no-audio clip renders with silent audio in a mixed assembly; an entirely
      audio-less project renders video only.
- [ ] Progress reaches 100% and the output is playable to the end.

## Detection checks (M2)

- [ ] Run `autocut analyze` on a natural 10+ minute talking-head take (not the
      repeated sample used for tuning) and read the removed percentage.
- [ ] Listen at every cut: no clipped word onsets or trailing consonants. If
      there are, raise `--pad-before`/`--pad-after` before touching thresholds.
- [ ] Compare `--detector energy` with `--detector vad`: energy should keep more
      material and miss short pauses; VAD should catch them.
- [ ] Re-run with the same settings: the second run reports "from cache" and the
      Cut List is byte-identical.
- [ ] `--no-audio-policy skip` omits the silent clip; `error` exits 3.

## Edge cases

- [ ] `F4-edge`: the no-audio clip follows `--no-audio-policy`, the silent clip is
      reported, and the 0-byte file is skipped with a warning, not a crash.
- [ ] `F3-vfr`: rendered duration matches the expected duration within one frame
      after conforming to constant frame rate.
- [ ] `F2-mixed`: the sequence format matches the most common clip, and the
      mismatched clips are retimed (not sped up) by the importer.
- [ ] `F5-long` on a slow disk: progress advances and ETA stays sane; cancel
      stops within a few seconds and leaves no partial file in the output folder.

## Regressions to check before every release

- [ ] `autocut doctor` shows the expected FFmpeg version and encoders.
- [ ] Ordering report, cut list and export agree on clip count and order.
- [ ] Re-running the same job twice yields identical reports.
- [ ] A folder of 100 clips with 3 corrupt files completes; the 3 failures are
      reported and the rest are processed.

## Packaged executable checks (M6)

Run against a downloaded release asset (or `dist/autocut` from a local build):

- [ ] `autocut --version` matches the release tag without `v`.
- [ ] `autocut doctor` finds the system FFmpeg and lists the same encoders as the
      Python install on the same machine.
- [ ] `autocut presets` lists five presets.
- [ ] `autocut analyze` on three or more clips uses the process pool (the log
      says "analysing N clip(s) with N processes") and produces a Cut List with
      `"detector": "vad"` — this is the check that catches a broken
      `multiprocessing.freeze_support` or a missing Silero model.
- [ ] The SHA-256 checksum matches, and the SBOM lists ONNX Runtime and the
      expected dependency versions.
- [ ] On macOS and Windows, the binary starts from a folder whose path contains
      spaces and non-ASCII characters.
- [ ] The binary runs on a machine with no Python and no `pip` installed.
