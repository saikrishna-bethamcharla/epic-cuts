"""FCPXML 1.10 export for Final Cut Pro and Resolve.

The Cut List already carries two timebases, so each asset clip keeps its native
start point while its ``offset`` on the spine is a sequence frame. Time values
are written as exact rationals (``1001/30000s``), never decimal seconds.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from autocut.errors import InputError
from autocut.exporters.timecode import TimecodeFormat
from autocut.planning.loader import LoadedCutList
from autocut.planning.timebase import Timebase


def _time(frames: int, timebase: Timebase) -> str:
    value = Fraction(frames * timebase.den, timebase.num)
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def _format_name(height: int, timebase: Timebase) -> str:
    return f"FFVideoFormat{height}p{round(timebase.fps * 100)}"


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


def build_fcpxml(
    cutlist: LoadedCutList,
    *,
    title: str | None = None,
    drop_frame: bool | None = None,
) -> bytes:
    """Render a single-project FCPXML document for the Cut List."""
    if cutlist.total_frames <= 0:
        raise InputError("cut list has no segments to export")
    name = title or cutlist.title
    timecode = TimecodeFormat.for_timebase(cutlist.timebase, drop_frame=drop_frame)

    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")

    format_ids: dict[tuple[int, int, Timebase], str] = {}
    sequence_format_id = "r1"
    ET.SubElement(
        resources,
        "format",
        id=sequence_format_id,
        name=_format_name(cutlist.height, cutlist.timebase),
        frameDuration=_time(1, cutlist.timebase),
        width=str(cutlist.width),
        height=str(cutlist.height),
    )
    format_ids[(cutlist.width, cutlist.height, cutlist.timebase)] = sequence_format_id

    next_id = 2
    asset_ids: dict[int, str] = {}
    for clip in cutlist.clips:
        width = clip.width or cutlist.width
        height = clip.height or cutlist.height
        key = (width, height, clip.timebase)
        if key not in format_ids:
            format_id = f"r{next_id}"
            next_id += 1
            ET.SubElement(
                resources,
                "format",
                id=format_id,
                name=_format_name(height, clip.timebase),
                frameDuration=_time(1, clip.timebase),
                width=str(width),
                height=str(height),
            )
            format_ids[key] = format_id
        asset_id = f"r{next_id}"
        next_id += 1
        asset_ids[clip.order] = asset_id
        asset = ET.SubElement(
            resources,
            "asset",
            id=asset_id,
            name=clip.source_path.name,
            start="0s",
            duration=_time(clip.duration_frames, clip.timebase),
            hasVideo="1",
            format=format_ids[key],
        )
        if clip.audio_stream is not None:
            asset.set("hasAudio", "1")
            asset.set("audioSources", "1")
            asset.set("audioChannels", "2")
            asset.set("audioRate", str(cutlist.audio_rate))
        ET.SubElement(
            asset, "media-rep", kind="original-media", src=_file_url(clip.source_path)
        )

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="AutoCut")
    project = ET.SubElement(event, "project", name=name)
    sequence = ET.SubElement(
        project,
        "sequence",
        format=sequence_format_id,
        duration=_time(cutlist.total_frames, cutlist.timebase),
        tcStart="0s",
        tcFormat="DF" if timecode.drop_frame else "NDF",
        audioLayout="stereo",
        audioRate=str(cutlist.audio_rate),
    )
    spine = ET.SubElement(sequence, "spine")
    for clip in cutlist.clips:
        for segment in clip.segments:
            ET.SubElement(
                spine,
                "asset-clip",
                ref=asset_ids[clip.order],
                offset=_time(segment.rec_in_frame, cutlist.timebase),
                start=_time(segment.src_in_frame, clip.timebase),
                duration=_time(segment.frames, cutlist.timebase),
                name=clip.source_path.name,
            )

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n").encode("utf-8")
