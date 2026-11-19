"""Decode audio only, 16 kHz mono, streamed through an ffmpeg pipe.

Video is never decoded for analysis, and the whole file is never held in memory:
:func:`stream_pcm` yields fixed-size chunks as ffmpeg produces them, so a
two-hour recording costs the same as a two-second one.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from autocut.analysis.base import NoAudioStreamError
from autocut.errors import ProcessingError, ToolMissingError
from autocut.media.tools import FFMPEG, find_tool, install_hint

LOGGER = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
DEFAULT_CHUNK_SECONDS = 1.0
#: Silero VAD v5 consumes 512-sample frames at 16 kHz (32 ms).
SILERO_FRAME_SAMPLES = 512
#: webrtcvad only accepts 10/20/30 ms frames.
WEBRTC_FRAME_SAMPLES = 320

_SILENCE_MARKERS = (
    "does not contain any stream",
    "matches no streams",
    "stream map",
    "no audio",
)


def build_extract_command(
    path: Path,
    *,
    executable: str,
    track: int | None,
    sample_rate: int,
    denoise: bool,
) -> list[str]:
    """The ffmpeg argument list; kept public so tests can assert on it."""
    command = [
        executable,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        f"0:a:{0 if track is None else track}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
    ]
    if denoise:
        # Analysis only: the temporary denoise never reaches the output file.
        command += ["-af", "afftdn=nf=-25"]
    command += ["-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"]
    return command


def stream_pcm(
    path: Path,
    *,
    track: int | None = None,
    sample_rate: int = SAMPLE_RATE,
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
    denoise: bool = False,
) -> Iterator[bytes]:
    """Yield mono 16-bit PCM chunks from one audio track of ``path``."""
    executable = find_tool(FFMPEG)
    if executable is None:
        raise ToolMissingError(FFMPEG, install_hint())

    command = build_extract_command(
        path,
        executable=executable,
        track=track,
        sample_rate=sample_rate,
        denoise=denoise,
    )
    chunk_bytes = max(
        BYTES_PER_SAMPLE,
        int(sample_rate * BYTES_PER_SAMPLE * max(chunk_seconds, 0.05)),
    )
    LOGGER.debug("extracting audio: %s", " ".join(command))

    # stderr goes to a file, never a pipe: a chatty ffmpeg would otherwise
    # deadlock against a full pipe buffer while we read stdout.
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=errors,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:  # pragma: no cover - guarded by find_tool
            raise ProcessingError(f"cannot run ffmpeg: {exc}") from exc

        stdout = process.stdout
        assert stdout is not None  # narrow for type checkers
        try:
            while True:
                chunk = stdout.read(chunk_bytes)
                if not chunk:
                    break
                yield chunk
        finally:
            stdout.close()
            return_code = process.wait()

        errors.seek(0)
        detail = errors.read().decode("utf-8", errors="replace").strip()

    if return_code != 0:
        lowered = detail.lower()
        if any(marker in lowered for marker in _SILENCE_MARKERS):
            raise NoAudioStreamError(
                f"{path} has no usable audio track "
                f"(track {0 if track is None else track}); "
                "choose another track with --audio-track"
            )
        tail = detail.splitlines()[-1] if detail else f"exit code {return_code}"
        raise ProcessingError(f"cannot decode audio from {path}: {tail}")
