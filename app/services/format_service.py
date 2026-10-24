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
import re
import subprocess
from queue import Empty
from typing import TYPE_CHECKING, Any

from app.i18n import _
from app.domain.cookies import (
    cookies_from_browser_args,
    is_cookie_extraction_error,
    login_required_hint,
)
from core import offline, yt_dlp_update
from core._proc import new_session_kwargs
from core.integrations import smtv as smtv_mod
from core.js_runtime import (
    mentions_missing_js_runtime,
    missing_js_runtime_hint,
    yt_dlp_js_args,
)

if TYPE_CHECKING:
    from app.app import App

logger = logging.getLogger(__name__)

# Pseudo-language keys yt-dlp's ``subtitles`` / ``automatic_captions`` dicts
# can carry that are not a real caption track (e.g. a live stream's chat
# replay) -- excluded so they never look like an available caption language.
_NON_LANGUAGE_CAPTION_KEYS = frozenset({"live_chat"})


def caption_lang_map(payload: dict) -> dict[str, str]:
    """Map caption language code -> ``"manual"`` or ``"auto"`` from a yt-dlp info dict.

    Reads the ``subtitles`` (creator-provided) and ``automatic_captions``
    (ASR) keys already present in the JSON the format lookup fetches, so
    checking "is language X available as a caption" needs no extra network
    call. A code present in both wins as ``"manual"`` -- matching yt-dlp's
    own behaviour when both ``--write-subs`` and ``--write-auto-subs`` are
    requested together for the same language (see the decision log in
    ``docs/auto-subtitles-feature.md``).
    """
    result: dict[str, str] = {}
    auto_caps = payload.get("automatic_captions")
    if isinstance(auto_caps, dict):
        for code in auto_caps:
            if code not in _NON_LANGUAGE_CAPTION_KEYS:
                result[code] = "auto"
    manual_subs = payload.get("subtitles")
    if isinstance(manual_subs, dict):
        for code in manual_subs:
            if code not in _NON_LANGUAGE_CAPTION_KEYS:
                result[code] = "manual"
    return result


_LINK_RE = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*://\S+"           # https://..., ftp://...
    r"|www\.\S+"                              # www.example.com/...
    r"|[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:[/?#]\S*)?"  # youtu.be/x, example.com
    r"|[A-Za-z0-9_-]{11}"                     # a bare YouTube video id
    r"|ytsearch\d*:.+)$",                     # a yt-dlp search
    re.IGNORECASE,
)


def looks_like_link(text: str) -> bool:
    """True when ``text`` can be a video link: an address with a scheme, a "www." or
    "site.tld/..." address, a bare 11-character YouTube id or a yt-dlp search. Plain words
    ("hello world") are not looked up. No Tk."""
    return bool(_LINK_RE.match((text or "").strip()))


def not_a_link_text() -> str:
    return _("That is not a video link. Copy the full address (it starts with https://) "
             "from your browser and paste it here.")


class FormatService:
    def __init__(self, app: "App") -> None:
        self.app = app

    def schedule_lookup(self) -> None:
        if self.app.format_lookup_after:
            self.app.after_cancel(self.app.format_lookup_after)
        # The link changed: the previous link's formats and error no longer apply. Without this,
        # Download (or Enter) within the 800 ms wait queued the new link with the old link's
        # formats (review, 2026-10-21); now it says the formats are still loading.
        self.app.audio_format_map = {}
        self.app.video_format_map = {}
        self.app.format_lookup_error = ""
        # The previous link's title, language and caption tracks go with its formats: the
        # "Use the subtitles" button built from them stayed on and queued the new link under
        # the old link's title, language and caption kind within the same wait.
        self.app.current_video_title = ""
        self.app.current_video_language = ""
        self.app.current_video_caption_langs = {}
        self.app.format_lookup_after = self.app.after(800, self.lookup_formats)
        if hasattr(self.app, "update_caption_shortcut_state"):
            self.app.update_caption_shortcut_state()

    def lookup_formats(self) -> None:
        url = smtv_mod.clean_url(self.app.download_url_var.get())
        self.app.format_lookup_after = None
        self.app.audio_format_map = {}
        self.app.video_format_map = {}
        self.app.current_video_title = ""
        self.app.current_video_language = ""
        self.app.current_video_caption_langs = {}
        self.app.format_lookup_error = ""
        if hasattr(self.app, "update_caption_shortcut_state"):
            self.app.update_caption_shortcut_state()
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
        # Offer the Deno install for a YouTube link when yt-dlp has no JS
        # runtime (hides the button again for any other / empty URL).
        prompt = getattr(self.app, "update_js_runtime_prompt", None)
        if callable(prompt):
            prompt(url)
        # The previous link's "video length 0:00:19" and sliders stayed after an emptied link,
        # plain words or a failed lookup (review, 2026-10-21); a read link sets them again.
        try:
            self.app.set_download_duration(0.0)
        except AttributeError:
            pass
        if not url:
            self.app.format_status_var.set(_("Paste a video link above to load its formats"))
            return
        if not looks_like_link(url):
            # Plain text ("hello world") went to yt-dlp, whose raw "ERROR: [generic] ..." came back
            # twice (review, 2026-10-21): say it in words, without a lookup.
            text = not_a_link_text()
            self.app.format_status_var.set(text)
            self.app.format_lookup_error = text
            return
        if offline.is_offline():
            # The lookup runs yt-dlp (or SMTV) against the site at once.
            text = offline.refused("looking up this link")
            self.app.format_status_var.set(text)
            self.app.format_lookup_error = text
            return

        if smtv_mod.parse_episode_id(url) is not None:
            self._lookup_smtv(url)
            return

        self.app.format_status_var.set(_("Loading formats..."))
        # Read on the Tk thread; the lookup thread only uses the copy.
        cookie_args = cookies_from_browser_args(
            self.app.app_config.get("cookies_from_browser", "")
        )

        def _probe(extra: list[str]) -> subprocess.CompletedProcess[str]:
            # Resolved here, on the lookup thread, after any running update of
            # the user-writable yt-dlp copy has finished (core.yt_dlp_update).
            yt_dlp_update.wait_while_updating()
            yt_dlp = self.app.yt_dlp_path()
            cmd = [yt_dlp]
            # Deno for YouTube's JS challenges (core.js_runtime); [] when
            # absent. Resolved here, on the lookup thread: the first call
            # asks yt-dlp for its version.
            js_args = yt_dlp_js_args(yt_dlp)
            # Only pass --ffmpeg-location when a bundled ffmpeg dir is
            # known; an empty value points yt-dlp at the cwd instead of
            # letting it discover ffmpeg on PATH (Linux/macOS without a
            # bundled binary). Mirrors download_service's guard.
            bin_path = self.app.bin_path()
            if bin_path:
                cmd += ["--ffmpeg-location", bin_path]
            cmd += [
                *js_args,
                *extra,
                "--dump-single-json",
                "--no-playlist",
                "--no-warnings",
                # End-of-options: this probe auto-fires on paste, so a
                # "URL" starting with '-' must not be read as a flag
                # (e.g. --exec → arbitrary command execution).
                "--",
                url,
            ]
            return subprocess.run(
                cmd,
                cwd=os.path.dirname(os.path.abspath(self.app.entry_file)),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                # One probe took ~30 s on a macOS 10.15 machine (onefile
                # yt-dlp unpacking + Deno solving YouTube's challenge).
                timeout=120,
                # No console window: from the windowed app every lookup popped a
                # black yt-dlp window over it (click-through test, 2026-10-21).
                **new_session_kwargs(),
            )

        def run() -> None:
            try:
                # Same browser cookies the download itself uses: without
                # them a login-walled link (Instagram, Facebook, age-gated
                # YouTube) failed the lookup even with cookies configured.
                r = _probe(cookie_args)
                if (
                    r.returncode
                    and cookie_args
                    and is_cookie_extraction_error(r.stderr or r.stdout or "")
                ):
                    # The browser's cookie jar could not be read (Chrome/Edge
                    # still open on Windows, DPAPI). Public links don't need
                    # it -- same fallback as the download service.
                    r = _probe([])
                if r.returncode:
                    # Strip before choosing: a stderr of only blank lines must
                    # not hide the stdout text or the fallback.
                    reason = (r.stderr or "").strip() or (r.stdout or "").strip()
                    raise RuntimeError(reason or "yt-dlp could not read this URL")
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
        if not audio_map:
            # No mp3 on the page yet (the site adds it weeks after the video): the
            # audio-only download takes the sound out of a video file instead.
            source = smtv_mod.audio_choice(episode)
            if source is not None:
                audio_map["Audio (taken from the video)"] = {
                    "kind": "smtv",
                    "mode": smtv_mod.AUDIO_FROM_VIDEO,
                    "quality": source.quality,
                    "url": source.download_url,
                }

        app.audio_format_map = audio_map
        app.video_format_map = video_map
        app.current_video_title = episode.title
        app.current_video_language = episode.lang_prefix
        # SMTV downloads from the site's own server (DownloadService._run_smtv_task;
        # the page text it saves is a description, not a transcript) -- the
        # "use captions instead" shortcut is yt-dlp-specific and never offered here.
        app.current_video_caption_langs = {}
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
        try:
            app.update_caption_shortcut_state()
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
                        app.format_status_var.set(_("Could not read formats for this URL"))
                        # English: also the reason the download warning and the log quote.
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
        if url != smtv_mod.clean_url(app.download_url_var.get()):
            return

        if kind == "error":
            cfg = getattr(app, "app_config", None) or {}
            hint = login_required_hint(str(payload), cfg.get("cookies_from_browser", ""))
            if not hint and mentions_missing_js_runtime(str(payload)):
                hint = missing_js_runtime_hint(app.yt_dlp_path())
            app.format_status_var.set(f"{hint}\n{payload}" if hint else payload)
            app.format_lookup_error = str(payload)
            if getattr(app, "pending_link_start", "") == url:
                app.pending_link_start = ""
                app.log("The link could not be read, so its download did not start; see the "
                        "message on the Download Videos tab.")
            offer = getattr(app, "offer_yt_dlp_update", None)
            if callable(offer) and yt_dlp_update.should_offer_update(str(payload)):
                offer(str(payload))
            app.current_video_caption_langs = {}
            if hasattr(app, "update_caption_shortcut_state"):
                app.update_caption_shortcut_state()
            return

        # A lookup that worked: an earlier "may be out of date" offer no longer applies.
        hide_offer = getattr(app, "hide_yt_dlp_offer", None)
        if callable(hide_offer):
            hide_offer()

        if kind == "smtv_formats":
            self._apply_smtv_formats(payload)
            self._start_pending_download(url)
            return

        if not isinstance(payload, dict):
            # Defence-in-depth: run() already rejects non-dict JSON, but a
            # future event source must not be able to crash the handler.
            raise RuntimeError(f"format payload is not a dict: {type(payload).__name__}")

        # The labels are only this lookup's map keys (the choice is never saved
        # or matched by its text elsewhere), so the shown label can be translated.
        best_audio, best_video = _("Best audio"), _("Best video")
        audio_values = [best_audio]
        video_values = [best_video]
        app.audio_format_map = {best_audio: {"kind": "best_audio"}}
        app.video_format_map = {best_video: {"kind": "best_video"}}
        app.current_video_title = payload.get("title", "")
        lang = payload.get("language") or ""
        if not lang:
            # Same guard as caption_lang_map: anything but an object is no list of languages.
            auto_caps = payload.get("automatic_captions")
            lang = next(iter(auto_caps), "") if isinstance(auto_caps, dict) else ""
        app.current_video_language = lang
        app.current_video_caption_langs = caption_lang_map(payload)

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
        title = str(payload.get("title") or "").strip()
        if (audio_values or video_values) and title:
            # Which video the link is: the counts said nothing a person checks (review, 2026-10-21).
            from app.widgets.tabs import clock_length, elide_middle

            seconds = payload.get("duration")
            if isinstance(seconds, (int, float)) and seconds > 0:
                app.format_status_var.set(_("Found: {title} ({length})", title=elide_middle(title, 70),
                                            length=clock_length(float(seconds))))
            else:
                app.format_status_var.set(_("Found: {title}", title=elide_middle(title, 70)))
        elif audio_values or video_values:
            app.format_status_var.set(_(
                "{audio} audio and {video} video formats loaded",
                audio=len(audio_values), video=len(video_values),
            ))
        else:
            app.format_status_var.set(_("No formats found"))
        app.update_caption_shortcut_state()
        self._start_pending_download(url)

    def _start_pending_download(self, url: str) -> None:
        """Start the download a Transcribe-button link is waiting for, once its formats are in."""
        app = self.app
        if not url or getattr(app, "pending_link_start", "") != url:
            return
        app.pending_link_start = ""
        app.after(0, app.add_download)
