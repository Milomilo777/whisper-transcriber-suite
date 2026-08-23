"""yt-dlp format lookup service.

Runs ``yt-dlp --dump-single-json`` in a daemon thread and posts the parsed
info dict back to the App via ``app.format_events``.

For Supreme Master TV URLs the yt-dlp probe is bypassed entirely; the
``core.integrations.smtv`` module scrapes the page once and we
populate the dropdowns from the SmtvEpisode it returns.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from queue import Empty
from typing import TYPE_CHECKING, Any

from core.integrations import smtv as smtv_mod

if TYPE_CHECKING:
    from app.app import App

logger = logging.getLogger(__name__)


class FormatService:
    def __init__(self, app: "App") -> None:
        self.app = app

    def schedule_lookup(self) -> None:
        if self.app.format_lookup_after:
            self.app.after_cancel(self.app.format_lookup_after)
        self.app.format_lookup_after = self.app.after(800, self.lookup_formats)

    def lookup_formats(self) -> None:
        url = self.app.download_url_var.get().strip()
        self.app.format_lookup_after = None
        self.app.audio_format_map = {}
        self.app.video_format_map = {}
        self.app.current_video_title = ""
        self.app.current_video_language = ""
        self.app.format_lookup_error = ""
        self.app.audio_format_combo["values"] = []
        self.app.video_format_combo["values"] = []
        self.app.audio_format_var.set("")
        self.app.video_format_var.set("")
        # Always drop the previous SMTV episode and hide the series
        # toggle. _apply_smtv_formats will re-stash and re-show them
        # if (and only if) the new lookup is an SMTV URL with
        # siblings; without this reset, a YouTube URL pasted after an
        # SMTV URL would still trigger the "Download all parts"
        # checkbox.
        self.app._smtv_episode = None  # type: ignore[attr-defined]
        toggle = getattr(self.app, "_smtv_series_toggle", None)
        if toggle is not None:
            try:
                toggle(visible=False)
            except Exception:  # noqa: BLE001
                pass
        if not url:
            self.app.format_status_var.set("Enter a URL to load available formats")
            return

        if smtv_mod.parse_episode_id(url) is not None:
            self._lookup_smtv(url)
            return

        self.app.format_status_var.set("Loading formats...")

        def run() -> None:
            try:
                cmd = [self.app.yt_dlp_path()]
                # Only pass --ffmpeg-location when a bundled ffmpeg dir is
                # known; an empty value points yt-dlp at the cwd instead of
                # letting it discover ffmpeg on PATH (Linux/macOS without a
                # bundled binary). Mirrors download_service's guard.
                bin_path = self.app.bin_path()
                if bin_path:
                    cmd += ["--ffmpeg-location", bin_path]
                cmd += [
                    "--dump-single-json",
                    "--no-playlist",
                    "--no-warnings",
                    # End-of-options: this probe auto-fires on paste, so a
                    # "URL" starting with '-' must not be read as a flag
                    # (e.g. --exec → arbitrary command execution).
                    "--",
                    url,
                ]
                r = subprocess.run(
                    cmd,
                    cwd=os.path.dirname(os.path.abspath(self.app.entry_file)),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                if r.returncode:
                    raise RuntimeError(
                        (r.stderr or r.stdout or "yt-dlp could not read this URL").strip()
                    )
                info = json.loads(r.stdout)
                # Some extractors / a captive-portal or proxy body can decode
                # to a non-object (null / list / number). The poll() handler
                # calls info.get(...), which would raise AttributeError on the
                # Tk thread and (before the self-healing reschedule) kill all
                # future format lookups. Reject it here as a normal error.
                if not isinstance(info, dict):
                    raise RuntimeError("yt-dlp returned unexpected (non-object) JSON")
                self.app.format_events.put(("formats", url, info))
            except Exception as e:  # noqa: BLE001
                self.app.format_events.put(("error", url, str(e)))

        from core._threads import safe_thread
        safe_thread(run, name="format-lookup")

    def _apply_smtv_formats(self, episode: smtv_mod.SmtvEpisode) -> None:
        """Populate the Download tab dropdowns from a parsed SMTV episode."""
        app = self.app
        # SMTV ignores time-range slicing, so disable the position sliders.
        try:
            app.set_download_duration(0.0)
        except AttributeError:
            pass
        audio_map: dict[str, dict[str, object]] = {}
        video_map: dict[str, dict[str, object]] = {}

        quality_labels = {
            "1080p": ("HD 1080p", "video-1080"),
            "720p":  ("HD 720p",  "video-720"),
            "396p":  ("SD 396p",  "video-396"),
        }
        for f in episode.files:
            if f.quality == "audio":
                audio_map["MP3 (audio only)"] = {
                    "kind": "smtv",
                    "mode": "audio",
                    "quality": "audio",
                    "url": f.download_url,
                }
            elif f.quality in quality_labels:
                label, mode = quality_labels[f.quality]
                video_map[label] = {
                    "kind": "smtv",
                    "mode": mode,
                    "quality": f.quality,
                    "url": f.download_url,
                }

        app.audio_format_map = audio_map
        app.video_format_map = video_map
        app.current_video_title = episode.title
        app.current_video_language = episode.lang_prefix
        app._smtv_episode = episode  # type: ignore[attr-defined]

        audio_values = list(audio_map.keys())
        video_values = list(video_map.keys())
        app.audio_format_combo["values"] = audio_values
        app.video_format_combo["values"] = video_values
        app.audio_format_var.set(audio_values[0] if audio_values else "")
        app.video_format_var.set(video_values[0] if video_values else "")
        try:
            app.update_download_mode()
        except Exception:  # noqa: BLE001
            pass

        sib_count = len(episode.siblings)
        suffix = f"; {sib_count} sibling part{'s' if sib_count != 1 else ''} detected" if sib_count else ""
        app.format_status_var.set(
            f"SMTV episode loaded: {len(video_values)} video / "
            f"{len(audio_values)} audio formats{suffix}"
        )
        # Surface the series-toggle checkbox if the tab built one
        toggle = getattr(app, "_smtv_series_toggle", None)
        if toggle is not None:
            try:
                toggle(visible=sib_count > 0)
            except Exception:  # noqa: BLE001
                pass

    def _lookup_smtv(self, url: str) -> None:
        """Background SMTV scrape; posts a ``smtv_formats`` event."""
        self.app.format_status_var.set("Loading SMTV formats...")

        def run() -> None:
            try:
                episode = smtv_mod.fetch_episode(url, timeout=30.0)
                self.app.format_events.put(("smtv_formats", url, episode))
            except smtv_mod.SmtvError as e:
                self.app.format_events.put(("error", url, str(e)))
            except Exception as e:  # noqa: BLE001
                self.app.format_events.put(("error", url, f"SMTV lookup failed: {e}"))

        from core._threads import safe_thread
        safe_thread(run, name="smtv-format-lookup")

    def poll(self) -> None:
        app = self.app
        # Don't pump new lookups into a tearing-down interpreter.
        if getattr(app, "_closing", False):
            return
        try:
            while True:
                try:
                    kind, url, payload = app.format_events.get_nowait()
                except Empty:
                    break
                # One malformed event must not kill the whole poll loop:
                # before this, an exception here skipped the reschedule at
                # the end and ALL future format lookups silently stopped.
                try:
                    self._handle_event(kind, url, payload)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "format poll: error handling %r event for %r", kind, url
                    )
                    try:
                        app.format_status_var.set("Could not read formats for this URL")
                        app.format_lookup_error = "Could not read formats for this URL"
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            # Always re-arm (unless shutting down) so a transient error
            # never permanently wedges format lookups.
            if not getattr(app, "_closing", False):
                app.after(200, self.poll)

    def _handle_event(self, kind: str, url: str, payload: Any) -> None:
        app = self.app
        if url != app.download_url_var.get().strip():
            return

        if kind == "error":
            app.format_status_var.set(payload)
            app.format_lookup_error = str(payload)
            return

        if kind == "smtv_formats":
            self._apply_smtv_formats(payload)
            return

        if not isinstance(payload, dict):
            # Defence-in-depth: run() already rejects non-dict JSON, but a
            # future event source must not be able to crash the handler.
            raise RuntimeError(f"format payload is not a dict: {type(payload).__name__}")

        audio_values = ["Best audio"]
        video_values = ["Best video"]
        app.audio_format_map = {"Best audio": {"kind": "best_audio"}}
        app.video_format_map = {"Best video": {"kind": "best_video"}}
        app.current_video_title = payload.get("title", "")
        lang = payload.get("language") or ""
        if not lang:
            auto_caps = payload.get("automatic_captions") or {}
            lang = next(iter(auto_caps.keys()), "") if auto_caps else ""
        app.current_video_language = lang

        for fmt in payload.get("formats", []):
            format_id = str(fmt.get("format_id", ""))
            ext = fmt.get("ext") or "unknown"
            resolution = fmt.get("resolution") or (
                f"{fmt.get('width')}x{fmt.get('height')}"
                if fmt.get("width") and fmt.get("height")
                else ""
            )
            note = fmt.get("format_note") or ""
            acodec = fmt.get("acodec") or ""
            vcodec = fmt.get("vcodec") or ""
            if not format_id:
                continue

            if acodec and acodec != "none" and (not vcodec or vcodec == "none"):
                abr = f"{fmt.get('abr')}k" if fmt.get("abr") else ""
                label = " | ".join(p for p in (format_id, ext, note, abr, f"a:{acodec}") if p)
                if label not in app.audio_format_map:
                    audio_values.append(label)
                    app.audio_format_map[label] = {"kind": "format_id", "format_id": format_id}

            if vcodec and vcodec != "none":
                fps = f"{fmt.get('fps')}fps" if fmt.get("fps") else ""
                label = " | ".join(
                    p for p in (format_id, ext, resolution, note, fps, f"v:{vcodec}") if p
                )
                if label not in app.video_format_map:
                    video_values.append(label)
                    app.video_format_map[label] = {"kind": "format_id", "format_id": format_id}

        app.audio_format_combo["values"] = audio_values
        app.video_format_combo["values"] = video_values
        if audio_values:
            app.audio_format_var.set(audio_values[0])
        if video_values:
            app.video_format_var.set(video_values[0])
        # Feed the probed video length to the Download-tab position
        # sliders (0 / missing → live or unknown → sliders disabled).
        duration = payload.get("duration")
        try:
            app.set_download_duration(float(duration) if duration else 0.0)
        except (AttributeError, TypeError, ValueError):
            pass
        app.update_download_mode()
        if audio_values or video_values:
            app.format_status_var.set(
                f"{len(audio_values)} audio and {len(video_values)} video formats loaded"
            )
        else:
            app.format_status_var.set("No formats found")
