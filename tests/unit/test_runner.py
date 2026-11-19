"""Runner behaviour: policies, cache, isolation and job sizing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import autocut.analysis.runner as runner_module
from autocut.analysis.base import DetectorSettings, Segment
from autocut.analysis.cache import AnalysisCache
from autocut.analysis.runner import (
    AnalysisRequest,
    analyze_clip,
    analyze_clips,
    make_detector,
    resolve_jobs,
)
from autocut.errors import InputError, ProcessingError

SETTINGS = DetectorSettings(pad_before=0.0, pad_after=0.0)


class FakeDetector:
    """A detector with scripted output, so runner logic is testable without media."""

    name = "fake"
    version = "1.0"

    def __init__(
        self, segments: list[Segment] | None = None, error: Exception | None = None
    ) -> None:
        self._segments = segments or []
        self._error = error
        self.calls = 0

    def detect(
        self, path: Path, *, duration: float, settings: DetectorSettings
    ) -> list[Segment]:
        del path, duration, settings
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._segments)


def make_request(
    tmp_path: Path, *, has_audio: bool = True, name: str = "1.wav"
) -> AnalysisRequest:
    target = tmp_path / name
    target.write_bytes(b"audio-bytes")
    return AnalysisRequest(path=target, duration=10.0, has_audio=has_audio)


def test_analyses_and_postprocesses(tmp_path: Path) -> None:
    detector = FakeDetector([Segment(1.0, 2.0)])
    analysis = analyze_clip(
        make_request(tmp_path), settings=SETTINGS, detector=detector
    )
    assert analysis.ok
    assert [segment.as_tuple() for segment in analysis.segments] == [(0.0, 10.0)]
    assert detector.calls == 1


def test_no_audio_keep_policy_keeps_the_whole_clip(tmp_path: Path) -> None:
    analysis = analyze_clip(
        make_request(tmp_path, has_audio=False),
        settings=SETTINGS,
        detector=FakeDetector(),
        policy="keep",
    )
    assert [segment.as_tuple() for segment in analysis.segments] == [(0.0, 10.0)]
    assert any("no audio track" in warning for warning in analysis.warnings)


def test_no_audio_skip_policy_keeps_nothing(tmp_path: Path) -> None:
    analysis = analyze_clip(
        make_request(tmp_path, has_audio=False),
        settings=SETTINGS,
        detector=FakeDetector(),
        policy="skip",
    )
    assert analysis.segments == ()
    assert any("skipped" in warning for warning in analysis.warnings)


def test_no_audio_error_policy_raises(tmp_path: Path) -> None:
    with pytest.raises(ProcessingError, match="no-audio policy is 'error'"):
        analyze_clip(
            make_request(tmp_path, has_audio=False),
            settings=SETTINGS,
            detector=FakeDetector(),
            policy="error",
        )


def test_entirely_silent_clip_follows_the_policy(tmp_path: Path) -> None:
    analysis = analyze_clip(
        make_request(tmp_path),
        settings=SETTINGS,
        detector=FakeDetector([]),
        policy="keep",
    )
    assert [segment.as_tuple() for segment in analysis.segments] == [(0.0, 10.0)]
    assert any("entirely silent" in warning for warning in analysis.warnings)


def test_speech_dropped_by_min_speech_follows_the_policy(tmp_path: Path) -> None:
    settings = DetectorSettings(min_speech=0.5, pad_before=0.0, pad_after=0.0)
    analysis = analyze_clip(
        make_request(tmp_path),
        settings=settings,
        detector=FakeDetector([Segment(2.0, 2.1)]),
        policy="keep",
    )
    assert any("min_speech" in warning for warning in analysis.warnings)


def test_cache_hit_skips_detection(tmp_path: Path) -> None:
    detector = FakeDetector([Segment(1.0, 2.0)])
    cache = AnalysisCache(tmp_path / "cache")
    request = make_request(tmp_path)

    first = analyze_clip(request, settings=SETTINGS, detector=detector, cache=cache)
    second = analyze_clip(request, settings=SETTINGS, detector=detector, cache=cache)

    assert first.cached is False
    assert second.cached is True
    assert detector.calls == 1
    assert [s.as_tuple() for s in second.segments] == [
        s.as_tuple() for s in first.segments
    ]


def test_disabled_cache_repeats_the_work(tmp_path: Path) -> None:
    detector = FakeDetector([Segment(1.0, 2.0)])
    cache = AnalysisCache(tmp_path / "cache", enabled=False)
    request = make_request(tmp_path)
    analyze_clip(request, settings=SETTINGS, detector=detector, cache=cache)
    analyze_clip(request, settings=SETTINGS, detector=detector, cache=cache)
    assert detector.calls == 2


def test_different_settings_miss_the_cache(tmp_path: Path) -> None:
    detector = FakeDetector([Segment(1.0, 2.0)])
    cache = AnalysisCache(tmp_path / "cache")
    request = make_request(tmp_path)
    analyze_clip(request, settings=SETTINGS, detector=detector, cache=cache)
    analyze_clip(
        request,
        settings=DetectorSettings(pad_before=0.0, pad_after=0.0, min_silence=0.9),
        detector=detector,
        cache=cache,
    )
    assert detector.calls == 2


def test_unknown_detector_name_is_an_input_error() -> None:
    with pytest.raises(InputError, match="unknown detector"):
        make_detector("magic")


def test_known_detector_names_resolve() -> None:
    assert make_detector("energy").name == "energy"
    assert make_detector("vad").name == "vad"


def test_unknown_policy_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="unknown no-audio policy"):
        analyze_clip(
            make_request(tmp_path),
            settings=SETTINGS,
            detector=FakeDetector(),
            policy="ignore",
        )


def test_analyze_clips_isolates_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = make_request(tmp_path, name="good.wav")
    bad = make_request(tmp_path, name="bad.wav")

    class SwitchingDetector(FakeDetector):
        def detect(
            self, path: Path, *, duration: float, settings: DetectorSettings
        ) -> list[Segment]:
            if path.name == "bad.wav":
                raise ProcessingError("this clip is broken")
            return super().detect(path, duration=duration, settings=settings)

    monkeypatch.setattr(
        runner_module,
        "make_detector",
        lambda _name: SwitchingDetector([Segment(1.0, 2.0)]),
    )
    progress: list[tuple[int, int]] = []
    batch = analyze_clips(
        [bad, good],
        settings=SETTINGS,
        detector_name="energy",
        on_progress=lambda done, total: progress.append((done, total)),
    )

    assert len(batch.analyses) == 2
    assert len(batch.failures) == 1
    assert batch.failures[0][0].name == "bad.wav"
    assert [analysis.path.name for analysis in batch.ok_analyses] == ["good.wav"]
    assert progress == [(1, 2), (2, 2)]


def test_analyze_clips_without_requests_is_empty() -> None:
    batch = analyze_clips([], settings=SETTINGS)
    assert batch.analyses == ()
    assert batch.failures == ()


def test_resolve_jobs_bounds() -> None:
    assert resolve_jobs(0, 1) == 1
    assert resolve_jobs(0, 4) >= 1
    assert resolve_jobs(3, 10) == 3
    assert resolve_jobs(9, 2) == 2
    assert resolve_jobs(-1, 3) >= 1


def test_clip_analysis_reports_kept_duration(tmp_path: Path) -> None:
    analysis = analyze_clip(
        make_request(tmp_path),
        settings=SETTINGS,
        detector=FakeDetector([Segment(1.0, 3.0)]),
    )
    assert analysis.kept_duration == 10.0
    assert analysis.error is None
    assert analysis.fingerprint.startswith("fast:")


def test_request_dataclass_defaults() -> None:
    request = AnalysisRequest(path=Path("x.mp4"), duration=1.0)
    assert request.has_audio is True


def test_metadata_is_serialisable(tmp_path: Path) -> None:
    analysis: Any = analyze_clip(
        make_request(tmp_path), settings=SETTINGS, detector=FakeDetector()
    )
    assert analysis.detector == "fake"
    assert analysis.detector_version == "1.0"
