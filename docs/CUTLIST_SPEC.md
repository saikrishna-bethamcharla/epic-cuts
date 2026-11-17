# Cut List specification (schema_version 1)

The Cut List is the canonical, non-destructive description of the assembled
timeline. Every exporter (xmeml, FCPXML, EDL, FFmpeg render) reads it; nothing
reads an exporter's output back.

Guarantees:

- **Frames are canonical.** A cut point is an integer frame index; every seconds
  value in the file is *derived* from frames. Seconds are convenience fields for
  humans and JSON consumers, never the source of truth.
- **Non-destructive.** Sources are never modified; cuts reference frame indices.
- **Deterministic.** The same sources and settings produce a byte-identical file
  modulo `created_at`.
- **Complete settings.** Every parameter that influenced the result is recorded.
- **Two timebases.** `src_*_frame` is in the clip's own rate, `rec_*_frame` is on
  the assembled sequence, so mixed-rate sources can be conformed exactly.

Status: written by `autocut analyze` (M2, detection only). Exporters consume it
from M3/M4.

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
    "number_rule": "natural",
    "full_hash": false
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
      "source_hash": "fast:104857600:1731837060123456789:9f2c1b...",
      "duration_frames": 2079,
      "duration": 69.3356,
      "fps": "30000/1001",
      "width": 1920,
      "height": 1080,
      "audio_stream": 0,
      "warnings": [],
      "segments": [
        {
          "src_in_frame": 36,
          "src_out_frame": 445,
          "rec_in_frame": 0,
          "rec_out_frame": 409,
          "frames": 409,
          "src_in": 1.2012,
          "src_out": 14.8508,
          "rec_in": 0.0,
          "rec_out": 13.647
        }
      ],
      "markers": [{ "at_frame": 0, "at": 0.0, "name": "01 - intro.mp4" }]
    }
  ],
  "timeline": {
    "frames": 1840,
    "duration": 61.395,
    "cuts": 12,
    "source_duration": 420.8,
    "removed_duration": 359.405,
    "removed_percent": 85.4
  }
}
```

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | int | 1 for this document; exporters reject newer versions |
| `generator` | object | `name`, `version` |
| `settings` | object | Every parameter used, including detector and padding |
| `sequence.fps` | string | Rational (`"30000/1001"`), never a float |
| `sequence.frame_rounding` | string | `"nearest"`: half frames round up |
| `clips[].source_hash` | string | `fast:<size>:<mtime_ns>:<blake2b>` or `sha256:<hex>` with `--full-hash` |
| `clips[].duration_frames` | int | Source length in the clip's own timebase |
| `clips[].segments[].src_in_frame` | int | Inclusive start frame in the **source** rate |
| `clips[].segments[].src_out_frame` | int | Exclusive end frame in the **source** rate |
| `clips[].segments[].rec_in_frame` | int | Inclusive start on the **sequence** timeline |
| `clips[].segments[].rec_out_frame` | int | Exclusive end on the **sequence** timeline |
| `clips[].segments[].frames` | int | `rec_out_frame - rec_in_frame` |
| `clips[].markers[].at_frame` | int | Sequence frame; `at` is derived |

## Rules

1. **Integers first.** `src_*` and `rec_*` frames are the stored values; `src_in`,
   `src_out`, `rec_in`, `rec_out` and `at` are `frame * den / num`, rounded to 6
   decimals.
2. **Contiguous recording timeline.** Segment *n* has
   `rec_in_frame == previous.rec_out_frame`, including across clip boundaries, and
   the first segment starts at 0.
3. **Totals agree.** `timeline.frames == sum(segments[].frames) ==` the last
   `rec_out_frame`, and `timeline.duration == fps_den/fps_num * frames`.
4. **In bounds.** `0 <= src_in_frame < src_out_frame <= duration_frames`; clips
   are clipped to their own length, never beyond it.
5. **No zero-length cuts.** After conforming, any segment shorter than one
   sequence frame is dropped (or extended to one frame when it started non-empty).
6. **Mixed sources.** `sequence` holds the conformed format; each clip keeps its
   own `fps`, `width` and `height` so exporters can retime rather than assume.
7. **Warnings travel with the clip** (missing audio, all-silence, unreadable),
   never in a separate side channel.
8. **Consumers must ignore** unknown keys added by later minor versions and must
   fail loudly on a newer `schema_version`.

## Frame-accuracy rules

`frames(t) = floor(t * num / den + 1/2)` (half up, computed with exact rationals
so no float drift accumulates), and `seconds(f) = f * den / num`. Tests assert
that frame indices round-trip at 24, 25, 30000/1001, 60000/1001 and 50 fps, and
that EDL timecodes agree with frame counts at NTSC rates (M4).
