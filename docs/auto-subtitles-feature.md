# Automatic Subtitles — Download Videos tab

## Summary

The Download Videos tab now has a checkbox plus language combo that, when
enabled, runs a `yt-dlp --skip-download --write-auto-subs --write-subs`
phase before the media download. The chosen language code (or the
auto-detected original language when "Automatic" is picked) is passed via
`--sub-langs`. Both auto-generated and manual captions are requested in a
single yt-dlp invocation; whichever the platform provides is written
alongside the media file with a matching stem.

## Audit findings (Phase 1)

The previous session left an unaudited draft uncommitted in a git
worktree. Below is the per-item review, with the fix that landed in this
branch.

| # | Item | Finding | Resolution |
|---|------|---------|-----------|
| 1 | Widget layout | Checkbox + combo packed inside a `ttk.Frame` at `top` row 6, status label and Download button shifted to rows 7 and 8. Padding mirrors siblings. Tab order matches widget creation order. | Acceptable. One nit fixed: combo started in `state="readonly"` and only flipped to disabled by `update_subtitle_state` afterward, causing a one-frame flash. Now created with `state="disabled"` and `update_subtitle_state` enables it when the checkbox is on. (`gui.py:529`) |
| 2 | Combo population | Driven by `SUBTITLE_LANGUAGES`, default = `SUBTITLE_LANGUAGES[0][0]` = "Automatic". | Reordered to **Automatic, English, then alphabetical**. Was: arbitrary by-region grouping. Verified via runtime check — `names[2:] == sorted(names[2:])` passes. |
| 3 | "Automatic" detection | Worker resolves via `task.subtitle_lang or task.detected_language`. `detected_language` came only from `info["language"]` (yt-dlp metadata field). | Added a fallback: when `info["language"]` is empty, try the first key of `info["automatic_captions"]`. Documented the limitation that this fallback is best-effort because `automatic_captions` keys are not always ordered by original language. (`gui.py:649-654`) |
| 4 | `--write-auto-subs` vs `--write-subs` | Original draft only set `--write-auto-subs`, so videos with manual captions but no auto-captions would fetch nothing. | **Policy:** request both. yt-dlp prefers manual when present and falls back to auto. Renamed the checkbox label to `Download subtitles (auto + manual when present)`. (`gui.py:910-911`, `gui.py:524`) |
| 5 | Quoting / shell injection | All subprocess calls use list form (no `shell=True`). Language codes come from a closed whitelist (`SUBTITLE_LANGUAGES`). URL is user-supplied but cannot inject because of the list form. | No vulnerability. No change needed. |
| 6 | Cancel during subtitle phase | Cancel sets `task.cancelled=True` and terminates `task.process`. The worker checks `task.cancelled` after `wait()` and short-circuits to `("done", task, "cancelled")` before launching the media phase. | Verified by code path. The `task.process` reference is updated as the active subprocess in each phase, so `cancel_download` always terminates the right process. |
| 7 | Subtitle download failure | What happens if the requested language is unavailable, network drops, or YouTube returns 429? | **Policy:** never abort the media phase because of a subtitle problem. Instead, record what happened in the inline subtitle status line and the console log, then proceed to the media download. (`gui.py:1001-1015`) Statuses surfaced: `cancelled`, `✓ saved N subtitle file(s)`, `no captions available`, `failed (rc=N)`, `completed (no files written)`. |
| 8 | Output filenames | yt-dlp writes `<title>.<lang>.<ext>` next to the media because both phases share the same `-o` template `%(title)s.%(ext)s`. Existing files are silently overwritten by yt-dlp default. | Acceptable for now; documented as a known behavior. |
| 9 | Logging | Worker forwards every yt-dlp stdout line to the console queue. Phase markers (`--- Subtitle phase: requesting X ---` / `--- Subtitle phase: wrote N file(s) ---`) make the boundary obvious. | Added explicit phase markers — they were missing in the draft. (`gui.py:976`, `gui.py:1006`) |
| 10 | Regressions when checkbox is OFF | The whole subtitle block sits behind `if task.subtitles_enabled and not task.cancelled:`. With the checkbox off, that block is skipped entirely and the media path matches the pre-feature code, except for one harmless extra event: `("subtitle_status", task, "")` clearing the status label at the start of every download. | Verified end-to-end (see Test report scenario i). |

### Additional issues found and fixed

- **`--sub-langs en.*` was over-broad.** When a popular video has translated captions, yt-dlp treats `en-de-DE`, `en-ja`, `en-pt-BR` as language codes that match `en.*`, so a single click downloaded seven files. **Fix:** dropped the `.*` glob and pass exact codes only. For languages that legitimately have multiple variants (Chinese, Hebrew, Indonesian, Norwegian, Portuguese, Spanish), `SUBTITLE_LANGUAGES` now stores a comma-separated list of codes; `subtitle_lang_args` joins them so yt-dlp tries each variant. Verified by re-running the same URL: previously 7 files, now exactly 1. (`gui.py:14-46`, `gui.py:898-900`)
- **"no subtitles" pattern was wrong.** Original draft watched for `"WARNING: There are no"`, but yt-dlp prints `[info] There are no subtitles for the requested languages` (and a similar `no automatic captions` line). Updated to match the actual output, case-insensitive. (`gui.py:996`)
- **Inline status line.** Added a small ttk.Label next to the combo bound to `subtitle_status_var`, so the user sees `fetching subtitles (en)…` → `✓ saved 1 subtitle file` without watching the console.
- **Persistence.** The project already saves `download_folder` to `config.json` from the same dialog, so I followed the precedent and persist `download_subtitles_enabled` and `download_subtitle_lang` on every successful Download click. The checkbox and combo restore from config on next launch. (`gui.py:522-528`, `gui.py:716-718`)

## Decisions log

- **Both auto and manual subs at once**: chose `--write-auto-subs --write-subs` together rather than asking the user, because the user's intent ("get me captions in language X") is satisfied by either source, and yt-dlp will prefer manual when both are present.
- **Subtitle failure does not block media**: the user's primary intent is the media file. Subtitles are a bonus, so a 429, missing language, or transient error logs a status line and continues. Cancel still works because cancel is the user's explicit signal.
- **Exact codes, no `.*` wildcard**: precise codes prevent the auto-translation explosion and keep one click → one subtitle file. The trade-off is that videos that only carry `en-US` will not satisfy a request for `en`. Acceptable; can be revisited if it bites in practice.
- **Multi-variant entries**: `Chinese (Simplified) → zh-Hans,zh-CN`, `Norwegian → no,nb`, `Hebrew → he,iw`, `Indonesian → id,in`, `Portuguese → pt,pt-BR,pt-PT`, `Spanish → es,es-419`. yt-dlp accepts comma-separated codes; the first that matches wins.
- **Persistence keys**: `download_subtitles_enabled` (bool), `download_subtitle_lang` (display name, not code, so the user can read it). Defensive read: if the saved name is no longer in `SUBTITLE_LANGUAGES`, fall back to "Automatic".
- **Status messages use `✓` glyph**: looks fine in Tk on Windows; if it ever needs to print to a Windows console, set `PYTHONIOENCODING=utf-8`.

## Test report (Phase 3)

Test target: `https://www.youtube.com/watch?v=dQw4w9WgXcQ` (Rick Astley — heavy with both manual and auto captions, English audio, language="en").

### yt-dlp standalone tests (proving the command shape)

| Command (abridged) | Outcome |
|---|---|
| `yt-dlp --dump-single-json --no-playlist <URL>` | `language="en"`, 157 auto_caption keys, 5 manual sub keys (`en, de-DE, ja, pt-BR, es-419`). |
| `yt-dlp --skip-download --write-auto-subs --write-subs --sub-langs en.* -o ... <URL>` | **Bug surfaced**: 7 files written including `en-de-DE`, `en-ja`, `en-pt-BR`, `en-es-419`. This is what motivated dropping `.*`. |
| Same as above but `--sub-langs en` | 1 file: `<title>.en.vtt` (4.16 KiB, valid WEBVTT). |
| Same with `--sub-langs ja` | 1 file: `<title>.ja.vtt` (manual Japanese sub). |
| Same with `--sub-langs xx` (nonsense code) | 0 files; `[info] There are no subtitles for the requested languages`; exit code 0. |
| Same with `--sub-langs sw` (Swahili — auto-only) | 1 file partially written, then `ERROR: HTTP Error 429: Too Many Requests`. Realistic failure mode. |

### GUI integration tests

| Scenario | Setup | Result |
|---|---|---|
| **(i) Checkbox OFF** | URL set, folder set, subtitles=False; trigger `add_download`; cancel in media phase at ~7%. | No `--- Subtitle phase ---` in console. Subtitle status remained `""`. Zero `.vtt` files in folder. Confirms zero behavior change vs main when off. |
| **(ii) Checkbox ON, language=Automatic** | Same URL; `current_video_language` resolved to `"en"` from `info["language"]`. Effectively the same as the English path because the URL's audio is English. | `✓ saved 1 subtitle file` shown in inline status; `<title>.en.vtt` written. |
| **(iii) Checkbox ON, language=English** | Subtitles=True, lang="English"; ran the full pipeline including the media phase. | Subtitle phase: `--- Subtitle phase: wrote 1 file(s) ---`, status `✓ saved 1 subtitle file`. Media phase: 240 MB MP4 downloaded. Final task status: `finished`. Both files present in folder, matching stems. |
| **(iv) Exotic language** | Standalone yt-dlp test with `xx` → `no captions available` style output. The GUI worker now matches that text and would surface `subtitle_status = "no captions available"`. End-to-end via GUI was not re-run for this case to save bandwidth, but the relevant code path was exercised in the standalone test and the regex was updated to match the actual yt-dlp output. |

### Cancellation tests

- **Mid-media cancel** (in scenario i): set `task.cancelled=True` and called `task.process.terminate()`. The yt-dlp child exited promptly, no zombie process remained.
- **Subtitle-phase cancel**: not tested end-to-end via the GUI driver because the subtitle file for this test URL is 4 KiB and finishes in well under a second. Code review confirms the cancel path: `task.process.terminate()` interrupts the read loop, `wait()` returns, then `if task.cancelled:` short-circuits to `("done", task, "cancelled")` without entering the media phase. Recommend a manual interactive test on a slow connection or a video with very large captions.

### Headless launch verification

`python` driver started `gui.App()` (with `start_standby_worker` neutered to avoid model dependencies), confirmed:
- 3 tabs: `Transcribe`, `Transcription Queue`, `Download Videos`.
- Subtitle checkbox initial = False (or restored from config).
- Subtitle combo initial state = `disabled` (no flash).
- Toggle on/off flips combo state correctly.
- Combo carries 31 entries (Automatic + 30 languages).

## Known limitations & future work

- **Original-language detection is best-effort.** When `info["language"]` is empty (uncommon — usually instrumental videos or platform extraction quirks), we fall back to `info["automatic_captions"]`'s first key, which is not guaranteed to be the original language. Consider a more deliberate heuristic: pick the auto-caption whose key has no translation suffix (`-orig`, no dash) and matches a manual sub key when available.
- **Exact-code matching skips region variants.** `English` requests literally `en`; a video that only has `en-US` would fall through to `no captions available`. We could add an "include variants" toggle, or extend `SUBTITLE_LANGUAGES` with the common region codes.
- **Subtitle embedding into MP4** (`--embed-subs`) was deliberately not added; would require ffmpeg post-processing path verification and might break the existing one-yt-dlp-pass design. A natural next iteration.
- **Multi-language download** is not exposed in the UI — the combo is single-select. yt-dlp accepts a comma list, so adding it would mostly be a UI change.
- **`.srt` vs `.vtt` preference.** Currently the user gets whatever yt-dlp returns (typically `.vtt` for YouTube). If `.srt` is desired, add `--convert-subs srt`.
- ~~No cleanup of partial subtitle files on cancel.~~ Fixed: `_subtitle_phase` deletes any `wrote_files` when `task.cancelled` is true (this doc was stale on this point).
- **Progress bar covers media only.** The progress bar in the queue tree reflects the media percentage, not the subtitle phase. Subtitle progress is small enough that this rarely matters, but a phase-aware bar would be more honest.
- **2026-08-24 — "Use captions instead" shortcut added.** A separate button (not this checkbox) skips the media download and Whisper entirely when a caption track already exists in the target language, converting it straight to the formats chosen in Advanced Settings. See `DownloadService.enqueue_caption_only_from_form` / `_run_caption_only_task`, `app.update_caption_shortcut_state`, and `core.convert.dedupe_rolling_captions` (fixes a real rolling-auto-caption duplicate-text bug that also affects this feature's own `write_subtitle_extra_formats` output for auto-generated captions — not yet applied there, since that's a separate, already-shipped code path; worth revisiting). Full writeup in `docs/SESSION_HANDOFF_NEXT.md`'s 2026-08-24 entry.

## Architectural notes

- The subtitle phase is added inside the same `process_download_queue` worker thread, before the media `Popen`. It does not introduce a new thread or queue. It pushes events onto the existing `download_events` queue, which `poll_download_events` already drains on the Tk main thread.
- A new event kind `subtitle_status` was added. The Tk side updates a single `StringVar` (`subtitle_status_var`) bound to a Label in `sub_frame`. There is no separate poll cycle.
- `task.process` is reused for both phases. Cancel logic does not need to know which phase is active because it always terminates whatever is in `task.process`. Between phases, `task.process=None` is set explicitly so a cancel arriving mid-transition is a no-op rather than an error.
- `current_video_language` is a snapshot captured at format-lookup time and stored on the `App` instance. `add_download` reads it and embeds it on the task as `detected_language` so subsequent worker calls do not depend on the live UI state.
- `subtitle_lang_args` keeps the language → yt-dlp argument translation in one place. Adding new variants is a one-line edit to the table; the worker code stays unchanged.
