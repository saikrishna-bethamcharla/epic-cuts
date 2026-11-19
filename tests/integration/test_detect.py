"""Detection against synthetic and real-speech fixtures (M2 acceptance)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from autocut.analysis.base import DetectorSettings, Segment
from autocut.analysis.cache import AnalysisCache
from autocut.analysis.energy import EnergyDetector
from autocut.analysis.runner import AnalysisRequest, analyze_clip, analyze_clips
from autocut.analysis.vad import VadDetector
from autocut.errors import ProcessingError
from autocut.media.probe import probe_media
from tests.media_fixtures import (
    all_silence,
    speech_pattern,
    tone_bursts,
    vfr_video,
    video_clip,
    wav_duration,
)

TOLERANCE = 0.05
SETTINGS = DetectorSettings()


def best_matching(segments: list[Segment], start: float, end: float) -> Segment:
    return max(segments, key=lambda item: min(item.end, end) - max(item.start, start))


def test_energy_boundaries_are_within_50ms(tmp_path: Path) -> None:
    wav = tone_bursts(tmp_path / "tones.wav", speech=1.0, silence=1.0, repeats=3)
    duration = wav_duration(wav)
    segments = EnergyDetector().detect(wav, duration=duration, settings=SETTINGS)

    truth = [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]
    assert len(segments) == len(truth)
    for segment, (start, end) in zip(segments, truth, strict=True):
        assert segment.start == pytest.approx(start, abs=TOLERANCE)
        assert segment.end == pytest.approx(end, abs=TOLERANCE)


def test_energy_survives_background_noise(tmp_path: Path) -> None:
    wav = tone_bursts(
        tmp_path / "noisy.wav", speech=1.0, silence=1.0, repeats=2, noise=True
    )
    duration = wav_duration(wav)
    segments = EnergyDetector().detect(
        wav, duration=duration, settings=DetectorSettings(threshold_db=-30.0)
    )
    truth = [(0.0, 1.0), (2.0, 3.0)]
    assert len(segments) == len(truth)
    for segment, (start, end) in zip(segments, truth, strict=True):
        assert segment.start == pytest.approx(start, abs=TOLERANCE)
        assert segment.end == pytest.approx(end, abs=TOLERANCE)


def test_vad_boundaries_are_within_50ms(tmp_path: Path, speech_wav: Path) -> None:
    wav = tmp_path / "speech_pattern.wav"
    truth = speech_pattern(wav, speech_wav, silence=1.0, repeats=2)
    duration = wav_duration(wav)

    segments = VadDetector().detect(wav, duration=duration, settings=SETTINGS)
    assert segments, "VAD found no speech in a real speech fixture"

    for start, end in truth:
        match = best_matching(segments, start, end)
        assert match.start == pytest.approx(start, abs=TOLERANCE)
        assert match.end == pytest.approx(end, abs=TOLERANCE)


def test_energy_on_real_speech_keeps_whole_clip(
    tmp_path: Path, speech_wav: Path
) -> None:
    """Continuous speech has no pauses, so nothing should be cut."""
    duration = wav_duration(speech_wav)
    segments = EnergyDetector().detect(speech_wav, duration=duration, settings=SETTINGS)
    assert len(segments) == 1
    assert segments[0].start == pytest.approx(0.0, abs=TOLERANCE)
    assert segments[0].end == pytest.approx(duration, abs=TOLERANCE)


def test_all_silent_clip_follows_the_policy(tmp_path: Path) -> None:
    wav = all_silence(tmp_path / "silence.wav", seconds=3.0)
    request = AnalysisRequest(path=wav, duration=wav_duration(wav), has_audio=True)

    kept = analyze_clip(
        request, settings=SETTINGS, detector=EnergyDetector(), policy="keep"
    )
    assert [segment.as_tuple() for segment in kept.segments] == [(0.0, 3.0)]
    assert any("entirely silent" in warning for warning in kept.warnings)

    skipped = analyze_clip(
        request, settings=SETTINGS, detector=EnergyDetector(), policy="skip"
    )
    assert skipped.segments == ()

    with pytest.raises(ProcessingError, match="no-audio policy is 'error'"):
        analyze_clip(
            request, settings=SETTINGS, detector=EnergyDetector(), policy="error"
        )


def test_video_without_audio_is_reported_not_fatal(tmp_path: Path) -> None:
    clip = video_clip(tmp_path / "noaudio.mp4", audio=None, seconds=1.0)
    media = probe_media(clip)
    assert media.audio_streams == ()

    request = AnalysisRequest(
        path=clip, duration=media.duration, has_audio=bool(media.audio_streams)
    )
    analysis = analyze_clip(
        request, settings=SETTINGS, detector=EnergyDetector(), policy="keep"
    )
    assert analysis.ok
    assert any("no audio track" in warning for warning in analysis.warnings)


def test_vfr_clip_is_analysed(tmp_path: Path) -> None:
    clip = vfr_video(tmp_path / "vfr.mp4", seconds=3.0)
    media = probe_media(clip)
    assert media.video is not None
    assert media.video.fps is not None

    analysis = analyze_clip(
        AnalysisRequest(path=clip, duration=media.duration, has_audio=True),
        settings=SETTINGS,
        detector=EnergyDetector(),
        policy="keep",
    )
    assert analysis.ok
    assert analysis.segments


def test_parallel_analysis_matches_sequential(tmp_path: Path) -> None:
    requests: list[AnalysisRequest] = []
    for index in range(3):
        wav = tone_bursts(tmp_path / f"{index}.wav", speech=0.5, silence=0.5, repeats=2)
        requests.append(AnalysisRequest(path=wav, duration=wav_duration(wav)))

    sequential = analyze_clips(
        requests, settings=SETTINGS, detector_name="energy", jobs=1
    )
    parallel = analyze_clips(
        requests, settings=SETTINGS, detector_name="energy", jobs=2
    )

    assert len(sequential.analyses) == 3
    assert len(parallel.analyses) == 3
    assert parallel.failures == ()
    assert [
        [segment.as_tuple() for segment in item.segments]
        for item in sequential.analyses
    ] == [
        [segment.as_tuple() for segment in item.segments] for item in parallel.analyses
    ]


def test_parallel_run_isolates_a_broken_file(tmp_path: Path) -> None:
    good = tone_bursts(tmp_path / "good.wav", speech=0.5, silence=0.5, repeats=2)
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not audio at all")
    requests = [
        AnalysisRequest(path=good, duration=wav_duration(good)),
        AnalysisRequest(path=broken, duration=2.0),
    ]
    batch = analyze_clips(requests, settings=SETTINGS, detector_name="energy", jobs=2)
    assert len(batch.analyses) == 2
    assert len(batch.failures) == 1
    assert batch.failures[0][0].name == "broken.wav"
    assert batch.ok_analyses[0].path.name == "good.wav"


def test_cache_hit_is_at_least_10x_faster(tmp_path: Path, speech_wav: Path) -> None:
    """Benchmarked on the VAD path: the default detector and the expensive one."""
    pytest.importorskip("onnxruntime")
    wav = tmp_path / "pattern.wav"
    speech_pattern(wav, speech_wav, silence=0.6, repeats=8)  # ~17 seconds
    duration = wav_duration(wav)
    clip = video_clip(tmp_path / "clip.mp4", audio=wav, seconds=duration)
    wav.unlink()
    request = AnalysisRequest(path=clip, duration=duration)
    cache = AnalysisCache(tmp_path / "cache")
    detector = VadDetector()

    start = time.perf_counter()
    first = analyze_clip(request, settings=SETTINGS, detector=detector, cache=cache)
    uncached = time.perf_counter() - start

    start = time.perf_counter()
    second = analyze_clip(request, settings=SETTINGS, detector=detector, cache=cache)
    cached = time.perf_counter() - start

    assert first.cached is False
    assert second.cached is True
    assert [s.as_tuple() for s in first.segments] == [
        s.as_tuple() for s in second.segments
    ]
    assert cached * 10 <= uncached, (
        f"cached run took {cached:.4f}s vs uncached {uncached:.4f}s "
        f"(expected at least 10x faster)"
    )
