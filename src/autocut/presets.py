"""Named workflow presets, a partial configuration rather than a mode.

A preset only supplies values; it never freezes them. Precedence, strongest
last: built-in defaults, the preset, the TOML config file, explicit CLI flags
(DECISIONS D30). Every preset is validated by the same pydantic models as a
config file, so a bad value here fails the test suite, not a user's run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

from autocut.errors import InputError


@dataclass(frozen=True)
class Preset:
    """One named starting point and the settings it contributes."""

    name: str
    summary: str
    settings: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


PRESETS: dict[str, Preset] = {
    "podcast": Preset(
        name="podcast",
        summary="Spoken-word interview: tight pauses, natural breaths kept",
        settings={
            "analysis": {
                "detector": "vad",
                "min_silence": 0.45,
                "min_speech": 0.18,
                "pad_before": 0.20,
                "pad_after": 0.35,
                "shrink_pauses_to": None,
            },
            "render": {"crf": 20, "crossfade_ms": 20},
        },
    ),
    "tutorial": Preset(
        name="tutorial",
        summary="Screen recording: keeps longer pauses so steps stay followable",
        settings={
            "analysis": {
                "detector": "vad",
                "min_silence": 0.80,
                "min_speech": 0.25,
                "pad_before": 0.25,
                "pad_after": 0.45,
            },
            "render": {"crf": 20, "crossfade_ms": 25},
        },
    ),
    "vlog": Preset(
        name="vlog",
        summary="Handheld, music-heavy footage: energy detector ignores the bed",
        settings={
            "analysis": {
                "detector": "energy",
                "threshold_db": -32.0,
                "min_silence": 0.40,
                "min_speech": 0.15,
                "pad_before": 0.15,
                "pad_after": 0.25,
            },
            "render": {"crf": 20, "crossfade_ms": 15},
        },
    ),
    "aggressive": Preset(
        name="aggressive",
        summary="Short-form: removes the most, shortest pads, smallest files",
        settings={
            "analysis": {
                "detector": "energy",
                "threshold_db": -30.0,
                "min_silence": 0.25,
                "min_speech": 0.10,
                "pad_before": 0.05,
                "pad_after": 0.10,
            },
            "render": {"crf": 22, "crossfade_ms": 8},
        },
    ),
    "gentle": Preset(
        name="gentle",
        summary="Conservative: only clear silences go, long lead-in and tail",
        settings={
            "analysis": {
                "detector": "vad",
                "threshold_db": -40.0,
                "min_silence": 1.00,
                "min_speech": 0.30,
                "pad_before": 0.30,
                "pad_after": 0.50,
            },
            "render": {"crf": 18, "crossfade_ms": 30},
        },
    ),
}


def preset_names() -> tuple[str, ...]:
    """Every preset name, in documentation order."""
    return tuple(PRESETS)


def get_preset(name: str) -> Preset:
    """Look up a preset, or fail with the valid names and a close match."""
    key = name.strip().lower()
    preset = PRESETS.get(key)
    if preset is not None:
        return preset
    message = f"unknown profile {name!r}; choose one of {', '.join(PRESETS)}"
    close = get_close_matches(key, list(PRESETS), n=1)
    if close:
        message += f" (did you mean {close[0]!r}?)"
    raise InputError(message)


def preset_settings(name: str) -> dict[str, dict[str, Any]]:
    """A fresh, mutable copy of a preset's settings."""
    return {
        section: dict(values) for section, values in get_preset(name).settings.items()
    }


def describe_presets() -> list[tuple[str, str]]:
    """``(name, summary)`` pairs for the ``presets`` command and docs."""
    return [(preset.name, preset.summary) for preset in PRESETS.values()]
