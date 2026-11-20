"""VAD framing, detector plumbing and backend failure messages."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import autocut.analysis.vad as vad_module
from autocut.analysis.base import DetectorSettings, DetectorUnavailableError
from autocut.analysis.vad import (
    SileroScorer,
    VadDetector,
    WebRtcScorer,
    frames_to_segments,
)

BASE = DetectorSettings()


class StubScorer:
    """Deterministic probabilities, one per frame, no audio decoding."""

    frame_samples = 512
    sample_rate = 16000

    def __init__(self, probabilities: list[float]) -> None:
        self._probabilities = probabilities
        self.calls = 0

    def probabilities(self, chunks: Iterator[bytes]) -> Iterator[float]:
        self.calls += 1
        for chunk in chunks:  # drain so the pipeline mirrors real use
            del chunk
        yield from self._probabilities


def test_frames_to_segments_builds_contiguous_runs() -> None:
    segments = frames_to_segments(
        [0.9, 0.8, 0.1, 0.2, 0.95], frame_seconds=0.032, threshold=0.5, duration=1.0
    )
    assert [(round(s.start, 3), round(s.end, 3)) for s in segments] == [
        (0.0, 0.064),
        (0.128, 0.16),
    ]


def test_frames_to_segments_closes_a_trailing_run_at_the_duration() -> None:
    segments = frames_to_segments(
        [0.9, 0.9], frame_seconds=0.032, threshold=0.5, duration=0.05
    )
    assert [(round(s.start, 3), round(s.end, 3)) for s in segments] == [(0.0, 0.05)]


def test_frames_to_segments_without_speech_is_empty() -> None:
    assert (
        frames_to_segments([0.1, 0.2], frame_seconds=0.032, threshold=0.5, duration=1.0)
        == []
    )


def test_vad_detector_uses_the_injected_scorer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        vad_module,
        "stream_pcm",
        lambda _path, **_kwargs: iter([b"\x00\x00" * 1024]),
    )
    scorer = StubScorer([0.9] * 10 + [0.0] * 10)
    detector = VadDetector(scorer=scorer)
    segments = detector.detect(tmp_path / "x.wav", duration=0.64, settings=BASE)
    assert scorer.calls == 1
    assert [(round(s.start, 3), round(s.end, 3)) for s in segments] == [(0.0, 0.32)]


def test_vad_detector_reports_its_backend_version() -> None:
    assert VadDetector(scorer=StubScorer([])).version.startswith("custom-")
    assert VadDetector().version.startswith("silero")


def test_silero_scorer_reports_a_missing_model(tmp_path: Path) -> None:
    scorer = SileroScorer(model_path=tmp_path / "missing.onnx")
    with pytest.raises(DetectorUnavailableError, match="model is missing"):
        scorer._load()


def test_webrtcvad_scorer_reports_the_install_hint() -> None:
    try:
        import webrtcvad  # noqa: F401
    except ImportError:
        with pytest.raises(
            DetectorUnavailableError, match="webrtcvad is not installed"
        ):
            WebRtcScorer()
    else:  # pragma: no cover - the module is absent on Windows ARM64
        assert WebRtcScorer().frame_samples == 320


def test_default_scorer_falls_back_with_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(self: SileroScorer) -> None:
        raise DetectorUnavailableError("no onnxruntime")

    monkeypatch.setattr(SileroScorer, "_load", unavailable)

    def no_webrtc(mode: int = 3) -> None:
        raise DetectorUnavailableError("webrtcvad is not installed")

    monkeypatch.setattr(vad_module, "WebRtcScorer", lambda mode=3: no_webrtc(mode))
    with pytest.raises(DetectorUnavailableError, match="webrtcvad is not installed"):
        vad_module.default_scorer()


def test_silero_model_ships_with_the_package() -> None:
    from autocut.analysis.vad import MODEL_PATH

    assert MODEL_PATH.exists(), f"bundled Silero model missing at {MODEL_PATH}"
    assert MODEL_PATH.stat().st_size > 1_000_000


def test_bundled_model_path_uses_the_pyinstaller_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = tmp_path / "autocut" / "analysis" / "models" / "silero_vad.onnx"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b"model")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert vad_module.bundled_model_path() == frozen


def test_bundled_model_path_falls_back_to_the_source_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An incomplete bundle must not shadow the real model.
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    source = Path(vad_module.__file__).parent / "models" / "silero_vad.onnx"
    assert vad_module.bundled_model_path() == source
