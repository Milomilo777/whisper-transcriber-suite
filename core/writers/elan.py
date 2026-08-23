"""ELAN Annotation Format ``.eaf`` writer (and parser helper).

Produces a minimal but schema-valid EAF 3.0 document: a ``TIME_ORDER``
holding one ``TIME_SLOT`` per distinct segment boundary (millisecond
``TIME_VALUE``s), and a single ``TIER`` of ``ALIGNABLE_ANNOTATION``s that
reference those slots and carry the segment text.

ELAN (https://archive.mpi.nl/tla/elan) opens this directly: File -> Open.

Stdlib only (``xml.etree.ElementTree``).
"""
from __future__ import annotations

from xml.etree import ElementTree as ET

from .base import normalize_text, sanitize_for_xml, speaker_prefix

TIER_ID = "default"
LINGUISTIC_TYPE_REF = "default-lt"


def _ms(seconds: object) -> int:
    """Coerce a segment timestamp to a non-negative millisecond int."""
    try:
        f = float(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    if f != f or f < 0:  # NaN check + negative clamp
        return 0
    return int(round(f * 1000))


def write(segments: list[dict], audio_path: str = "") -> str:
    """Return the ``.eaf`` XML body for *segments*.

    Each segment becomes one ``TIME_SLOT`` pair (start/end) and one
    ``ALIGNABLE_ANNOTATION`` in a single tier. Empty-text segments are
    skipped (mirroring the other writers' treatment of blank cues).
    """
    root = ET.Element("ANNOTATION_DOCUMENT", {
        "AUTHOR": "whisper-transcriber-suite",
        "DATE": "1970-01-01T00:00:00+00:00",
        "FORMAT": "3.0",
        "VERSION": "3.0",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:noNamespaceSchemaLocation": "http://www.mpi.nl/tools/elan/EAFv3.0.xsd",
    })

    header = ET.SubElement(root, "HEADER", {
        "MEDIA_FILE": "",
        "TIME_UNITS": "milliseconds",
    })
    if audio_path:
        import os as _os
        ET.SubElement(header, "MEDIA_DESCRIPTOR", {
            "MEDIA_URL": "file:///" + _os.path.abspath(audio_path).replace("\\", "/"),
            "MIME_TYPE": "audio/x-wav",
        })

    time_order = ET.SubElement(root, "TIME_ORDER")
    tier = ET.SubElement(root, "TIER", {
        "TIER_ID": TIER_ID,
        "LINGUISTIC_TYPE_REF": LINGUISTIC_TYPE_REF,
    })

    slot_index = 0
    annotation_index = 0
    for seg in segments:
        text = sanitize_for_xml(speaker_prefix(seg) + normalize_text(seg.get("text", "")))
        if not text:
            continue
        start_ms = _ms(seg.get("start", 0.0))
        end_ms = _ms(seg.get("end", start_ms))
        if end_ms < start_ms:
            end_ms = start_ms

        slot_index += 1
        ts1 = f"ts{slot_index}"
        ET.SubElement(time_order, "TIME_SLOT", {
            "TIME_SLOT_ID": ts1, "TIME_VALUE": str(start_ms),
        })
        slot_index += 1
        ts2 = f"ts{slot_index}"
        ET.SubElement(time_order, "TIME_SLOT", {
            "TIME_SLOT_ID": ts2, "TIME_VALUE": str(end_ms),
        })

        annotation_index += 1
        annotation = ET.SubElement(tier, "ANNOTATION")
        aligned = ET.SubElement(annotation, "ALIGNABLE_ANNOTATION", {
            "ANNOTATION_ID": f"a{annotation_index}",
            "TIME_SLOT_REF1": ts1,
            "TIME_SLOT_REF2": ts2,
        })
        value = ET.SubElement(aligned, "ANNOTATION_VALUE")
        value.text = text

    # Minimal type / language / constraint scaffolding so ELAN's schema
    # validation and "Linguistic Type" panel are happy on open.
    ET.SubElement(root, "LINGUISTIC_TYPE", {
        "LINGUISTIC_TYPE_ID": LINGUISTIC_TYPE_REF,
        "TIME_ALIGNABLE": "true",
        "GRAPHIC_REFERENCES": "false",
    })
    ET.SubElement(root, "CONSTRAINT", {
        "STEREOTYPE": "Time_Subdivision",
        "DESCRIPTION": "Time subdivision of parent annotation's time interval, no time gaps allowed within this interval",
    })

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8") + "\n"
