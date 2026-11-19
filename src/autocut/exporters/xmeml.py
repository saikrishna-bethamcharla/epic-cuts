"""FCP7 ``xmeml`` timeline export.

xmeml is the interchange format Premiere Pro and DaVinci Resolve both import
directly. Every keep segment becomes one video ``clipitem`` plus a matching
audio ``clipitem``, with timeline positions in sequence frames and in/out points
in the source clip's own timebase, so mixed-rate sources retime correctly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from autocut.planning.loader import LoadedClip, LoadedCutList
from autocut.planning.timebase import Timebase


def _rate(parent: ET.Element, timebase: Timebase) -> ET.Element:
    rate = ET.SubElement(parent, "rate")
    nominal = -(-timebase.num // timebase.den)
    ET.SubElement(rate, "timebase").text = str(nominal)
    ET.SubElement(rate, "ntsc").text = "TRUE" if timebase.den == 1001 else "FALSE"
    return rate


def _file_url(path: Path) -> str:
    """``file://localhost/...`` as expected by FCP7 importers."""
    posix = path.as_posix()
    if not posix.startswith("/"):
        posix = "/" + posix
    return "file://localhost" + quote(posix, safe="/:")


def _sample_characteristics(
    parent: ET.Element,
    *,
    timebase: Timebase,
    width: int,
    height: int,
) -> None:
    characteristics = ET.SubElement(parent, "samplecharacteristics")
    _rate(characteristics, timebase)
    ET.SubElement(characteristics, "width").text = str(width)
    ET.SubElement(characteristics, "height").text = str(height)
    ET.SubElement(characteristics, "anamorphic").text = "FALSE"
    ET.SubElement(characteristics, "pixelaspectratio").text = "square"
    ET.SubElement(characteristics, "fielddominance").text = "none"


def _file_element(
    parent: ET.Element,
    clip: LoadedClip,
    *,
    file_id: str,
    define: bool,
    sequence_width: int,
    sequence_height: int,
    audio_rate: int,
) -> None:
    file_element = ET.SubElement(parent, "file", id=file_id)
    if not define:
        return
    ET.SubElement(file_element, "name").text = clip.source_path.name
    ET.SubElement(file_element, "pathurl").text = _file_url(clip.source_path)
    ET.SubElement(file_element, "duration").text = str(clip.duration_frames)
    _rate(file_element, clip.timebase)
    media = ET.SubElement(file_element, "media")
    video = ET.SubElement(media, "video")
    _sample_characteristics(
        video,
        timebase=clip.timebase,
        width=clip.width or sequence_width,
        height=clip.height or sequence_height,
    )
    if clip.audio_stream is not None:
        audio = ET.SubElement(media, "audio")
        characteristics = ET.SubElement(audio, "samplecharacteristics")
        ET.SubElement(characteristics, "depth").text = "16"
        ET.SubElement(characteristics, "samplerate").text = str(audio_rate)
        ET.SubElement(audio, "channelcount").text = "2"


def _clipitem(
    track: ET.Element,
    *,
    clip: LoadedClip,
    item_id: str,
    file_id: str,
    define_file: bool,
    start: int,
    end: int,
    in_frame: int,
    out_frame: int,
    media_type: str,
    sequence_width: int,
    sequence_height: int,
    audio_rate: int,
) -> None:
    item = ET.SubElement(track, "clipitem", id=item_id)
    ET.SubElement(item, "name").text = clip.source_path.name
    ET.SubElement(item, "duration").text = str(clip.duration_frames)
    _rate(item, clip.timebase)
    ET.SubElement(item, "start").text = str(start)
    ET.SubElement(item, "end").text = str(end)
    ET.SubElement(item, "in").text = str(in_frame)
    ET.SubElement(item, "out").text = str(out_frame)
    _file_element(
        item,
        clip,
        file_id=file_id,
        define=define_file,
        sequence_width=sequence_width,
        sequence_height=sequence_height,
        audio_rate=audio_rate,
    )
    source_track = ET.SubElement(item, "sourcetrack")
    ET.SubElement(source_track, "mediatype").text = media_type
    ET.SubElement(source_track, "trackindex").text = "1"


def build_xmeml(cutlist: LoadedCutList, *, title: str | None = None) -> bytes:
    """Render an FCP7 XML sequence for every segment in the Cut List."""
    root = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(root, "sequence", id="sequence-1")
    ET.SubElement(sequence, "name").text = title or cutlist.title
    ET.SubElement(sequence, "duration").text = str(cutlist.total_frames)
    _rate(sequence, cutlist.timebase)
    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    video_format = ET.SubElement(video, "format")
    _sample_characteristics(
        video_format,
        timebase=cutlist.timebase,
        width=cutlist.width,
        height=cutlist.height,
    )
    video_track = ET.SubElement(video, "track")
    audio_media = ET.SubElement(media, "audio")
    audio_track = ET.SubElement(audio_media, "track")

    file_ids = {
        clip.order: f"file-{index + 1}" for index, clip in enumerate(cutlist.clips)
    }
    defined: set[int] = set()
    item_number = 0
    for clip in cutlist.clips:
        for segment in clip.segments:
            item_number += 1
            define_file = clip.order not in defined
            defined.add(clip.order)
            for track, media_type, suffix in (
                (video_track, "video", ""),
                (audio_track, "audio", "-audio"),
            ):
                if media_type == "audio" and clip.audio_stream is None:
                    continue
                _clipitem(
                    track,
                    clip=clip,
                    item_id=f"clipitem-{item_number}{suffix}",
                    file_id=file_ids[clip.order],
                    define_file=define_file,
                    start=segment.rec_in_frame,
                    end=segment.rec_out_frame,
                    in_frame=segment.src_in_frame,
                    out_frame=segment.src_out_frame,
                    media_type=media_type,
                    sequence_width=cutlist.width,
                    sequence_height=cutlist.height,
                    audio_rate=cutlist.audio_rate,
                )

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n"
    ).encode("utf-8")
