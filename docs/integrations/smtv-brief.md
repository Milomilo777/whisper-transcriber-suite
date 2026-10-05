# Supreme Master TV Integration — Implementation Brief

Self-contained brief for the agent half of this hands-off session.
**Read [`smtv-research.md`](smtv-research.md) first.** That note is
the *why* and the *what we found*; this brief is the *what to build*.

The work happens on the existing branch `release/single-file-exe`.
No new branch, no rebase, no force push, no merge to master.

---

## Where we are right now

| Phase                                  | Last commit on `release/single-file-exe` | Status                  |
|----------------------------------------|------------------------------------------|-------------------------|
| Method A (onefile exe pivot)           | `2b637c9`                                | done                    |
| Method B (Inno Setup installer)        | `d423d2f`                                | done, pushed to origin  |
| Phase 0 SMTV — Tk after-callback audit | `6266aab`                                | done                    |

`master` is at `25153ec` upstream. The new SMTV work is the **only**
content on this branch from now on; both deliverables (`dist\…exe`
and `dist_installer\…Setup.exe`) will need to rebuild against the
new code before we declare done.

---

## Scope

Three sub-features, one new integration module, two small services
patches, one new "kind-of-URL" recognised by the existing Download
tab. No new UI tab.

### 1. Core library — `core/integrations/smtv.py`

Stdlib-only Python module. New public surface:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class SmtvFile:
    quality: str          # "1080p" | "720p" | "396p" | "audio"
    relative_path: str    # "2026/0512/3143-BMD-…-700k.mp4"
    download_url: str     # full https URL (CDN endpoint)

@dataclass(frozen=True)
class SmtvSibling:
    url: str              # absolute https URL of /lang1/v/<id>.html
    title: str            # "… Part 2 of 7 …"
    part: int | None      # parsed N from "Part N of M"
    total: int | None     # parsed M

@dataclass(frozen=True)
class SmtvEpisode:
    vid: str              # 12-digit episode ID
    title: str            # from <title> or article-title
    page_url: str         # canonical episode URL
    lang_prefix: str      # "en", "fa", "de", …
    files: list[SmtvFile] # ordered: 1080p, 720p, 396p, audio (whichever exist)
    transcript_text: str  # plain text of div.article-text, empty string if absent
    transcript_html: str  # raw HTML of div.article-text, empty string if absent
    siblings: list[SmtvSibling]   # other parts of the same series, in N order
    poster_url: str | None
    youtube_id: str | None
    duration_seconds: int | None

# --- public functions ---

SMTV_HOST_RE = re.compile(r"^https?://(?:www\.)?suprememastertv\.com/", re.I)
SMTV_EPISODE_RE = re.compile(
    r"^https?://(?:www\.)?suprememastertv\.com/([a-z]{2,3})1/v/(\d{6,})\.html$",
    re.I,
)

def is_smtv_url(url: str) -> bool:
    """True iff `url` looks like an SMTV episode page."""

def parse_episode_id(url: str) -> tuple[str, str] | None:
    """Return (lang_prefix, vid) if `url` is a recognised episode URL; else None."""

def fetch_episode(url: str, *, timeout: float = 30.0) -> SmtvEpisode:
    """HTTP GET the page, parse, return an SmtvEpisode.

    Raises:
      SmtvError on any of: HTTP non-2xx, page missing videoPlayerData,
      empty videoFile array, captcha/Cloudflare interstitial detected.
    """

def best_url_for_mode(episode: SmtvEpisode, mode: str) -> str:
    """`mode` ∈ {'video-best', 'video-720', 'video-396', 'audio'}.
    Returns the chosen file's download_url. Raises SmtvError if the
    requested mode isn't available for this episode (e.g. asking
    'audio' on a news clip that ships video-only)."""

def filename_for(episode: SmtvEpisode, mode: str) -> str:
    """Suggested filename for the chosen mode. Uses the CDN's basename
    when available, else builds '<title>.<ext>' with safe-path
    sanitisation."""

def transcript_filename(episode: SmtvEpisode) -> str:
    """Suggested filename for the transcript text file. Mirrors
    `filename_for(episode, 'audio')` but with .txt extension; if
    audio isn't available, mirrors the first video file."""

class SmtvError(RuntimeError):
    pass
```

**Internals (module-private):**

- `_VIDEOFILE_RE = re.compile(r"""videoPlayerData\[\s*"videoFile"\s*\]\.push\(\s*new\s+Array\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)\s*\)""")`
- `_VIDEOLENGTH_RE`, `_VID_RE`, `_YID_RE`, `_POSTER_RE` — straight
  string-form parsers on the `videoPlayerData[…] = "…"` lines
- `_ARTICLE_TEXT_RE = re.compile(r'<div class="article-text" id="article-text">(.*?)</div>\s*</div>\s*</div>\s*</article>', re.S)`
- `_PLAYLIST_ANCHOR_RE = re.compile(r'<a\s+href="\.\./v/(\d+)\.html"\s+title="([^"]+)"[^>]*>([^<]+)</a>')`
- `_PART_RE = re.compile(r"\bPart\s+(\d+)\s+of\s+(\d+)\b", re.I)`
- `_CDN_PREFIX = "https://cf-vdo.suprememastertv.com/vod/video/download-mp4.php?file="`
- `_DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WhisperProject"`
- `_strip_html(html_str) -> str` — single-pass `HTMLParser` subclass
  collecting text from `<p>` blocks with `\n\n` paragraph separators.

Implementation rules:

- **Stdlib only.** `urllib.request`, `re`, `html`, `html.parser`,
  `dataclasses`, `pathlib`. Do **not** add `beautifulsoup4`, `lxml`,
  or `requests`. The bundle is the bundle.
- Always send `User-Agent: Mozilla/5.0 …`; SMTV serves a 403 to the
  default urllib UA on at least the search endpoints.
- Always honour the `timeout` parameter; the worker side wraps this
  in `try/except SmtvError` and posts a `download_events.error` event.
- `fetch_episode` does **one** GET, then parses everything from that
  response body. Do not make additional probes.
- Build absolute sibling URLs from the page's own URL (e.g. for a
  page at `/fa1/v/123.html`, sibling `../v/456.html` resolves to
  `/fa1/v/456.html`). Preserve language prefix.
- Sibling filtering: keep only siblings whose title shares the
  "Part N of M" suffix with the current episode (i.e. same `M`,
  matching series-name prefix). Drop unrelated "you might also like"
  cards.

### 2. New "kind-of-URL" handling — `app/services/download_service.py`

The existing Download tab takes an arbitrary URL into
`download_url_var`. Today `format_service.lookup_formats` runs
`yt-dlp --dump-single-json` and populates the dropdowns.

Two changes:

#### 2a. Format service — `app/services/format_service.py`

At the top of `lookup_formats(self)`:

```python
from core.integrations import smtv as smtv_mod

url = self.app.download_url_var.get().strip()
if smtv_mod.is_smtv_url(url):
    self._lookup_smtv_formats(url)
    return
```

New method `_lookup_smtv_formats(self, url)`:

- Spawn a daemon thread (same `threading.Thread(target=run, daemon=True).start()` pattern as `lookup_formats`)
- Inside the thread: call `smtv_mod.fetch_episode(url)`; on success
  put a `("smtv_formats", url, episode)` event into
  `self.app.format_events`; on error put `("error", url, str(e))`
- Add a handler in `format_service.poll`:

```python
if kind == "smtv_formats":
    self._apply_smtv_formats(payload)  # populate combos, set
                                       # current_video_title and
                                       # current_video_language
    continue
```

Where `_apply_smtv_formats` mirrors what the existing branch does
but reads from `SmtvEpisode.files`:

- `audio_format_map` keys: "MP3 (audio only)" if `audio` file exists
- `video_format_map` keys: "HD 1080p", "HD 720p", "SD 396p"
  (only those that exist), each maps to `{"kind": "smtv", "quality":
  q, "url": file.download_url}`
- `current_video_title` = `episode.title`
- `current_video_language` = `episode.lang_prefix` (so the existing
  subtitle lookup defaults to the right language code; SMTV does not
  expose .vtt files so the subtitle phase later short-circuits)

This is the only UI-visible difference for SMTV URLs: the dropdowns
get populated from our scrape instead of from yt-dlp's JSON dump.

#### 2b. Download service routing — `app/services/download_service.py`

In `DownloadService._run_task`, *before* `maybe_update_yt_dlp`,
check if the task came from an SMTV URL. The trigger is the
presence of `"kind": "smtv"` on `task.format_info["audio"]` or
`task.format_info["video"]`. If so, route to a new method:

```python
def _run_smtv_task(self, task: "VideoDownloadTask") -> None:
    """Direct CDN download for SMTV episodes.

    Bypasses yt-dlp entirely. Streams via urllib with chunked
    progress events; on completion writes the transcript text file
    next to the video. Auto-transcribe-after-download (Phase 3a)
    wires up via the existing `done_full` event with a saved_path.
    """
```

The flow:

1. Determine target URL from `task.format_info` — the same map
   `_apply_smtv_formats` populated above
2. Determine target filename via `smtv.filename_for(episode, mode)`,
   joined with `task.folder`. Use atomic write: download to
   `<filename>.part` then `os.replace` to the final name on success.
3. While streaming, post `("progress", task, percent)` events on each
   chunk boundary (chunk = 256 KiB; throttle progress to once per
   ~500 ms to avoid drowning the Tk queue)
4. On HTTP error or cancellation: cleanup the `.part` file, post
   `("error", task, message)` or `("done", task, "cancelled")`
5. On success: if `episode.transcript_text` is non-empty, write
   `<base>.txt` (UTF-8, BOM-free) **after** the video is in place
6. Post `("done_full", task, {"status": "finished", "saved_path":
   <abs_path_to_video>})` so the auto-transcribe-after-download
   wiring picks it up. The auto-transcribe code path is the same
   one the YouTube download flow uses — no changes there.

**Cancellation:** `task.cancelled` is set by the existing
`cancel_download` method. The download loop must check it on every
chunk boundary and abort cleanly.

**Series expansion:** sub-feature 1 below.

### 3. Series expansion — sub-feature 1

A new helper in `download_service.py`:

```python
def expand_smtv_series(self, episode: "SmtvEpisode",
                       chosen_mode: str,
                       folder: str) -> list["VideoDownloadTask"]:
    """Return one VideoDownloadTask per sibling (including the
    requested episode itself), in part-number order. Each task's
    format_info matches the user's chosen mode/quality."""
```

Wiring into the Download tab:

- `app/services/download_service.py::enqueue_from_form` currently
  builds **one** task and appends it. For SMTV URLs:
  - After building the task, look at `episode.siblings`.
  - If there are siblings AND the user has the new "Download all
    parts" checkbox checked (default: ON when an SMTV URL is detected),
    replace the single task with `expand_smtv_series(...)`'s list.
  - Refresh the queue and call `process_queue`.
- New checkbox lives on the Download tab next to the existing
  "Download subtitles" checkbox. Variable name:
  `smtv_download_all_parts_var` (BooleanVar, default True).
- Show/hide rule: visible only when `is_smtv_url(current_url)` is
  True. Implementation: a `bind("<KeyRelease>", …)` on the URL entry
  toggles the widget's `pack_forget()` / `pack(...)`.

### 4. MP3 — sub-feature 2

Mostly free. When `_apply_smtv_formats` populates the audio dropdown
with "MP3 (audio only)", and the user picks audio mode, the chosen
`format_info["audio"]` carries `{"kind": "smtv", "quality": "audio",
"url": "<mp3 cdn url>"}`. `_run_smtv_task` then downloads that URL
directly — no ffmpeg conversion needed because SMTV already provides
real MP3 files.

The existing output-format dropdown (`mp3`/`m4a`/`aac`/`opus`/`flac`/`wav`)
is now a polite suggestion only for YouTube downloads; for SMTV we
ignore it and always save the CDN's MP3. Document this in the
README's "What sets it apart" line.

If the episode has no MP3 (news clips), the "MP3 (audio only)" entry
is simply absent from the dropdown. The UI gives the same "Wait for
formats to load, then select an audio format" error if the user
tries to enqueue without one.

### 5. Transcript — sub-feature 3

If `episode.transcript_text` is non-empty, write `<base>.txt` next
to the downloaded media. Filename mirrors the chosen mode:

| Chosen mode | Video file                  | Transcript file              |
|-------------|-----------------------------|------------------------------|
| audio       | `…-p1o7.mp3`                | `…-p1o7.txt`                 |
| video       | `…-p1o7-720p.mp4`           | `…-p1o7-720p.txt` (same base)|

Auto-transcribe-after-download (Phase 3a) is unchanged: if the user
has it on, the saved video path lands in the transcription queue
exactly like a YouTube download would. The MP3 file is also
acceptable to faster-whisper. So the user gets *two* transcript
sources: the SMTV-provided text (verbatim from the show's
script-quality transcript), and the whisper-generated SRT/JSON.

The brief deliberately does **not** add UI for choosing between
them — both files land alongside, and the user picks at consumption
time. This keeps the change minimal.

---

## Tests — `tests/integrations/test_smtv.py`

| Test                                          | What it asserts                                                                                                                                              |
|-----------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `test_is_smtv_url_accepts_known_shapes`        | `is_smtv_url("https://suprememastertv.com/en1/v/123.html")` → True; non-SMTV URLs → False; works for `/fa1/`, `/de1/`, etc.                                  |
| `test_parse_episode_id_extracts_lang_and_vid`  | `parse_episode_id(...)` returns `("en", "314924375480")` for the reference URL                                                                                |
| `test_videofile_regex_extracts_all_qualities`  | Given a fixture HTML string with the four `videoFile.push(new Array(...))` lines, the parser yields four `SmtvFile`s in order: 1080p, 720p, 396p, audio       |
| `test_videofile_regex_missing_mp3_okay`        | Fixture with only `720p`+`396p` (news clip) yields two files, no exception                                                                                   |
| `test_siblings_filter_by_series_match`         | Fixture playlist with 7 "Part N of 7 — Shiva" anchors plus 3 unrelated "you might like" anchors → only the 7 series anchors survive                          |
| `test_transcript_text_extraction`              | Fixture with `<div class="article-text">` block — extracted text matches the expected stripped string                                                       |
| `test_transcript_text_empty_when_block_absent` | Fixture without article-text — `transcript_text == ""`, no exception                                                                                         |
| `test_best_url_for_mode_audio_missing`         | `best_url_for_mode(news_clip, "audio")` raises `SmtvError`                                                                                                   |
| `test_filename_for_uses_cdn_basename`          | Filename ends with `…-p1o7-720p.mp4` for a 720p mode call                                                                                                    |
| `test_filename_sanitises_unsafe_chars`         | Title containing `?`, `:`, `*` is cleaned for both Windows and POSIX filename rules                                                                          |
| `test_fetch_episode_smoke_offline_fixture`     | Read a fixture HTML from disk via a monkey-patched urlopen; assert all SmtvEpisode fields populate                                                          |
| `test_fetch_episode_raises_on_no_videoplayer`  | Page without `videoPlayerData["videoFile"]` → `SmtvError`                                                                                                    |
| `test_smtv_url_routing_in_format_service`      | Monkeypatch `smtv.fetch_episode` to return a stub; call `FormatService.lookup_formats` with SMTV URL; assert dropdown maps populated with three video qualities + mp3 |
| `test_smtv_routing_does_not_call_yt_dlp`       | Same as above; assert `subprocess.Popen` is **not** invoked                                                                                                  |
| `test_run_smtv_task_writes_part_then_renames`  | With a stub urlopen returning known bytes, assert `<file>.part` exists during the simulated chunked write and is renamed to the final filename on success    |
| `test_run_smtv_task_transcript_alongside`      | Same as above with `episode.transcript_text="hello"` — `<base>.txt` exists with that content, UTF-8, no BOM                                                  |
| `test_expand_smtv_series_returns_n_tasks`      | 7-part series → 7 VideoDownloadTasks, in part order, all with the same chosen format_info                                                                   |
| `test_no_regression_yt_dlp_path`               | Run the existing YouTube format-lookup flow with a stubbed yt-dlp; SMTV branch must not interfere                                                            |

**Smoke test** (real network, in `tests/smoke/test_smtv_smoke.py`,
skipped when offline):

| Test                       | What it asserts                                                                                            |
|----------------------------|------------------------------------------------------------------------------------------------------------|
| `test_real_episode_parse`  | Live GET of `https://suprememastertv.com/en1/v/314324511501.html`; assert 4 files, ≥ 6 siblings, transcript non-empty |
| `test_real_cdn_head`       | HEAD on the SD 396p URL of the same episode; assert HTTP 200 and `Content-Disposition` present              |

Skip these when `WHISPER_OFFLINE_TESTS=1` is set, or when the SMTV
host is unreachable (`socket.gaierror` / `OSError` on connect).

---

## UI surface (summary)

Download tab gains:

1. A checkbox **"Download all parts of series (SMTV)"** —
   `smtv_download_all_parts_var`, default ON, *visible only when
   the URL is an SMTV episode and the episode has siblings*.
2. The audio-format dropdown shows **"MP3 (audio only)"** as a
   choice when SMTV-detected (replacing whatever yt-dlp would have
   shown).
3. The video-format dropdown shows **"HD 1080p"**, **"HD 720p"**,
   **"SD 396p"** filtered to what the page actually has.

No new tab. No new menu items. No new dialog.

---

## Spec / build impact

`whisper_project.spec` (onefile) and `whisper_project_onedir.spec`
(onedir) — **add to `hiddenimports`** in both:

```
'core.integrations.smtv',
```

`installer.iss` — no change. The new module is pure Python; the
installer's `[Files]` block already sweeps the whole onedir tree.

No new entries in `requirements.txt` (stdlib only).

---

## Documentation deliverables

After implementation, before declaring done:

- `docs/CHANGELOG.md` — `### Unreleased` block: three Added lines
  (series, MP3, transcript), one Changed line (Download tab now
  detects SMTV URLs and routes through `core.integrations.smtv`)
- `README.md` — "What sets it apart" gets a line about SMTV; the
  Download tab section describes the new checkbox
- `docs/ROADMAP.md` — move "SMTV download" from TODO to "Completed
  integrations" alongside oTranscribe
- `docs/integrations/README.md` — append a row to the index table
- `docs/integrations/smtv-acceptance.md` — the grep-able acceptance
  file, modelled on `docs/integrations/otranscribe-acceptance.md`

---

## Acceptance tokens (SMTV-T1 … SMTV-T8)

These are the grep-able tokens the user listed in the prompt. Each
must be PASS in `smtv-acceptance.md`.

| Token   | Verification command (informal)                                                                                                                                                                                                                                                                                                                                                                                                                                                |
|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| SMTV-T1 | `python -c "from core.integrations.smtv import is_smtv_url; assert is_smtv_url('https://suprememastertv.com/en1/v/314924375480.html')"` — alternative: the format service routes SMTV URLs without crashing                                                                                                                                                                                                                                                            |
| SMTV-T2 | `python -c "from core.integrations import smtv; ep = smtv.fetch_episode('https://suprememastertv.com/en1/v/314924375480.html'); assert len(ep.siblings) >= 6"` (real network)                                                                                                                                                                                                                                                                            |
| SMTV-T3 | Run the app, enter the reference URL, pick "HD 720p", click "Add". Wait for done. Verify `<folder>/<filename>-2m.mp4` exists and is the expected size (matches `Content-Length` from the CDN HEAD)                                                                                                                                                                                                                                                                       |
| SMTV-T4 | Same flow with "MP3 (audio only)". Verify `<folder>/<filename>.mp3` exists and is `audio/mpeg`. ffprobe should not be invoked — we used the CDN's mp3 directly                                                                                                                                                                                                                                                                                          |
| SMTV-T5 | Verify that for the reference URL, `<folder>/<base>.txt` is written alongside the media. Open it: starts with `"You guys are experts at eating."` (the known opening of part 1) for Part 1, or whatever the actual opening is for whichever part the user picked                                                                                                                                                                                                          |
| SMTV-T6 | With auto-transcribe-after-download enabled, the saved MP4 also yields `<base>.srt` and `<base>.json` via the existing pipeline. The two transcript outputs (T5's `.txt` from SMTV; T6's `.srt`/`.json` from whisper) coexist                                                                                                                                                                                                                              |
| SMTV-T7 | `python -m pytest tests/ --ignore=tests/smoke` — full unit suite passes; no regression on Phase 0/1a/1b/2a/2-oTranscribe/3a tests                                                                                                                                                                                                                                                                                                                                       |
| SMTV-T8 | `WHISPER_SMOKE_EXE=dist\WhisperProject.exe python -m pytest tests/smoke/test_exe_real_e2e.py` AND `WHISPER_SMOKE_EXE=C:\Temp\installed_test\WhisperProject.exe python -m pytest tests/smoke/test_exe_real_e2e.py` — both pass. Confirms the SMTV module survives onefile bundling and onedir-via-installer packaging                                                                                                                          |

---

## Time estimates

| Sub-feature                                            | Estimate    |
|--------------------------------------------------------|-------------|
| `core/integrations/smtv.py` + unit tests              | 3–4 hours   |
| Format service routing                                 | 1 hour      |
| Download service streamer + transcript write           | 2 hours     |
| Series expansion + UI checkbox                         | 1.5 hours   |
| Acceptance doc + smoke tests                           | 1 hour      |
| Spec hiddenimports + rebuild + onefile + installer     | 1 hour      |
| Total                                                  | ~9.5 hours  |

No sub-feature exceeds the 3-day cap. No new heavy dependencies. No
ToS blocker.

---

## Constraints

- **Stay on `release/single-file-exe`.** No new branches; both
  deliverables built from this branch must continue to work.
- **Stdlib only.** Don't pull in `beautifulsoup4`, `lxml`,
  `requests`, `aiohttp`, etc.
- **Don't touch `core/worker.py`'s JSON stdio protocol.** SMTV is a
  *download* feature; the transcription worker is unchanged.
- **Tk single-threaded.** The new SMTV scrape and download happen on
  daemon threads; they post events into the existing
  `format_events` / `download_events` queues; UI consumes via the
  existing 200 ms / 300 ms `after` loops.
- **Atomic file writes.** Use the `<name>.part` → `os.replace`
  pattern. Same as Phase 3a's writers. No half-written files visible
  to the user.
- **No DB migrations.** SMTV downloads land in the existing
  `history.db` row schema (insert_download / finish_download). The
  `format_label` column can carry a string like
  `"SMTV HD 720p"` so reports show provenance.
- **No yt-dlp subprocess for SMTV URLs.** The whole point of this
  feature is to avoid that hop. Tests T1 and T2 verify this.

---

## Known traps (project-side)

| Trap                                                                                            | Mitigation                                                                                                                                                            |
|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Tk's `after()` loops in `download_service.poll` and `format_service.poll`                       | Don't add a new `after()` schedule — the SMTV thread feeds the existing queues, the existing poll loops consume them                                                  |
| `sys._MEIPASS` resource lookup                                                                  | Not relevant here — SMTV makes no use of bundled `bin/`. Pure-Python module                                                                                            |
| Single-file exe re-extracts on each worker spawn                                                | We don't add new workers. The SMTV download runs in a `download_service` daemon thread inside the main UI process; no new subprocess                                  |
| Cancelling a partially downloaded file                                                          | The `.part` cleanup runs in a `finally:` block in `_run_smtv_task`                                                                                                    |
| The Tk `invalid command name "<id>poll"` regression                                             | The Phase 0 fix in `App.destroy` already cleans pending callbacks; no new schedules added by this work, no new exposure                                               |
| Persian / multi-byte titles in filenames                                                        | Sanitise via `re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)`; trim to 200 chars; same approach yt-dlp's `--restrict-filenames` would use, manually                       |
| User pastes a non-English SMTV URL (e.g. `/fa1/v/…`)                                            | The lang prefix flows through; transcript ends up in Persian; that's the correct behaviour                                                                            |
| User pastes a non-episode SMTV URL (e.g. the search root)                                       | `is_smtv_url` returns True for the host, but `parse_episode_id` returns None → format service falls through to yt-dlp (which will then say "Unsupported URL")        |
| CDN rate-limits on a multi-part download                                                        | Series expansion respects the existing `parallel_workers` (transcription queue) **AND** the single-active download (`app.download_current`) — only one SMTV file streams at a time |

---

## Known limitations

- **Time-range download (v1.0.3).** The Download tab now exposes
  optional Start/End fields that wire through to
  `yt-dlp --download-sections "*start-end"` for YouTube / generic
  URLs. The SMTV path streams the source file straight from the CDN
  via plain HTTP and does **not** support server-side slicing — there
  is no equivalent of `--download-sections` on the CDN endpoint, and
  client-side trimming would require ffmpeg post-processing that
  defeats the "small clip = small bandwidth" goal of the feature.
  When a user enters a Start or End value alongside an SMTV URL, the
  scraper logs a single WARN (`Time-range download is not supported
  for Supreme Master TV URLs in this release; downloading the full
  clip.`) via `core.integrations.smtv.warn_time_range_unsupported`
  and the download proceeds with the full clip. The same line is
  also posted to the in-app console so the user sees it next to the
  download progress.

## Out of scope

Documented now so a future session knows not to scope-creep this one:

- **Subtitle download.** SMTV has no .vtt/.srt files; we save the
  page-embedded transcript as `.txt` instead. If a future feature
  needs SRT-with-timestamps from SMTV, the auto-transcribe pipeline
  (whisper) already produces it.
- **Docx download.** The site's "Download Docx" button is a
  client-side JS conversion; reproducing it would need
  `python-docx` (heavy) and isn't a user-listed requirement.
- **Bulk search → download** flow. The brief defers this: paste-an-
  episode-URL covers all three sub-features the user listed. A
  search-driven UI would be a follow-up.
- **Multi-language transcript pulling.** If a user wants the Persian
  transcript of an English-original lecture, they can paste the
  Persian URL — same episode ID exists under `/fa1/v/<id>.html`.
- **Resuming partial downloads.** Not asked for; the CDN supports
  `Range` so it could be a one-pager follow-up if it matters.

---

## Step N — verify and commit

After all SMTV-T1 … SMTV-T8 are PASS:

1. Rebuild Method A: `python -m PyInstaller --noconfirm --clean
   whisper_project.spec` → `dist\WhisperProject.exe`
2. Rebuild Method B: `python -m PyInstaller --noconfirm --clean
   --distpath dist_onedir whisper_project_onedir.spec` then
   `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss`
3. Re-run the existing onefile and installer smoke E2E against the
   reference test video — must still PASS (this proves SMTV did not
   regress the existing transcribe flow)
4. Atomic commits, recommended ordering:
   - `feat(smtv): core/integrations/smtv.py + unit tests`
   - `feat(smtv): format service routes SMTV URLs without yt-dlp`
   - `feat(smtv): download service streams SMTV CDN files directly`
   - `feat(smtv): expand multi-part series into N download tasks`
   - `feat(smtv): persist page transcript as <base>.txt`
   - `spec: add core.integrations.smtv to onefile + onedir hidden imports`
   - `docs: smtv-acceptance.md + README + ROADMAP`

No `git push`. Stay local until the user says push.

---

## Reference: an actual episode page

A trimmed snapshot of the data we parse out of `/en1/v/314324511501.html`:

```js
videoPlayerData["sourceDefault"] = "video";
videoPlayerData["videoPoster"]  = "../../vimages/202605/3143-BMD1.jpg";
videoPlayerData["youTubeUrl"]   = "Cl_Ne-MeU5Y";
videoPlayerData["videoLength"]  = "37:31";
videoPlayerData["vid"]          = "314324511501";
videoPlayerData["videoFile"].push(new Array('1080p','2026/0512/3143-BMD-19951224-Shivas-112-Ways-of-Concentration-I-p1o7-1080p.mp4'));
videoPlayerData["videoFile"].push(new Array('720p', '2026/0512/3143-BMD-19951224-Shivas-112-Ways-of-Concentration-I-p1o7-2m.mp4'));
videoPlayerData["videoFile"].push(new Array('396p', '2026/0512/3143-BMD-19951224-Shivas-112-Ways-of-Concentration-I-p1o7-700k.mp4'));
videoPlayerData["videoFile"].push(new Array('audio','2026/0512/3143-BMD-19951224-Shivas-112-Ways-of-Concentration-I-p1o7.mp3'));
```

```html
<div class="playlist-contaner">
  <a href="../v/314324511501.html" title="Shiva's 112 Ways of Concentration I, Part 1 of 7, ..."> ... Part 1 of 7</a>
  <a href="../v/314424544835.html" title="Shiva's 112 Ways of Concentration I, Part 2 of 7, ...">...Part 2 of 7</a>
  ...
  <a href="../v/314924375480.html" title="Shiva's 112 Ways of Concentration I, Part 7 of 7, ...">...Part 7 of 7</a>
</div>
```

```html
<div class="article-text" id="article-text">
  <p>You guys are experts at eating. (Hallo, Master.) ...</p>
  <p>... full transcript ...</p>
</div>
```
