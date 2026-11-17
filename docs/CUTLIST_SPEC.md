# Cut List specification (schema_version 1)

The Cut List is the canonical, non-destructive description of the assembled
timeline. Every exporter (xmeml, FCPXML, EDL, FFmpeg render) reads it; nothing
reads an exporter's output back.

Guarantees:

- **Non-destructive.** Sources are never modified; cuts reference timestamps.
- **Deterministic.** The same sources and settings produce a byte-identical file
  modulo the `created_at` field.
- **Complete settings.** Every parameter that influenced the result is recorded,
  so a cut list can be reproduced and audited.
- **Frame-accurate.** Times are seconds as decimals in the file, but each cut
  point carries the frame index it was conformed to in the sequence timebase.

Status: the ordering report (`ordering.json`, schema version 1) is implemented in
M1; the Cut List below is frozen as the M3 contract and is written by
`autocut analyze`.

## Shape

```json
{
  "schema_version": 1,
  "created_at": "2026-11-17T10:31:00Z",
  "generator": { "name": "autocut", "version": "0.1.0" },
  "settings": {
    "detector": "vad",
    "threshold_db": -35.0,
    "min_silence": 0.5,
    "min_speech": 0.15,
    "pad_before": 0.12,
    "pad_after": 0.18,
    "shrink_pauses_to": null,
    "trim_head_tail": false,
    "denoise_for_analysis": false,
    "no_audio_policy": "keep",
    "audio_track": 0,
    "crossfade_ms": 10,
    "number_rule": "first",
    "preset": "podcast"
  },
  "sequence": {
    "fps": "30000/1001",
    "width": 1920,
    "height": 1080,
    "audio_rate": 48000,
    "frame_rounding": "nearest"
  },
  "clips": [
    {
      "order": 1,
      "source_path": "footage/01 - intro.mp4",
      "source_hash": "sha256:9f2c...",
      "duration": 83.2,
      "fps": "30000/1001",
      "width": 1920,
      "height": 1080,
      "audio_stream": 0,
      "warnings": [],
      "segments": [
        { "src_in": 1.2, "src_out": 14.85, "rec_in": 1.2, "rec_out": 14.85, "frames": 409 },
        { "src_in": 16.4, "src_out": 22.0, "rec_in": 14.85, "rec_out": 20.45, "frames": 167 }
      ],
      "markers": [{ "at": 1.2, "name": "01 - intro.mp4" }]
    }
  ],
  "timeline": {
    "duration": 61.42,
    "frames": 1840,
    "cuts": 12,
    "source_duration": 420.8,
    "removed_duration": 359.38,
    "removed_percent": 85.4
  }
}
```

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | int | 1 for this document; exporters reject unknown versions |
| `created_at` | string | ISO 8601 UTC |
| `generator` | object | `name`, `version` |
| `settings` | object | Every parameter used; unknown keys preserved verbatim |
| `sequence.fps` | string | Rational, e.g. `"30000/1001"`; never a float |
| `sequence.frame_rounding` | string | `"nearest"` \| `"floor"` for cut conforming |
| `clips[].order` | int | 1-based position after sorting |
| `clips[].source_hash` | string | Content hash of the source file |
| `clips[].segments[]` | array | Keep segments: `src_in` < `src_out`, ascending, non-overlapping |
| `clips[].segments[].rec_in` / `rec_out` | float | Position on the assembled timeline |
| `clips[].segments[].frames` | int | Duration in whole sequence frames |
| `clips[].markers[]` | array | Optional; default name is the filename |
| `timeline.duration` | float | Sum of kept durations minus crossfade overlaps |
| `timeline.removed_percent` | float | Rounded to one decimal |

## Rules

1. **Segments** are sorted, non-overlapping and inside `[0, clip.duration]`.
2. **No segment is shorter** than one sequence frame after conforming.
3. **`rec_in`/`rec_out`** are contiguous: each segment starts where the previous
   one ended (crossfades overlap audio only, not picture).
4. **Mixed sources**: `sequence` holds the conformed format; `clips[]` keeps each
   source's own `fps`, `width` and `height` so exporters can retime correctly.
5. **Warnings** travel with the clip (missing audio, all-silence, VFR
   normalisation), never in a separate side channel.
6. **Consumers must ignore** unknown keys added by later minor versions, and must
   fail loudly on a newer `schema_version`.

## Frame-accuracy rules

`t_frames = round(t * fps_num / fps_den)` with `round-half-up`, then
`t = frames * fps_den / fps_num`. Cut points are snapped to this grid before
`rec_in`/`rec_out` are computed. Tests assert that an EDL timecode and the frame
count always agree, including at NTSC rates (`30000/1001`, `24000/1001`).
