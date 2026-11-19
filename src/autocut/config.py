"""Validated settings, loaded from a TOML file and overridden by the CLI.

``extra="forbid"`` makes a typo in the config file a clear input error instead of
a silently ignored key. Only settings that this build actually uses are modelled;
later milestones add their own groups.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from autocut.analysis.base import DetectorSettings
from autocut.errors import InputError
from autocut.render.ffmpeg import RenderSettings

NumberRuleName = Literal["natural", "first", "last", "regex"]
DetectorName = Literal["energy", "vad"]
AudioPolicyName = Literal["keep", "skip", "error"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class OrderingSettings(_Model):
    """How filenames are numbered and read from disk (brief 3.1)."""

    number_rule: NumberRuleName = "natural"
    number_regex: str | None = None
    recursive: bool = False
    unnumbered_policy: Literal["end", "error"] = "end"

    @model_validator(mode="after")
    def _regex_required_with_rule(self) -> OrderingSettings:
        if self.number_rule == "regex" and not self.number_regex:
            raise ValueError("number_regex is required when number_rule is 'regex'")
        return self


class AnalysisSettings(_Model):
    """Silence detection and post-processing (brief 3.2)."""

    detector: DetectorName = "vad"
    threshold_db: float = -35.0
    min_silence: float = Field(default=0.5, ge=0.0)
    min_speech: float = Field(default=0.15, ge=0.0)
    speech_probability: float = Field(default=0.5, ge=0.0, le=1.0)
    pad_before: float = Field(default=0.18, ge=0.0)
    pad_after: float = Field(default=0.28, ge=0.0)
    shrink_pauses_to: float | None = Field(default=None, ge=0.0)
    trim_head_tail: bool = False
    denoise_for_analysis: bool = False
    audio_track: int | None = None
    no_audio_policy: AudioPolicyName = "keep"

    def to_detector_settings(self) -> DetectorSettings:
        try:
            return DetectorSettings(
                threshold_db=self.threshold_db,
                min_silence=self.min_silence,
                min_speech=self.min_speech,
                speech_probability=self.speech_probability,
                pad_before=self.pad_before,
                pad_after=self.pad_after,
                shrink_pauses_to=self.shrink_pauses_to,
                trim_head_tail=self.trim_head_tail,
                denoise_for_analysis=self.denoise_for_analysis,
                audio_track=self.audio_track,
            )
        except ValueError as exc:  # pragma: no cover - pydantic validates first
            raise InputError(f"invalid analysis settings: {exc}") from exc

    def as_cutlist_payload(self) -> dict[str, Any]:
        return dict(self.model_dump(mode="json"))


class RunSettings(_Model):
    """Run-wide behaviour."""

    strict: bool = False
    strict_warnings: bool = False
    jobs: int = 0
    full_hash: bool = False


class CacheSettings(_Model):
    """Analysis cache location and switch."""

    enabled: bool = True
    directory: Path | None = None


class RenderConfig(_Model):
    """Encoder and assembly choices for the FFmpeg render."""

    codec: str = "libx264"
    crf: int = Field(default=18, ge=0, le=63)
    preset: str = "medium"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    crossfade_ms: int = Field(default=10, ge=0, le=5000)
    hardware: bool = True
    faststart: bool = True
    encoder: str | None = None

    def to_render_settings(self) -> RenderSettings:
        return RenderSettings(
            codec=self.codec,
            crf=self.crf,
            preset=self.preset,
            audio_codec=self.audio_codec,
            audio_bitrate=self.audio_bitrate,
            crossfade_ms=self.crossfade_ms,
            hardware=self.hardware,
            faststart=self.faststart,
            encoder=self.encoder,
        )


class ExportSettings(_Model):
    """Timeline export conventions."""

    edl_drop_frame: bool | None = None
    title: str | None = None


class LogSettings(_Model):
    level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    file: Path | None = None


class Config(_Model):
    ordering: OrderingSettings = Field(default_factory=OrderingSettings)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    render: RenderConfig = Field(default_factory=RenderConfig)
    export: ExportSettings = Field(default_factory=ExportSettings)
    run: RunSettings = Field(default_factory=RunSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    log: LogSettings = Field(default_factory=LogSettings)


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "config"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def load_config(path: Path | None) -> Config:
    """Load a TOML config file, or return defaults when no path is given."""
    if path is None:
        return Config()

    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise InputError(f"config file does not exist: {config_path}")
    if not config_path.is_file():
        raise InputError(f"config path is not a file: {config_path}")

    try:
        raw: dict[str, Any] = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read config file {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise InputError(f"invalid TOML in {config_path}: {exc}") from exc

    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise InputError(
            f"invalid config file {config_path}: {_format_validation_error(exc)}"
        ) from exc


def apply_overrides(config: Config, overrides: dict[str, Any]) -> Config:
    """Apply CLI overrides, dropping the ones the user did not pass.

    Values are validated by the pydantic models, so a bad value is reported as an
    input error with the offending field named.
    """
    try:
        for dotted, value in overrides.items():
            if value is None:
                continue
            section, _, field = dotted.partition(".")
            if not field:
                setattr(config, section, value)
            else:
                setattr(getattr(config, section), field, value)
    except ValidationError as exc:
        raise InputError(_format_validation_error(exc)) from exc
    return config
