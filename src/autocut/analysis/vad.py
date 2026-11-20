"""VAD detector: Silero VAD via ONNX Runtime, with a webrtcvad fallback.

Silero v5 consumes 512-sample hops at 16 kHz, but the ONNX graph expects each
step as ``[64 samples of context, 512 new samples]`` (576 wide, per Silero's own
``OnnxWrapper``). Feeding raw 512-sample frames silently yields ~0.001
probability for loud speech, so the context is maintained here and covered by a
test against a real speech fixture.

A frame counts as speech at or above ``speech_probability``; contiguous speech
frames become keep segments, and everything else is shared post-processing.

The model ships with the package (``analysis/models/silero_vad.onnx``, MIT, from
snakers4/silero-vad) so no download happens at runtime. ONNX Runtime and numpy
are the optional ``vad`` extra; without them the detector reports exactly what to
install instead of failing obscurely.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol

from autocut.analysis.audio import (
    SAMPLE_RATE,
    SILERO_FRAME_SAMPLES,
    WEBRTC_FRAME_SAMPLES,
    stream_pcm,
)
from autocut.analysis.base import DetectorSettings, DetectorUnavailableError, Segment

LOGGER = logging.getLogger(__name__)

MODEL_FILENAME = "silero_vad.onnx"
MODEL_RELATIVE_PATH = Path("autocut") / "analysis" / "models" / MODEL_FILENAME
INSTALL_HINT = 'uv pip install -e ".[vad]"  (onnxruntime + numpy)'

SILERO_VERSION = "silero-vad-5-onnx"
WEBRTC_VERSION = "webrtcvad-3"
VAD_VERSION = SILERO_VERSION


def bundled_model_path() -> Path:
    """Locate the Silero model, including inside a PyInstaller one-file bundle.

    PyInstaller unpacks ``datas`` under ``sys._MEIPASS`` and keeps the package
    layout there, which is not where ``__file__`` points for a frozen module.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if isinstance(meipass, str):
        frozen = Path(meipass) / MODEL_RELATIVE_PATH
        if frozen.exists():
            return frozen
    return Path(__file__).parent / "models" / MODEL_FILENAME


MODEL_PATH = bundled_model_path()


class Scorer(Protocol):
    """Turns PCM chunks into per-frame speech probabilities."""

    frame_samples: int
    sample_rate: int

    def probabilities(self, chunks: Iterator[bytes]) -> Iterator[float]: ...


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise DetectorUnavailableError(
            f"the VAD detector needs numpy: {INSTALL_HINT}"
        ) from exc
    return np


class SileroScorer:
    """Silero VAD v5 through ONNX Runtime, one recurrent state per stream."""

    frame_samples = SILERO_FRAME_SAMPLES
    sample_rate = SAMPLE_RATE
    #: Silero's ONNX graph wants 64 samples of history in front of each hop.
    context_samples = 64

    def __init__(self, model_path: Path | None = None) -> None:
        self._model_path = Path(model_path or bundled_model_path())
        self._session: Any | None = None

    def _load(self) -> Any:
        if self._session is not None:
            return self._session
        if not self._model_path.exists():
            raise DetectorUnavailableError(
                f"the Silero VAD model is missing: {self._model_path}. "
                "Reinstall autocut or pass --detector energy."
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise DetectorUnavailableError(
                f"the VAD detector needs onnxruntime: {INSTALL_HINT}"
            ) from exc
        try:
            session = ort.InferenceSession(
                str(self._model_path), providers=["CPUExecutionProvider"]
            )
        except Exception as exc:  # pragma: no cover - corrupt model / no CPU EP
            raise DetectorUnavailableError(
                f"cannot load the Silero VAD model: {exc}"
            ) from exc
        inputs = {item.name for item in session.get_inputs()}
        if not {"input", "state", "sr"} <= inputs:
            raise DetectorUnavailableError(
                "unsupported Silero model layout (expected v5 inputs 'input', "
                f"'state' and 'sr', got {sorted(inputs)})"
            )
        self._session = session
        return session

    def probabilities(self, chunks: Iterator[bytes]) -> Iterator[float]:
        np = _numpy()
        session = self._load()
        frame_bytes = self.frame_samples * 2
        state = np.zeros((2, 1, 128), dtype=np.float32)
        rate = np.array(SAMPLE_RATE, dtype=np.int64)
        context = np.zeros(self.context_samples, dtype=np.float32)
        buffer = bytearray()

        for chunk in chunks:
            buffer.extend(chunk)
            while len(buffer) >= frame_bytes:
                frame = bytes(buffer[:frame_bytes])
                del buffer[:frame_bytes]
                samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                samples /= 32768.0
                model_input = np.concatenate([context, samples]).reshape(1, -1)
                outputs = session.run(
                    None,
                    {
                        "input": model_input,
                        "state": state,
                        "sr": rate,
                    },
                )
                state = outputs[1]
                context = samples[-self.context_samples :]
                yield float(np.ravel(outputs[0])[0])


class WebRtcScorer:
    """webrtcvad fallback: a binary decision per 20 ms frame."""

    frame_samples = WEBRTC_FRAME_SAMPLES
    sample_rate = SAMPLE_RATE

    def __init__(self, mode: int = 3) -> None:
        try:
            import webrtcvad
        except ImportError as exc:
            raise DetectorUnavailableError(
                "webrtcvad is not installed and usually needs a C compiler; "
                "install the vad extra (onnxruntime) instead"
            ) from exc
        self._vad = webrtcvad.Vad(mode)

    def probabilities(self, chunks: Iterator[bytes]) -> Iterator[float]:
        frame_bytes = self.frame_samples * 2
        buffer = bytearray()
        for chunk in chunks:
            buffer.extend(chunk)
            while len(buffer) >= frame_bytes:
                frame = bytes(buffer[:frame_bytes])
                del buffer[:frame_bytes]
                yield 1.0 if self._vad.is_speech(frame, SAMPLE_RATE) else 0.0


def default_scorer() -> Scorer:
    """Silero when available, otherwise webrtcvad, otherwise a clear error."""
    try:
        scorer = SileroScorer()
        scorer._load()
        return scorer
    except DetectorUnavailableError as exc:
        LOGGER.debug("Silero VAD unavailable (%s); trying webrtcvad", exc)
    return WebRtcScorer()


def frames_to_segments(
    probabilities: Sequence[float],
    *,
    frame_seconds: float,
    threshold: float,
    duration: float,
) -> list[Segment]:
    """Binary speech frames -> contiguous keep segments."""
    segments: list[Segment] = []
    run_start: int | None = None
    for index, probability in enumerate(probabilities):
        speech = probability >= threshold
        if speech and run_start is None:
            run_start = index
        elif not speech and run_start is not None:
            segments.append(
                Segment(
                    start=run_start * frame_seconds,
                    end=min(index * frame_seconds, duration),
                )
            )
            run_start = None
    if run_start is not None:
        segments.append(
            Segment(
                start=run_start * frame_seconds,
                end=min(len(probabilities) * frame_seconds, duration),
            )
        )
    return [segment for segment in segments if segment.duration > 0]


class VadDetector:
    """Silero (default) or webrtcvad, behind the shared Detector interface."""

    name = "vad"

    def __init__(self, scorer: Scorer | None = None) -> None:
        self._scorer = scorer
        self.version = SILERO_VERSION if scorer is None else f"custom-{VAD_VERSION}"

    @property
    def scorer(self) -> Scorer:
        if self._scorer is None:
            self._scorer = default_scorer()
        return self._scorer

    def detect(
        self, path: Path, *, duration: float, settings: DetectorSettings
    ) -> list[Segment]:
        scorer = self.scorer
        chunks = stream_pcm(
            path,
            track=settings.audio_track,
            denoise=settings.denoise_for_analysis,
        )
        probabilities = list(scorer.probabilities(chunks))
        frame_seconds = scorer.frame_samples / scorer.sample_rate
        return frames_to_segments(
            probabilities,
            frame_seconds=frame_seconds,
            threshold=settings.speech_probability,
            duration=duration,
        )
