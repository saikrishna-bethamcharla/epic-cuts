"""Analysis cache keyed by file fingerprint, detector, settings and version.

A hit turns a re-run into JSON reads, which is what makes iterating on thresholds
bearable on real footage. Keys include *everything* that changes the result —
including padding — so a stale entry can never be mistaken for a fresh one.
Corrupt or half-written entries are ignored, never fatal.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocut.analysis.base import Segment

LOGGER = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1


def default_cache_root() -> Path:
    """A per-user cache folder that works on Windows, macOS and Linux."""
    override = os.environ.get("AUTOCUT_CACHE_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "autocut" / "analysis"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "autocut" / "analysis"
    return Path(tempfile.gettempdir()) / "autocut" / "analysis"


@dataclass(frozen=True)
class CachedAnalysis:
    """What the cache stores: post-processed keep segments plus warnings."""

    segments: tuple[tuple[float, float], ...]
    warnings: tuple[str, ...] = ()

    def as_segments(self) -> tuple[Segment, ...]:
        return tuple(Segment(start=start, end=end) for start, end in self.segments)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "segments": [[start, end] for start, end in self.segments],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> CachedAnalysis:
        raw_segments = payload.get("segments") or []
        segments: list[tuple[float, float]] = []
        for item in raw_segments:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                segments.append((float(item[0]), float(item[1])))
        warnings_raw = payload.get("warnings") or []
        warnings = tuple(str(item) for item in warnings_raw)
        return cls(segments=tuple(segments), warnings=warnings)


class AnalysisCache:
    """A directory of JSON files, one per (clip, detector, settings) key."""

    def __init__(self, root: Path | None = None, *, enabled: bool = True) -> None:
        self.root = Path(root) if root is not None else default_cache_root()
        self.enabled = enabled

    @staticmethod
    def make_key(
        *,
        fingerprint: str,
        detector: str,
        detector_version: str,
        settings: Mapping[str, Any],
        duration: float,
        has_audio: bool,
    ) -> str:
        payload = {
            "fingerprint": fingerprint,
            "detector": detector,
            "detector_version": detector_version,
            "settings": dict(settings),
            "duration": round(duration, 6),
            "has_audio": has_audio,
            "schema": CACHE_SCHEMA_VERSION,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def path_for(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def load(self, key: str) -> CachedAnalysis | None:
        if not self.enabled:
            return None
        target = self.path_for(key)
        if not target.exists():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("ignoring unreadable cache entry %s: %s", target, exc)
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
            return None
        cached = CachedAnalysis.from_json(payload)
        LOGGER.debug("cache hit for %s", key[:12])
        return cached

    def store(self, key: str, analysis: CachedAnalysis) -> None:
        if not self.enabled:
            return
        target = self.path_for(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(analysis.to_json(), indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - read-only cache dir
            LOGGER.warning("cannot write cache entry %s: %s", target, exc)
