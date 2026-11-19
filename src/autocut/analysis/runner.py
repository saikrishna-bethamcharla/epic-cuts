"""Run one detector over many clips: caching, policies, parallelism, isolation.

One failing clip is reported and skipped; it never aborts the batch unless
``--strict`` is set. Parallelism uses a process pool because decoding and VAD are
CPU-bound Python work, and each worker owns its own ONNX session.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from autocut.analysis.base import (
    Detector,
    DetectorSettings,
    NoAudioStreamError,
    Segment,
)
from autocut.analysis.cache import AnalysisCache, CachedAnalysis, default_cache_root
from autocut.analysis.energy import EnergyDetector
from autocut.analysis.postprocess import postprocess
from autocut.analysis.vad import VadDetector
from autocut.errors import InputError, ProcessingError
from autocut.media.fingerprint import file_fingerprint

LOGGER = logging.getLogger(__name__)

AudioPolicy = Literal["keep", "skip", "error"]
POLICIES: tuple[str, ...] = ("keep", "skip", "error")

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class AnalysisRequest:
    """One clip to analyse."""

    path: Path
    duration: float
    has_audio: bool = True


@dataclass(frozen=True)
class ClipAnalysis:
    """The analysis outcome for one clip."""

    path: Path
    duration: float
    fingerprint: str
    segments: tuple[Segment, ...]
    warnings: tuple[str, ...]
    detector: str
    detector_version: str
    cached: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def kept_duration(self) -> float:
        return sum(segment.duration for segment in self.segments)


@dataclass(frozen=True)
class BatchResult:
    """Every clip's outcome, successes and failures kept apart."""

    analyses: tuple[ClipAnalysis, ...]
    failures: tuple[tuple[Path, str], ...] = ()

    @property
    def ok_analyses(self) -> tuple[ClipAnalysis, ...]:
        return tuple(item for item in self.analyses if item.ok)

    @property
    def cached_count(self) -> int:
        return sum(1 for item in self.analyses if item.cached)


def make_detector(name: str) -> Detector:
    """Resolve a detector name to an instance."""
    if name == "energy":
        return EnergyDetector()
    if name == "vad":
        return VadDetector()
    raise InputError(f"unknown detector {name!r}; choose 'energy' or 'vad'")


def _validate_policy(policy: str) -> AudioPolicy:
    if policy not in POLICIES:
        raise InputError(
            f"unknown no-audio policy {policy!r}; choose keep, skip or error"
        )
    return policy  # type: ignore[return-value]


def _policy_outcome(
    policy: AudioPolicy,
    *,
    duration: float,
    reason: str,
) -> tuple[tuple[Segment, ...], tuple[str, ...]]:
    """Apply ``--no-audio-policy`` to a clip that produced no speech."""
    if policy == "error":
        raise ProcessingError(f"{reason} (no-audio policy is 'error')")
    if policy == "skip":
        return (), (f"{reason}; skipped",)
    return (Segment(start=0.0, end=duration),), (f"{reason}; kept whole clip",)


def analyze_clip(
    request: AnalysisRequest,
    *,
    settings: DetectorSettings,
    detector: Detector,
    cache: AnalysisCache | None = None,
    policy: str = "keep",
    full_hash: bool = False,
) -> ClipAnalysis:
    """Analyse one clip, using the cache when a matching entry exists."""
    resolved_policy = _validate_policy(policy)
    fingerprint = file_fingerprint(request.path, full_hash=full_hash)
    cache = cache if cache is not None else AnalysisCache(enabled=False)

    key = AnalysisCache.make_key(
        fingerprint=fingerprint,
        detector=detector.name,
        detector_version=detector.version,
        settings=settings.cache_key(),
        duration=request.duration,
        has_audio=request.has_audio,
    )

    hit = cache.load(key)
    if hit is not None:
        return ClipAnalysis(
            path=request.path,
            duration=request.duration,
            fingerprint=fingerprint,
            segments=hit.as_segments(),
            warnings=hit.warnings,
            detector=detector.name,
            detector_version=detector.version,
            cached=True,
        )

    if not request.has_audio:
        segments, warnings = _policy_outcome(
            resolved_policy, duration=request.duration, reason="no audio track"
        )
        outcome = CachedAnalysis(
            segments=tuple(segment.as_tuple() for segment in segments),
            warnings=warnings,
        )
        cache.store(key, outcome)
        return ClipAnalysis(
            path=request.path,
            duration=request.duration,
            fingerprint=fingerprint,
            segments=segments,
            warnings=warnings,
            detector=detector.name,
            detector_version=detector.version,
        )

    try:
        raw = detector.detect(
            request.path, duration=request.duration, settings=settings
        )
    except NoAudioStreamError as exc:
        raw = []
        LOGGER.warning("%s", exc)

    if not raw:
        segments, warnings = _policy_outcome(
            resolved_policy,
            duration=request.duration,
            reason="clip is entirely silent or its audio is unreadable",
        )
    else:
        processed = postprocess(raw, duration=request.duration, settings=settings)
        if processed:
            segments, warnings = tuple(processed), ()
        else:
            segments, warnings = _policy_outcome(
                resolved_policy,
                duration=request.duration,
                reason="no speech survived min_speech filtering",
            )

    cache.store(
        key,
        CachedAnalysis(
            segments=tuple(segment.as_tuple() for segment in segments),
            warnings=warnings,
        ),
    )
    return ClipAnalysis(
        path=request.path,
        duration=request.duration,
        fingerprint=fingerprint,
        segments=segments,
        warnings=warnings,
        detector=detector.name,
        detector_version=detector.version,
    )


def _worker(payload: dict[str, Any]) -> dict[str, Any]:
    """Process-pool entry point: one clip, fully isolated."""
    try:
        settings = DetectorSettings(**payload["settings"])
        detector = make_detector(payload["detector"])
        cache = AnalysisCache(Path(payload["cache_root"]), enabled=payload["use_cache"])
        analysis = analyze_clip(
            AnalysisRequest(
                path=Path(payload["path"]),
                duration=float(payload["duration"]),
                has_audio=bool(payload["has_audio"]),
            ),
            settings=settings,
            detector=detector,
            cache=cache,
            policy=payload["policy"],
            full_hash=bool(payload["full_hash"]),
        )
    except Exception as exc:
        return {"path": payload["path"], "error": f"{type(exc).__name__}: {exc}"}

    return {
        "path": str(analysis.path),
        "duration": analysis.duration,
        "fingerprint": analysis.fingerprint,
        "segments": [segment.as_tuple() for segment in analysis.segments],
        "warnings": list(analysis.warnings),
        "detector": analysis.detector,
        "detector_version": analysis.detector_version,
        "cached": analysis.cached,
        "error": None,
    }


def _from_payload(payload: dict[str, Any]) -> ClipAnalysis:
    error = payload.get("error")
    if error:
        return ClipAnalysis(
            path=Path(payload["path"]),
            duration=0.0,
            fingerprint="",
            segments=(),
            warnings=(),
            detector="",
            detector_version="",
            error=str(error),
        )
    return ClipAnalysis(
        path=Path(payload["path"]),
        duration=float(payload["duration"]),
        fingerprint=str(payload["fingerprint"]),
        segments=tuple(
            Segment(start=float(start), end=float(end))
            for start, end in payload["segments"]
        ),
        warnings=tuple(str(item) for item in payload["warnings"]),
        detector=str(payload["detector"]),
        detector_version=str(payload["detector_version"]),
        cached=bool(payload["cached"]),
    )


def resolve_jobs(jobs: int, count: int) -> int:
    """``0`` or a negative value means "one worker per core"."""
    if count <= 1:
        return 1
    if jobs <= 0:
        return max(1, min(count, os.cpu_count() or 1))
    return max(1, min(jobs, count))


def analyze_clips(
    requests: Sequence[AnalysisRequest],
    *,
    settings: DetectorSettings,
    detector_name: str = "vad",
    cache: AnalysisCache | None = None,
    jobs: int = 1,
    policy: str = "keep",
    full_hash: bool = False,
    on_progress: ProgressCallback | None = None,
) -> BatchResult:
    """Analyse every request, isolating failures. Order is preserved."""
    if not requests:
        return BatchResult(analyses=())

    cache = cache if cache is not None else AnalysisCache(enabled=False)
    total = len(requests)
    workers = resolve_jobs(jobs, total)
    analyses: list[ClipAnalysis] = []
    failures: list[tuple[Path, str]] = []

    def record(analysis: ClipAnalysis, done: int) -> None:
        analyses.append(analysis)
        if on_progress is not None:
            on_progress(done, total)

    if workers == 1:
        detector = make_detector(detector_name)
        for index, request in enumerate(requests, start=1):
            try:
                analysis = analyze_clip(
                    request,
                    settings=settings,
                    detector=detector,
                    cache=cache,
                    policy=policy,
                    full_hash=full_hash,
                )
            except Exception as exc:
                analysis = ClipAnalysis(
                    path=request.path,
                    duration=request.duration,
                    fingerprint="",
                    segments=(),
                    warnings=(),
                    detector=detector.name,
                    detector_version=detector.version,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if analysis.error:
                failures.append((request.path, analysis.error))
                LOGGER.warning("%s: %s", request.path, analysis.error)
            record(analysis, index)
        return BatchResult(analyses=tuple(analyses), failures=tuple(failures))

    LOGGER.info("analysing %d clip(s) with %d processes", total, workers)
    payloads = [
        {
            "path": str(request.path),
            "duration": request.duration,
            "has_audio": request.has_audio,
            "settings": asdict(settings),
            "detector": detector_name,
            "cache_root": str(cache.root),
            "use_cache": cache.enabled,
            "policy": policy,
            "full_hash": full_hash,
        }
        for request in requests
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for index, payload in enumerate(pool.map(_worker, payloads), start=1):
            analysis = _from_payload(payload)
            if analysis.error:
                failures.append((analysis.path, analysis.error))
                LOGGER.warning("%s: %s", analysis.path, analysis.error)
            record(analysis, index)

    return BatchResult(analyses=tuple(analyses), failures=tuple(failures))


def default_analysis_cache(
    root: Path | None = None, *, enabled: bool = True
) -> AnalysisCache:
    """Convenience constructor used by the CLI."""
    return AnalysisCache(root or default_cache_root(), enabled=enabled)
