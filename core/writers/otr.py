"""oTranscribe ``.otr`` writer.

Delegates the actual serialisation to ``core.integrations.otranscribe``, the
single source of truth for the .otr format (also used by the app's
"Export -> oTranscribe" menu action and the download pipeline's .otr
sidecar export). The .otr format has no speaker field, so a diarised
segment's ``Speaker: `` label goes at the start of its text.
"""
from __future__ import annotations

from ..integrations.otranscribe import segments_to_otr
from .base import labelled_text, replace_lone_surrogates, speaker_prefix


def write(segments: list[dict], audio_path: str = "") -> str:
    labelled = [
        {**seg, "text": labelled_text(seg)}
        if isinstance(seg, dict) and speaker_prefix(seg) else seg
        for seg in segments
    ]
    # The media name and every body go into the JSON as they are.
    return replace_lone_surrogates(segments_to_otr(labelled, media_filename=audio_path))
