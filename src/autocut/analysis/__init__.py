"""Analysis layer: audio extraction, detectors, post-processing and caching."""

from __future__ import annotations

from autocut.analysis.base import (
    Detector,
    DetectorSettings,
    DetectorUnavailableError,
    NoAudioStreamError,
    Segment,
)
from autocut.analysis.cache import AnalysisCache, CachedAnalysis
from autocut.analysis.energy import EnergyDetector
from autocut.analysis.postprocess import postprocess
from autocut.analysis.runner import (
    BatchResult,
    ClipAnalysis,
    analyze_clip,
    analyze_clips,
    make_detector,
)
from autocut.analysis.vad import VadDetector

__all__ = [
    "AnalysisCache",
    "BatchResult",
    "CachedAnalysis",
    "ClipAnalysis",
    "Detector",
    "DetectorSettings",
    "DetectorUnavailableError",
    "EnergyDetector",
    "NoAudioStreamError",
    "Segment",
    "VadDetector",
    "analyze_clip",
    "analyze_clips",
    "make_detector",
    "postprocess",
]
