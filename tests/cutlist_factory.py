"""Build Cut List documents for exporter and renderer tests without ffmpeg."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def cutlist_payload(
    *,
    fps: str = "25/1",
    width: int = 1920,
    height: int = 1080,
    audio_rate: int = 48000,
    clips: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A minimal, valid Cut List with a contiguous recording timeline."""
    if clips is None:
        clips = [
            {
                "order": 1,
                "source_path": "footage/01.mp4",
                "duration_frames": 250,
                "fps": fps,
                "width": 1920,
                "height": 1080,
                "audio_stream": 1,
                "segments": [(0, 50), (75, 125)],
            },
            {
                "order": 2,
                "source_path": "footage/02.mp4",
                "duration_frames": 200,
                "fps": fps,
                "width": 1920,
                "height": 1080,
                "audio_stream": 1,
                "segments": [(10, 60)],
            },
        ]

    cursor = 0
    built: list[dict[str, Any]] = []
    for raw_clip in clips:
        clip = dict(raw_clip)
        segments = []
        for src_in, src_out in clip.pop("segments"):
            frames = max(1, src_out - src_in)
            segments.append(
                {
                    "src_in_frame": src_in,
                    "src_out_frame": src_out,
                    "rec_in_frame": cursor,
                    "rec_out_frame": cursor + frames,
                    "frames": frames,
                }
            )
            cursor += frames
        built.append(
            {
                **clip,
                "source_hash": clip.get("source_hash", "sha256:test"),
                "warnings": clip.get("warnings", []),
                "markers": clip.get("markers", []),
                "segments": segments,
            }
        )

    return {
        "schema_version": 1,
        "created_at": "2026-11-18T00:00:00Z",
        "generator": {"name": "autocut", "version": "0.1.0"},
        "settings": {"detector": "energy"},
        "sequence": {
            "fps": fps,
            "width": width,
            "height": height,
            "audio_rate": audio_rate,
            "frame_rounding": "nearest",
        },
        "clips": built,
        "timeline": {"frames": cursor},
    }


def write_cutlist(
    tmp_path: Path, payload: dict[str, Any] | None = None, name: str = "cutlist.json"
) -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload or cutlist_payload(), indent=2), encoding="utf-8"
    )
    return target
