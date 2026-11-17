# Manual QA checklist

Automated tests verify structure and frame maths. Only a real editor verifies
that a timeline actually imports. Run this list before releasing any milestone
that changes an exporter (M4 onwards).

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
