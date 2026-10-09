"""File extensions the app treats as audio/video it can transcribe.

One list for the places that pair a transcript with its media: a viewer finds
``talk.mts`` next to ``talk.json`` exactly when the folder watcher would have
transcribed ``talk.mts`` in the first place. ``tests/core/test_media_types.py``
fails when ``core.watcher`` accepts an extension this tuple lacks.
"""
from __future__ import annotations

# Most common first: a folder holding both ``talk.mp4`` and ``talk.mp3`` pairs
# the JSON with the video.
MEDIA_EXTENSIONS: tuple[str, ...] = (
    ".mp4", ".mp3", ".wav", ".m4a", ".mkv", ".webm", ".flac", ".ogg", ".aac",
    ".opus", ".mov", ".m4v", ".avi", ".wma", ".ts", ".wmv", ".mka", ".oga",
    ".mpg", ".mpeg", ".3gp",
    # Broadcast / camcorder / DVD video, AIFF audio and Flash video.
    ".aiff", ".flv", ".m2ts", ".mts", ".vob",
)
