# Changelog

All notable changes to this project. Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Windows taskbar progress, job badge and flash.** The app's taskbar button shows a progress bar
  while a job runs (yellow when paused; red after a failure, for at least 5 seconds and then until
  the window is in front), a small badge with the number of queued and running jobs, and blinks
  three times when a job finishes while the window is not in front (once per job, when its last
  stage is done; never for a failed or cancelled job). The flash follows the existing **Chime on completion** setting;
  there is no new option. `native_taskbar` in `config.json` (or `WTS_NO_TASKBAR=1`) turns it off, and
  a start that crashed in the set-up keeps it off until the app is updated (ADR 0012).
- **macOS native feel, part 2.** With the theme on System the Mac app follows Light/Dark live (an
  explicit Light or Dark still wins), the interface uses the macOS system font, and a finished transcription,
  download, subtitle burn or failed subtitled-video chain posts a macOS notification while the app is in the background, minimised or hidden (the existing
  "Chime on completion" setting, now "Chime and notify on completion" on macOS; one per job, one
  summary per queue). Clicking the banner opens Script Editor, not the app. Windows and Linux are
  unchanged (`docs/MACOS_BUILD_NOTES.md`).
- **Speed and time left.** The Queue tab shows how fast each transcription runs and roughly how
  long is left (`about 4.8x, 6 min left`), and the result card says e.g. "42 min of audio
  transcribed in 3 min 40 s (11.5x) with small on CPU". The speed comes from segment end times on a clock that
  stops while paused; the history records speed, model and device. Rules in `docs/SPEED_METER.md`.
- **macOS native feel.** The Mac app has an app menu with About and Settings (Command-comma), the
  standard Window menu, a Help menu with the system search field, Command-W for secondary windows,
  and "Reveal in Finder". Files from Finder ("Open With", a drop on the Dock icon) wait until
  start-up is done and then open like a drop on the window, a Dock click shows a hidden window, and
  the transcript viewer shows its file as the proxy icon and the unsaved-edits dot. Windows and Linux
  are unchanged; the hooks are the ones `tools/mac_native_probe.py` proved (`docs/MACOS_BUILD_NOTES.md`).
- **Work offline, made visible.** While Work offline is on, a line at the bottom of the window
  says whether the app or a process it started has a TCP connection to another computer open
  (checked about every 10 seconds, never "clean" without a successful check) and counts refused
  actions and automatic requests that were not sent. **Network log** lists each event with its feature and
  host, and **Verify offline now** shows a test connection, lookup and UDP send being refused.
  `docs/WORK_OFFLINE.md` explains the limits and how to check the app with Resource Monitor,
  PowerShell or Wireshark.
- **Windows title bars follow the theme.** The title bar of the main window and of every dialog
  turns dark with the Dark theme instead of staying light, and on Windows 11 the caption and border
  match the app panels too. Windows' own message boxes and file dialogs keep the system title bar;
  `native_window_theme` in `config.json` (or `WTS_NO_NATIVE_CHROME=1`) turns it off.
- **"System" theme follows Windows live.** With the theme set to System, the app reads the Windows
  "default app mode" setting and switches when it changes while the app is open (checked every
  2 seconds, only in System mode; nothing is saved). Light and Dark still win over Windows.
- **FFmpeg source for the GPL builds.** `THIRD_PARTY_NOTICES.md` now names the exact corresponding
  source of the bundled FFmpeg (Windows: the gyan.dev build's FFmpeg commit; macOS: the FFmpeg 9.0.2
  release) and the builders' library lists. `tools/fetch_ffmpeg_source.py` downloads the pinned
  tarballs (`platform/ffmpeg-source.json`, size and SHA-256 checked) under release-prefixed names,
  and `docs/RELEASE_PROCESS.md` attaches them to every release.

- **Make subtitled video.** A new **Make subtitled video** choice on the Download Videos tab turns a
  link into `<title>-subbed.mp4` with the subtitles burned in: the download hands off to Whisper and
  then to ffmpeg, and the row shows `running`, `transcribing`, `burning` with one rising percent and a
  working Cancel. The download and the transcript are always kept, an existing `-subbed.mp4` is never
  replaced (`-subbed (2).mp4`), and a failure leaves no partial video (`docs/SUBTITLED_VIDEO.md`).
  Braces, backslashes and `<i>`-style tags in a transcript are drawn as text instead of being read
  as libass style commands, and the burned MP4 uses 8-bit H.264 with AAC audio when the source
  audio would not play inside an MP4.
- **Shareable web page of a transcript.** The transcript viewer and the Last Result card have a
  **Save shareable page** button that saves one `.html` file that opens in any browser with no
  install and no internet connection: timestamps, speakers, chapters, a search box with
  Previous/Next, and a click on a word (or a line) plays the media from there while the spoken
  word is highlighted. The media is linked, not copied, so the page plays while it stays next to
  the media file. A strict Content-Security-Policy allows no outside resource; the optional footer
  link is the page's only web address (`core/writers/html_transcript.py`).
- **Windows installer built in CI.** A new workflow (`windows-installer.yml`) builds the installer
  and the Portable ZIP from the committed tree, smoke-tests a silent install and keeps both as
  workflow artifacts for 7 days; it never publishes a release. Every third-party download (Python,
  ffmpeg, yt-dlp, Deno, diarization models, Inno Setup) is pinned with its published SHA-256 in
  `platform/windows/build-deps.json`, and `build_embed_installer.bat` now verifies the Python
  tarball too (see `docs/BUILD.md`).
- **Gentle star invitation.** After 5 successful jobs and 7 days of use, one quiet bar asks once
  whether a GitHub star may help other people find the app (**Open GitHub page**, **Not now**,
  **Don't ask again**). At most twice ever, 30 days apart; never while a job runs or waits and never
  in Work offline mode. The counters are local config keys that are never sent
  (`star_*`, see `docs/CONFIG.md`); About has one quiet link line to the repository page.
- **Open in Subtitle Edit (Windows).** The Last Result card and the transcript viewer have an
  **Open in Subtitle Edit** button that opens the written SRT (or VTT/ASS) in the free editor for
  waveform-based timing work. It finds an installed copy through the uninstall registry entries and
  `Program Files`; a portable copy is chosen once in **Advanced → App behaviour**
  (`subtitle_edit_path`). When Subtitle Edit is missing, the button offers its official download
  page, opened only on your click. Hidden on macOS and Linux.
- **Translate speech straight to English.** The Transcribe tab has an **Output: English
  translation** option (off by default) that uses Whisper's own translate task: non-English
  speech becomes English subtitles in one pass, with no AI model. Files are named
  `name.en-translated.srt`, the history records the task, and a resumed job keeps it. It is
  greyed out (reason on hover) for other engines, `large-v3-turbo` and English-only models
  (`translate_to_english`, see `docs/CONFIG.md`).
- **Text to Voice speaks long texts piece by piece, and a cancelled job continues.** A text longer
  than one piece is split at sentence ends; each finished piece is kept on disk with a small
  progress file (`core.tts_job`), the status line shows the time left, and Cancel, a crash or a
  power cut lose at most the piece in progress. Generate with the same text, voice and speed
  offers **Continue the unfinished job** or **Start over**; the final file is joined, tagged as
  AI-generated and checked before the pieces are deleted. The job limit goes from 5,000 to
  100,000 characters, and **Advanced → App behaviour** has a local-only "no text length limit"
  switch (`tts_no_text_limit`). OmniVoice's designed and own voices stay single-pass (5,000
  characters), since each pass picks a new voice.
- **Text to Voice shows the time, file size and free space before a long text starts.** A long
  text gets a confirm step under the text box with the time range on this computer, the speech
  length and the WAV size; a job the disk cannot hold (plus 500 MB kept free) is refused with the
  space it needs. The range comes from a speed figure stored per engine and device
  (`core.tts_plan`): Kokoro offers a 10-second measuring run, and every finished job of a few
  seconds or more updates it; it is measured again after an engine or hardware change. The
  5,000-character limit is now one constant for both engines, and Kokoro enforces it too.
- **Work offline: one switch that keeps the app off the network.** **File → Work offline** (also
  in **Advanced → App behaviour**, `work_offline`) stops every network use: the online config,
  the update check, usage statistics and crash reports are skipped, and a link lookup, a download,
  a model or component download, a cloud engine, the remote AI provider or SMTV says "Offline
  mode is on" and names the switch (the download, update and helper buttons offer to turn it
  off). Models already on disk keep working. Each app process
  also refuses any other outbound connection or name lookup while it is on (`core.offline`), and
  the online config can never change it. `docs/CONFIG.md` lists what it blocks for every request.
- **Quiet notices instead of message boxes for plain information.** "Saved", "Renamed", "You're on the latest version", "Could not reach the update server" and similar hints now show as a short notice along the bottom edge of the window (`app/widgets/notice.py`): it hides by itself after a few seconds, stays while the pointer is over it, never takes the keyboard focus, and `Ctrl+.` or its close button dismisses it. At most three are held. Questions, errors that need action, consent and data-loss warnings are still dialogs.
- **One place for colours, spacing and type sizes, and one icon set.** `app/theme/tokens.py` now
  holds every colour the UI uses (the 48 literal hex values in `app/` are gone), the 4/8/12/16/24/32
  spacing scale and a type scale. Near-duplicate colours were unified, so the blue of links and
  info marks, the amber of warnings, the green of "ready" and the red of errors are each one value.
  `assets/icons` ships 26 Lucide icons (ISC licence, included) pre-rendered at 16 and 24 px for
  100%, 125%, 150% and 200% scaling; `app/theme/icons.py` picks the sharpest file for the window
  and tints it to a theme colour. Nothing in the UI uses the icons yet. The Windows installers
  copy the folder; the PyInstaller specs already ship all of `assets`. `tools/build_icons.py`
  regenerates the set (PyMuPDF, development only).
- **Sharp text at 125% and 150% display scaling on Windows.** The app now declares per-monitor DPI
  awareness before its first window opens (with fallbacks for older Windows), so Windows no longer
  stretches a blurry bitmap. Window minimum sizes, the Supreme Master TV banner and the Live tab
  level display scale with the display; the sizes stay inside small screens. macOS and Linux are unchanged.
- **An empty Transcribe tab says what to do, and About moved under Help.** While nothing is queued
  the tab shows one block: "Drop a file here, paste a link, or try the sample" (it names only what
  works on that install), where a link goes, the supported formats and the sample button; it
  disappears once a file is queued. **About** is now the last item of the **Help** menu instead of
  a separate menu bar entry.
- **The Download tab says which subtitles a video already has.** After a link lookup a line under the
  link field names them ("Subtitles available: English (made by the uploader), Spanish (automatic)"),
  uploader-made and automatic told apart; it is hidden when there are none and for SMTV episodes. With
  "Transcribe after download" on and subtitles in the chosen language, **Download** asks "Use the existing
  subtitles (seconds) or transcribe (minutes)?" with a "Don't ask again" box (`download_caption_choice`,
  also in Advanced settings > Downloads). YouTube's automatic translations no longer count as subtitles
  once the real speech-recognition track is listed.
- **The video downloader (yt-dlp) updates itself without administrator rights.** A download
  or format lookup that fails like an outdated yt-dlp (HTTP 403, signature or extractor
  errors) shows a bar with **Update it**: yt-dlp's own updater refreshes a copy in the user
  cache, checked against the release's `SHA2-256SUMS`, and the app runs whichever of that copy
  and the bundled one is newer (the bundled binary is never written, and no update runs during
  a download). **Advanced → Downloads (yt-dlp)** offers "Ask me" (default), "Keep it up to date
  automatically" (once a day, before a download) and "Never"; an old `auto_update_yt_dlp: true`
  loads as the automatic mode. The macOS app does the same with a downloaded copy (next entry).
- **macOS: the video downloader can update itself too.** **Update it** (or the automatic mode)
  installs yt-dlp's official folder build, the latest stable release's `yt-dlp_macos.zip` (about
  54 MB), over https from GitHub's hosts only. It is installed in the user cache only if it matches
  the release's `SHA2-256SUMS`, is unpacked safely into a new versioned folder and starts with
  `--version`; only then does the app switch to it and remove the old folder. A bad checksum, an
  unsafe archive, a cut-off download or a build that does not start installs nothing and the
  previous copy keeps working. A Mac older than macOS 10.15 keeps the old advice to install the newest
  app version, now with the download-page link.
- **"Try it now" sample clip.** An 18-second public-domain (CC0) spoken clip ships with the
  app. "Finish and try it now" in the quick start window, and a "Try it now (sample clip)"
  button on the Transcribe tab, transcribe it with the chosen model and open the transcript, so
  a new user sees a real result before finding a file of their own. Credit and licence:
  `docs/SAMPLE_CLIP.md`.
- **Quick start window on the first launch of a new install.** Three choices:
  the main spoken language, "Fast" or "Best quality", and the folder for
  downloaded media. Each choice shows the model, its download size and a rough time
  per minute of audio on this computer, and the model comes from the
  per-language table. Skip keeps the old first-run path; existing installs
  never see it, and `quick_start_enabled` switches it off. Unmeasured languages
  now get `small` as their "fast" model instead of the 3 GB default.
- **Multilingual benchmark results and a per-language model table.** Six local
  models (tiny to large-v3) were scored in eight languages on FLEURS, five
  utterances each, on CPU; the tables are in `docs/evaluations/benchmark-v1/`.
  `core/language_defaults.py` turns them into a "fast" (`small` everywhere) and a
  "best" model per language (`large-v3` or `large-v3-turbo`); other languages keep
  the default. The benchmark script can now resume per (language, model), read
  models from an existing folder without writing to it, and resets the sampling
  seed before every utterance.
- **`tools/benchmark_multilingual.py`: per-language accuracy and speed of the local
  models on public FLEURS speech (CC-BY-4.0, no account).** It transcribes through the
  app's own faster-whisper backend on CPU and scores WER, or CER for zh/ja, with a
  stdlib Levenshtein and a documented normaliser. Method and licence are in
  `docs/evaluations/benchmark-v1/`.
- **Synthetic speech is labelled as AI-generated.** Every WAV the Clone Your
  Voice / Text to Voice tab produces (OmniVoice and Kokoro) carries a RIFF
  `INFO` comment `AI-generated synthetic speech` plus the app name and version;
  the audio samples are unchanged. Each voice clone from reference clips also
  appends a local, never-uploaded consent record (time, output hash, reference
  hashes) to `voice_clone_consent.jsonl`; see `docs/CONFIG.md`.
- **Help → Usage statistics.** The usage-statistics switch is now a
  check item in the Help menu as well as in Advanced → App behaviour; both
  show the same saved value, and About lists exactly what is sent.
- **macOS: the finished `.dmg` is now tested like a user meets it**
  (`platform/macos/pyinstaller/test_dmg.sh`, run by `build_mac.sh` and the
  macOS CI): mount, check the drag-to-Applications link, copy the app out,
  lint its Info.plist, verify the signature, run the CLI and open the GUI
  from the copy, unmount. The pipeline never tested the `.dmg` itself before.
- **`docs/COMPARISON.md`: a dated comparison with Subtitle Edit, Vibe, Buzz,
  noScribe and aTrain**, with "choose X if" lines, the cases where another app
  fits better, and a source for every fact. The website's compare table now
  covers Subtitle Edit, Vibe and Buzz from the same facts (it compared Buzz,
  MacWhisper and the OpenAI API) and links to the page;
  `tests/test_comparison_doc.py` checks its links and WTS facts against the code.

- **One `llms.txt`, plus `site/facts.json`**: the repo-root copy is gone;
  `site/llms.txt` (now with the full docs list and the engines/formats facts)
  is the only one. `site/facts.json` lists version, platforms, output formats,
  engines, licence and links for machines; the release workflow refreshes its
  version and date, and `tests/test_site_facts.py` checks the rest against the code.

- **`docs/SERVER.md` documents the whole server API**: the OpenAI-compatible
  `/v1/models` and `/v1/audio/transcriptions` routes, all `serve` flags,
  token, HTTPS and the completion webhook, with copy-paste curl and an Open
  WebUI setup. `tests/test_server_doc.py` checks flags, routes, config keys,
  response formats and webhook fields against the code.

- **How the project is built, said plainly**: README and CONTRIBUTING state that
  it is developed with heavy AI help, which checks run when, and that AI-assisted
  commits carry an `Assisted-by:` trailer (the rule is in `AGENTS.md`). A new
  `.mailmap` merges the maintainer's two GitHub identities in `git shortlog`;
  `tests/test_ai_disclosure.py` ties each claim to the workflow and files behind it.

### Changed

- **Help → About links to this project's repository and has a "Report a problem" button** that opens a new GitHub issue with the app version and system filled in; translation-robot is named as co-author.
- **Supreme Master TV tab: an Explore grid of 24 programs**, including Veggie Elite, Make Peace, Cinema Scene, Golden Age Technology and Climate Change; the banner keeps only "About the channel" and the video cards no longer have a Transcribe button.
- **Update notice: major releases and a monthly reminder.** A release whose first version number is
  higher (2.x to 3.0) is announced as "Version 3.0 is here: a major new release", and What's new
  lists up to five highlights instead of three. After Later's 3, 7 and 14 days the bar comes back
  every 30 days instead of going quiet for good; Skip this version still silences that version, and
  the bar now waits until no transcription or download is queued or running.
- **Burn subtitles reports progress and can be stopped.** `core/burn_subs.burn()` now runs ffmpeg
  with `-progress pipe:1` against the probed duration, drains stderr on its own thread, accepts a
  cancel check and hands over the ffmpeg process; its time limit grows with the video (three times
  its length, at least one hour) instead of a fixed hour.
- **Builds list every module and pin every download.** The three PyInstaller specs now carry
  every `app.*` / `core.*` module (17 were missing on Windows, 27 on macOS), and a test built from
  the module tree fails when one is left out. The macOS build pins ffmpeg (9.0.2), yt-dlp, Deno,
  numpy and PyInstaller with SHA-256 checks instead of taking the latest release, fetches the two
  speaker-diarization models like the Windows build, and no longer bundles the unused `ffplay`.
- **Windows installer CI checks what users run.** The workflow imports every app and engine module
  plus the GUI-only dependencies (Pillow's ImageTk, pystray, watchdog, sounddevice), checks the
  assets and licence files, smoke-tests the Portable tree as well as the installed copy, runs when
  `app/`, `core/`, `gui.py` or `assets/` change, and no longer cancels a running build. All GitHub
  workflows use actions pinned to a commit and a read-only token by default.
- **The voice-clone worker log shows how long the OmniVoice model load takes.** The worker's
  log now has a line when the load starts and one when the model is ready (total and import
  time), times the worker's own start-up imports, and names the process's CPU and I/O priority.
  A worker started at low I/O priority (as a scheduled task does) can wait many minutes for a
  busy disk, which looked like a hang; the priority and the timed lines now point at that cause.
- **Usage statistics no longer include the file name.** The row sent after a finished
  transcription has no `file_name` field any more, so nothing in it says what was transcribed.
  The stats server script ignores a `file_name` posted by older app versions and stores NULL in
  that column; its README shows how to clear the names kept in old rows.
- **Usage statistics never send a local model folder.** A model loaded from a folder (for
  example a path typed as the NVIDIA model id) is reported as `local-model` instead of its path,
  which could hold the account name; catalog names and Hugging Face repo ids are unchanged.
- **Crash reports carry no file paths or machine name.** When Sentry crash reports are turned on
  (`SENTRY_DSN`, never set in published builds), every event drops the host name, command line,
  local variables, breadcrumbs, frame paths and log arguments, and masks URLs and file paths in
  messages.
- **The translated READMEs no longer say that nothing is sent.** The German, Spanish, French,
  Japanese, Korean, Portuguese and Chinese pages now name the usage statistics and their switch
  (**Help → Usage statistics**); the Persian page drops the claim.
- **A quiet update bar instead of the "Open the download page?" dialog.** A newer
  release shows one line under the menu (version and headline) with What's new (its
  first highlights), Download (the installer, Portable ZIP or Mac dmg this copy came
  from), Later (again in 3, 7, then 14 days, then only a dot on the Help menu) and
  Skip this version. It never takes focus, appears at most once per launch, and
  stays silent offline or until the matching file is uploaded. Turn it off in
  Advanced → App behaviour or with `WTS_DISABLE_UPDATER=1`; the online config can
  never change these settings.
- **Voice cloning: a permission tick instead of the one-time warning dialog.**
  The Clone Your Voice tab always shows the rules (own voice or the speaker's
  clear permission; no impersonation, no misleading audio of real people), and
  Generate stays disabled for a clone until "I have the speaker's permission"
  is ticked; adding or removing a reference clip clears the tick. Voice design,
  the model's own voice and Kokoro need no tick. The "about 2 GB, one time"
  notice now appears when the OmniVoice download starts.
- **README cut from 27 KB to 8 KB**: who it is for, features, downloads, the
  per-version download badges, what leaves the computer (usage statistics
  included) and links to the docs and the comparison page. The FAQ lives on
  the website; the model-folder choice, `--safe-mode`, updating and the
  keyboard shortcuts moved to `docs/INSTALL.md`, whose install section now
  names the current release files (it still described v1.0.3) and covers
  opening the Mac app past Gatekeeper.
- **Repository root: the 22 per-branch handoff files are removed.** The 20
  `OPENCODE_HANDOFF_*.md` files and the two `INTEGRATION_*.md` files were
  working notes from a past branch merge; they stay in git history.
- **The generated repo map is no longer tracked.** `PROJECT_INDEX.md` and
  `.project_index.json` are git-ignored (a local hook keeps refreshing them)
  and `tools/index_refresh.py` is removed; README, CONTRIBUTING and
  `.cursorrules` now point coding agents to `AGENTS.md`.
- **Docs: market analyses, per-release notes and integration briefs are
  removed.** `docs/release-notes/` (24 files; release notes live on GitHub
  Releases), `docs/roadmap/`, the competitive-analysis and gap-analysis files,
  the integration research/brief/acceptance notes, the macOS VM report and
  its screenshots, the Gemma evaluation and the video script (43 files in
  all) stay in git history; the references to them are fixed.
- **Agent rules live in one tool-neutral `AGENTS.md`.** It now holds the
  layout, build and test commands, code rules and release/macOS guardrails;
  `CLAUDE.md` only imports it and `.cursorrules` is removed (Cursor reads
  `AGENTS.md`). `tests/test_agents_md.py` keeps it that way.
- **macOS: the bundled yt-dlp starts in about half a second instead of
  ~25 s per call.** It is now yt-dlp's onedir build (`yt-dlp_macos.zip`,
  checked against the release's SHA2-256SUMS), unpacked once inside the
  app; the onefile build unpacked itself on every run. Only the very first
  run after installing still takes ~25 s.
- **Usage stats no longer send the computer name.** The payload
  drops `platform_node` and adds `country`, a two-letter code read from the
  operating system's region setting (no network lookup; empty when unset).
- **Stats server script: stores the app's country code instead of the IP
  address.** It moved from `stats/` to `platform/stats-server/` (with a
  deployment README), no longer reads the client IP or calls a geoip
  service, accepts `country` only as two upper-case letters, and caps every
  text field. Old columns stay; new rows leave them empty. A deployed server
  keeps its old behaviour until its operator installs this version.
- **Website, README and `llms.txt`: privacy wording now says exactly what
  leaves the computer.** "Private by architecture" and the blanket "no upload"
  lines are gone: audio is uploaded only by the two opt-in cloud engines, and
  transcript text only when a remote AI model is connected.
- **Docs, About dialog and code comments: usage stats and network use are
  described as they work.** `docs/CONFIG.md` gives the real `stats_url`
  default, says stats are on by default, lists every field sent, and has a
  new "Network use" table of every outbound connection. Wording that called
  the stats unidentifiable or off until switched on is gone, and the About
  dialog no longer says there is no network call without a click.
- **Website and docs: the contact address is no longer written in any
  file.** The website's Contact section shows it on request (a same-origin
  function hands it over after a short proof-of-work); README, SECURITY.md,
  `llms.txt` and the package metadata point to that section instead.
- **macOS build: `pyinstaller whisper_project_onedir.spec` (or the onefile
  spec) from the repo root builds the working `.app` on a Mac** by handing
  over to the macOS spec (it used to make a Windows-style folder that could
  not become an app). `compileall-whisper-mac.sh` now makes its dmg with
  `builddmg.command` (hdiutil when create-dmg is missing). Windows builds
  are unchanged.
- **macOS build: a Homebrew ffmpeg left in `bin/` stopped the build**
  ("Permission denied" while replacing it). `fetch_mac_binaries.sh` now
  replaces read-only files.

### Removed

- **Hardware wizard benchmark.** The "Run 5 s benchmark" button is gone: it needed a model loaded
  in the GUI process (only the optional local server has one), timed a silent clip, and could label
  a speed with a tier it was not measured on. `hardware.json` keeps its `benchmark_rtf` field,
  now always empty.
- **Models download only from the Hugging Face Hub.** The zip mirror is retired: no catalog
  entry names it, and a `url`/`md5` left in an older `config.json` (including a hand-edited
  `model_catalog` pin) is ignored. An installed model is never deleted for a re-check, and a
  cut-off download resumes in place. The download window shows progress from the bytes on disk.
- **Video Tiling is gone.** The tab, its About section, the monitor chooser, the
  tiling engine, monitor detection and the `screeninfo` dependency are removed, and
  the app no longer offers to download ffplay. The Windows installer no longer has
  the task and removes the old marker file on upgrade; the tutorial, website and
  macOS install notes no longer mention it. Settings files that still hold
  `tiling_*` keys load normally, and the next save drops them.

### Fixed

- **macOS 10.15: PDF export and the menu-bar icon work again.** The app bundled two versions of one compression library and older macOS loaded the wrong one for the image library.
- **macOS: opening several files at once from Finder (Open With) adds them all to the queue together.** Before, only the last of them ended up selected.
- **On macOS, the app no longer uses a third of a CPU core while a text box has the focus.** The text cursor stays steady instead of blinking.
- **On macOS, quiet notices no longer appear as an empty bar** at the bottom of the window.
- **Closing the app now also stops the SMTV tab's background search workers**, and a crash in an SMTV search is written to the log instead of vanishing.
- **An interrupted yt-dlp self-update or version check no longer leaves yt-dlp running.** Its process tree is now ended before the error is passed on.
- **A URL job in the local API no longer leaves yt-dlp running when its wait is interrupted.** The download process is now stopped whenever the wait ends early.
- **A broken character in a transcript no longer loses an export format or the unsaved Live text.** A
  lone half of a character pair (from a hand-edited JSON or a damaged file name) made every text format
  fail to save, and the Live tab's exit autosave deleted its file; the bad character is now replaced with
  the standard replacement character and everything else is written.
- **A transcript with a stray U+FFFE or U+FFFF character now exports to Word.** These two characters are
  not legal in the Word file format and made the whole export fail with "All strings must be XML
  compatible"; they are replaced with the standard replacement character, like a broken character half.
- **Two different file names no longer count as one file.** On Windows and macOS a transcript name with
  the German sharp s was treated as the same file as its "ss" spelling, so the transcript viewer raised
  the wrong window and the share page refused a legitimate name. Only case differences are folded now.
- **Declining "stop the running job?" after a model or engine change no longer keeps the old model.**
  The change was saved but the running worker was never replaced, so every later job silently used the
  old model until the app restarted. The worker is now replaced as soon as it is idle, before the next
  job starts, and the history and usage-stats model label names the model that really ran.
- **A model entry with an impossible download size no longer blocks its download.** A catalog size of
  `Infinity` or a number too large to count raised an error before the first byte, and NaN showed "about nan
  GB"; such a size is now treated as unknown. A full disk while creating the model folder now says so and
  suggests another folder.
- **A dropped file whose name has `#` or `%41` in it keeps its name.** The file address was decoded twice, so
  `a%20%231.mp4` became `a ` and an encoded `%41` became `A`; it is now decoded once.
- **Closing the app during a Live session always finishes the recording.** If the unsaved transcript could not be
  written (for example a character that cannot be encoded), the recorder was never closed, the session stayed
  open and an empty transcript file was left behind. The audio is now kept and no empty file remains.
- **Closing a window no longer leaves layout and status timers running.** The tab pages' layout check and
  the Work-offline status bar now cancel their timers when destroyed; before, a leftover timer failed with
  an "invalid command name" error and on macOS could freeze the next window's redraw.
- **Save shareable page can no longer overwrite the transcript or media on a Mac.** The check that
  refuses those two files compared names with a case rule that only Windows applies, so on a Mac
  volume `T.JSON` passed as a new name and replaced `t.json`. It now asks the filesystem; the same
  fix covers one transcript window per file, the Re-run duplicate check and subtitle-burn output names.
- **A blank or missing `device` setting now means "auto" instead of an empty device name.** Only the
  literal `auto` triggered the GPU check, so a hand-edited `"device": ""` or `null` reached the engine as
  no device at all; the value is also trimmed and lower-cased now.
- **Chapter titles for Chinese, Japanese and Thai transcripts stay short.** These scripts have no
  spaces, so the six-word limit never applied and a long clause became the whole title; titles now
  stop at 30 characters with an ellipsis.
- **Cancelling on macOS and Linux no longer leaves a stubborn child process behind.** After the polite
  stop, the app waited only for the main process to exit; a helper (for example ffmpeg) that ignored it
  survived as soon as the main process was gone. It now waits for the whole process group and force-kills
  what is left after the grace period.
- **A word with no confidence value no longer paints its transcript row red.** The viewer counted a
  missing `probability` as 0 %, so one such word (hand-edited or third-party JSON) made the whole
  row look low-confidence; the word is now ignored.
- **"Remove fillers" keeps the marks a segment opens with.** A segment such as `... um, well` or
  `...and then um we go` lost its leading `...` (and `?!`) because the cleanup of punctuation left
  by the filler also stripped the original opening marks.
- **Changing the Whisper model in Settings no longer stops a running transcription without asking, or
  before the choice is saved.** It now asks like an engine switch does and restarts the worker only
  after the save worked; a failed save (also from "Download now") puts the previous model back.
- **An SRT cue with an absurdly long timecode no longer stops the oTranscribe import.** That cue is skipped and the others are read.
- **A Supreme Master TV download named like a Windows device with spaces (`LPT1 .txt`) is now renamed too,** as `LPT1.txt` already was, so it cannot be routed to the device.
- **A damaged macOS preferences file no longer hides the country from the usage statistics.** The region lookup now falls back to the locale environment instead of returning nothing.
- **One damaged history row no longer stops the search re-index.** A row whose saved output list was not a list aborted the walk, so every later transcript stayed unindexed; the row is now skipped.
- **A model size of `Infinity` or NaN in the model catalog no longer breaks the download.** It used to crash the start of a download (`Infinity`) or show "about nan GB"; such a size now counts as unknown.
- **A start or end time typed with a minus sign and zeros (`-0:00:01`) is no longer accepted** for a download clip; it is treated as unusable input, like any other negative time.
- **A failed copy of the bundled yt-dlp no longer leaves a stray `yt-dlp.copy` file** in the cache folder; the copy in use is kept untouched.
- **A speaker name containing `-->` no longer breaks an SRT cue.** The name is now escaped like the cue text in the SRT and bilingual SRT files, as WebVTT already did.
- **A damaged "online config not published" marker file no longer aborts the settings load.** A marker that is not valid UTF-8 is treated as absent and the online config is simply asked for again.
- **A transcript with a broken character no longer stops the Word or ELAN export.** A lone surrogate in the text, a speaker name or the title made the file fail to save; it is now replaced with the Unicode replacement character (U+FFFD).
- **The API server keeps only the file name of an uploaded Windows path on macOS and Linux.** A client
  that sent `C:\Users\me\clip.wav` as the file name got the folders glued onto the name
  (`CUsersmeclip.wav`); it is now saved as `clip.wav`, as on Windows.
- **A file name with an unpaired surrogate no longer breaks the resume-checkpoint lookup.** The
  checkpoint key now encodes such a path instead of raising, so the lookup answers "no checkpoint"
  and the job carries on.
- **The installer build no longer depends on the PC's Windows code page when it checks `gui.py`.**
  A non-ASCII character that the code page cannot decode failed the check.
- **Uninstalling and answering Yes to deleting the models folder removes only the models.** The question
  used to delete the whole folder chosen as the model hub, which could be Documents or a drive; now only
  the `models--*` folders go, and the hub folder itself only if that leaves it empty.
- **Meaning search on a long history no longer loads every stored vector at once.** It reads the rows
  one by one and keeps only the best matches, which keeps memory flat.
- **A job that starts while the exit questions are open is recorded as closed on purpose.** The next
  launch no longer calls it a crash.
- **A folder dropped as a `file://` address is queued like any other dropped folder.** It was reported
  as an unusable item.
- **A late Cancel no longer turns a finished download into a cancelled one.** Cancelling a download
  that had ended in the meantime (the Esc question left open, an old menu) also cancelled its transcription.
- **A transcription cancelled before it starts stops at once.** It used to run vocal separation,
  duration probing and slicing first, which could take minutes.
- **A subtitled video finished just before closing the app is recorded in the history.** The row was
  written by a callback on the window thread that never ran when the app closed first; the burn
  thread now writes it as soon as the file exists.
- **Command-W closes a Mac window whose close action is a Tcl script.** Such a window (Tk's own
  dialogs set one) stayed open without any message.
- **Closing the app during a live session can no longer lose both the words and the audio.** The
  session recording was deleted before the unsaved transcript was written; the transcript is saved
  first now, and if that fails the recording is kept and its location is logged.
- **A failed Google batch upload no longer leaves the audio in your bucket.** When the connection
  dropped after the file was stored, nothing deleted it and it kept costing storage; the upload now
  removes its own object before reporting the error.
- **The NVIDIA Parakeet engine no longer waits forever on an unreadable file.** Decoding the audio
  with ffmpeg had no time limit, so a file on a disconnected network drive wedged the worker; it now
  stops after 30 minutes with a clear message, like the cloud engines.
- **Word and PDF transcripts show a real total time when the last segment has no end time.** The
  header said `00:00:00 total`; it now counts up to that segment's start.
- **The SMTV Word template now reads right-to-left for Persian, Arabic and Hebrew.** The transcript
  cells were left-to-right, so closing punctuation landed on the wrong side; a segment whose text is
  the number 0 was also dropped from that file.
- **A caption with null text no longer becomes the word "None" in Convert.** The rolling-caption
  clean-up turned a null `text` into the string `None`.
- **Subtitle text that contains an arrow is now escaped when burned in.** A cue line holding `-->`
  was mistaken for a timing line and went to ffmpeg with its `{...}` blocks and tags unescaped.
- **Bilingual subtitles for a non-Latin target language no longer overwrite each other.** The file name
  dropped every non-ASCII letter of the language (Persian, Arabic, ...), so each run replaced the previous file.
- **A failed format lookup always shows a reason, and odd caption data no longer blocks the formats.**
  A yt-dlp error with only blank lines on stderr showed an empty message; a non-object
  `automatic_captions` value raised an error in the format list.
- **The server keeps working when it cannot start a webhook thread.** A finished job stays finished and
  the next jobs still run; the notification is logged and dropped.
- **A large upload stays byte-exact when a long text field follows the file.** The server could keep
  the two line-break bytes in front of the closing boundary in the saved media.
- **Opening a file no longer freezes the window.** The Mac and Linux openers are waited for off the
  window's thread (up to 5 s was blocked before), and any failure of the opener, a path it rejects
  included, still shows the error dialog. A failing `xdg-open` now shows its exit code instead of
  "no app is set", and the "shown in its folder" notice is not shown when the folder cannot be opened.
- **The primary button's text is readable while pressed.** The pressed text of the main blue/cyan
  button (Transcribe, Finish, Search) read 3.1:1 (dark) and 2.9:1 (light); it is now black, 7.7:1 and
  4.9:1. The resting button was already fine (black on cyan 11.1:1 in dark, white on blue 6.3:1 in light).
- **Destructive confirmations default to the safe answer.** Quitting with jobs running, stopping
  running jobs to switch the engine or model, cancelling a transcription or download, closing a viewer
  with unsaved edits, overwriting a transcript changed on disk and replacing an `.otr` file now select
  No (or Cancel), so pressing Return no longer does the destructive thing.
- **No warning for the last heartbeats of a finished parallel worker.** After parallel jobs end, the
  retired worker's final heartbeats and exit notice are logged at debug level; an unmatched event that
  can carry a result (such as `done`) still warns.
- **The caption under the viewer's player follows edits.** After Find & Replace, Remove fillers or a
  timestamp edit it kept the old wording ("fox" for a segment that now says "cat") until the playhead
  moved to another segment.
- **The transcript viewer opens inside a small Mac screen.** On a 1280x800 Mac it was placed at the
  system's offset and ran past the right edge and under the Dock. It now opens centred over the main
  window, and windows sized to the screen keep room for the menu bar, title bar and Dock there
  (Windows and Linux are unchanged). The viewer also ends above the Dock and can be dragged shorter there.
- **Opening a result file says so when no app can open it.** "Open" on a `.srt` did nothing on a Mac
  with no app for that type, because the exit code of `open` was ignored. The result is now checked
  on every platform (also `xdg-open`, and Windows "no association"): a Mac opens text files such as
  `.srt` in its text editor, anything else is shown in its folder with a short notice.
- **The engine row agrees with the model row after Quick start.** Finishing Quick start left
  "Model not downloaded yet" next to "Downloaded" until Advanced settings was opened; the engine
  status is now probed again once the choices are saved.
- **The AI provider address and the launch-ping address accept only http(s).** A `file://` or
  `ftp://` value in either setting is refused with a message instead of being opened.
- **The Windows installer and Portable ZIP start on a PC without the Visual C++ Redistributable.**
  The speech engines (`ctranslate2`, `onnxruntime`) import `msvcp140.dll` and `msvcp140_1.dll`,
  which the bundled Python does not carry; the build now adds them (pinned, SHA-256 checked) to
  `python\` and fails if any DLL in the tree imports a DLL that is neither shipped nor part of
  Windows 10 (`tools/check_embed_tree.py`).
- **The Windows build no longer ships the build machine's bytecode.** `app\` and `core\` were copied
  with their `__pycache__` folders (bytecode of the build machine's CPython 3.14, in a CPython 3.11
  tree); they are now left out, and the build fails if any reappear.
- **A line break in a logged value can no longer forge a log line.** A video title, a file name
  or a setting that holds a newline is now shown as an escape in `app.log` (the message only:
  tracebacks keep their own lines), and the macOS helper hook
  runs only the exact multiprocessing command it was written for. The Linux installer fetches
  ffmpeg over HTTPS only, and two form fields and a graphics page got a label or a title.
- **No banner while you are looking at the Mac app.** The finished-job notification no longer
  appears when the app is in front and its window is on screen, even if no control has the keyboard
  focus (for example right after clicking a tab); it still appears when another app is in front or
  the window is minimised or hidden.
- **Quitting before a Word file is rebuilt now says so.** When the 30-second wait for the
  transcript viewer's export rebuild runs out, a message names the files that still hold the old
  text and says to reopen the transcript and save again; the transcript itself was already saved.
- **Stopping a helper process on Windows no longer gives up silently.** When the forced
  `taskkill` of a worker or download tree reports a failure, the app now also signals the
  process itself instead of treating the kill as done.
- **No helper program can take over the app's command pipe any more.** Every other child
  process the app starts (ffprobe, ffmpeg, yt-dlp, Deno, pip, Demucs, `open` / `xdg-open`)
  now gets no stdin as well, so the same ten-minute hang cannot come back through the
  diarization, voice-clone or noise-reduction ffmpeg, and a test checks every such call. The
  optional-feature installer also tells pip not to prompt, so a private-index login fails cleanly.
- **The idle app no longer keeps a Mac busy.** The 500 ms queue refresh rewrote the empty-state
  headline on every round even when its text had not changed, and each write repainted the window;
  an idle app used about 40% of a core on macOS and now uses under 2%. The text is written only when it changes.
  The Transcription Queue tab had the same problem (about 36% of a core): the 500 ms refresh re-packed
  the empty-queue label, rebuilt the row list and re-set the action buttons every round. It now touches
  each only when it changed.
- **Resuming a job and time ranges no longer stall for ten minutes.** The ffmpeg that cuts the
  audio slice inherited the worker's command pipe as its stdin and, on Windows, hung at the end of
  the slice until its 600-second timeout; a resume then started over from the beginning. It now
  gets no stdin and finishes in about a second.
- **macOS: the About window opens over the middle of the main window** instead of off to one side.
- **macOS: the title bar follows an explicit Light or Dark theme.** With Dark chosen on a Light Mac
  (or the reverse) the main window and every dialog kept the system title bar; they now take the
  theme, and System still follows the Mac. `native_window_theme` (or `WTS_NO_NATIVE_CHROME=1`) turns it off.
- **macOS: File > Close Window works after a dialog was closed.** In the transcript viewer it did
  nothing once the Find dialog and an alert had been closed, because Tk reports no focus then even
  though the viewer is the front window. It now acts on the window macOS calls the key window (asked
  from AppKit) and still never on the main window.
- **macOS: Persian and Arabic file names read left to right in the queues and the Last result card.** Tk on macOS takes the line direction from the first strong letter, so "name.wav" was drawn as "wav.name" and the bullet or check mark jumped to the right end; the queue and download rows and the result card now start such strings with an invisible left-to-right mark, as Tk does on Windows (`app/theme/bidi_display.py`). Transcript lines are unchanged, and Windows and Linux are unaffected.
- **The idle app no longer keeps a Mac busy.** The 500 ms queue refresh rewrote the empty-state
  headline on every round even when its text had not changed, and each write repainted the window;
  an idle app used about 40% of a core on macOS and now uses under 2%. The text is written only when it changes.
- **Transcript viewer Save keeps every export in step.** Save rewrote only the SRT, VTT and ASS, so
  the TXT, Markdown, Word and the other exports kept the old text without a word. It now rebuilds
  each text and Word export that still matches the transcript it came from, with the same writers
  and the same title as the transcription. The check at open and the rebuild after Save run in
  worker threads (a Word file of 20,000 segments froze the window for 18 s each time); the JSON is
  written first. A file edited elsewhere (any Word part), a link, a file that changed while it was
  rebuilt, a PDF, the SMTV document and a file whose writer failed are named in a notice, say that
  they still hold the old text, and are left as they are; bilingual subtitles and the chapters
  file are named as not rebuilt.
  Quitting the app waits up to 30 seconds for a rebuild in progress, then names what was not rebuilt.
- **A long Last result list no longer squeezes the window.** With many output files the Last result
  card grew until the drop zone was cut off and the log pane shrank to one line. The file list now
  scrolls after four rows, and the Transcribe tab scrolls like the other tall tabs when the window
  is shorter than it.
- **Work offline: UDP and name-lookup gaps closed.** The network guard now also refuses UDP
  datagrams sent to another computer (`sendto` / `sendmsg`), the `gethostbyname`,
  `gethostbyaddr` and `getnameinfo` lookups and calls made on `_socket` directly, through a
  Python audit hook, and asyncio's Windows (Proactor) loop; before, a datagram to this computer's
  own LAN address was delivered while offline. A refused `connect_ex` now returns
  an error number (`EACCES`) instead of raising.
- **"System" theme on Windows no longer always means Dark.** It needed the optional `darkdetect`
  package, which the Windows builds do not contain, so the answer was always Dark. Windows now reads
  its own setting (`app/theme/system_appearance.py`); macOS and Linux still use `darkdetect`, and
  a missing package is now logged instead of silent.
- **macOS shows Mac wording and shortcuts.** Menus, buttons and the What's-new list now show the Command key and work with it (Command-O, Command-F, Command-S, Command-Return); the File menu has no Exit item on macOS (the app menu owns Quit) and the queued-tasks prompt says Quit; About no longer calls the app a Windows app, and the VLC hint mentions 32/64-bit only on Windows. Windows and Linux keep Ctrl and "Exit" unchanged (`app/shortcuts.py`).
- **Unsaved viewer edits are no longer lost on exit.** Closing the app (close button, File > Exit,
  Ctrl+Q, tray Exit, macOS Cmd+Q) while a transcript viewer holds unsaved edits now asks Save /
  Discard / Cancel for each such viewer, before anything is stopped. Save uses the viewer's own
  save and must succeed, otherwise the app stays open; minimise-to-tray never asks.
- **Settings changed after the first transcription were ignored.** Unticking "Identify speakers"
  (or changing VAD, word timestamps, chapters, noise reduction, the AI layer and the other per-file
  options) had no effect until the app was restarted, because the long-lived worker kept the
  settings it started with. Each task now carries a snapshot of these options taken when it is
  dispatched, the worker applies it to that task only, and a resumed task keeps the options it
  started with (`core/task_settings.py`). Keys without a control in the app (for example
  `batch_size`, `chapter_min_seconds`) are re-read from `config.json` for each task, so a hand edit
  applies to the next file.

- **Quitting during a job.** On macOS, Cmd+Q (and the app-menu and Dock Quit) now ask before
  quitting ("Quit with queued tasks?" on macOS, "Exit with queued tasks?" on Windows) instead of
  dropping a running transcription. A confirmed exit is recorded as
  closed on purpose, so the next start offers to resume it as "interrupted when the app was closed"
  rather than blaming a crash, and a worker whose app has gone logs one line instead of a
  `BrokenPipeError` traceback.

- **Closing the window ends the app.** A model download started inside the app (web server start,
  first-run model window, Live tab) runs on library threads that cannot be interrupted, and Python
  waited for them at exit: the window was gone but the process lived on, holding the single-instance
  lock, until the whole model had arrived. The process now ends right after the orderly shutdown
  (Sentry and logs flushed first, never waiting more than 3 s); an unfinished download resumes the
  next time. A package install in progress is stopped and its merge step is waited for (up to
  30 s) so no half-moved package folder is left; if one is left anyway (a crash, a power cut), the
  next start restores or removes it. Quitting also asks a running job to cancel before
  shutting its worker down, so the resume checkpoint is written (it was lost when the worker was
  killed after 5 s; the exit now allows up to 15 s), and a job that finishes during the exit,
  including one with no speech, is recorded as finished instead of being offered for resume again.

- **Worker output pipe on Windows.** A closed pipe is `OSError(22)` there, not `BrokenPipeError`, so
  the quiet handling added for macOS did nothing; it now covers both when the stream is the
  worker's own stdout. A single failed write that works on retry no longer silences the worker.

- **"Minimise to system tray" says why it is off.** Where the tray cannot work (macOS, or pystray / Pillow missing) the option is greyed out with a one-line reason, and Save leaves the stored choice alone.
- **No repeated "Online config fetch failed (404)" at every worker start.** The default `config_url` is not published yet; an HTTP 404/410 is now logged once at INFO and not retried for 24 hours (cache and built-in settings keep applying).
- **Log lines no longer carry signed-URL secrets.** Every log handler now cuts http(s) URLs to scheme, host and path (query string, fragment and user info dropped), so a signed model-download link no longer lands in `app.log`.
- **Server jobs keep paid text and no longer lose files.** A web/API job on a paid cloud engine that
  fails part-way now offers its finished text (`partial_srt`, also archived) instead of deleting it
  with the job folder; outputs are archived and the history row written before a job reads
  "finished"; a download that produced no file reports the size limit instead of "transcribing" the
  folder marker; a second server (GUI web access, `gui.py serve`, another window) no longer purges
  the first one's job folders (the marker names its owning process); a finished job's uploaded or
  downloaded media is deleted once its outputs are saved. If saving fails (disk full) the job shows
  a warning and its folder is kept until the copy succeeds; Cancel is refused once a job is ending.

- **The job server no longer starts a thread per connection without limit.** At most 64
  connections are served at once (a surplus client gets a 503 it can actually read, even
  mid-upload), idle keep-alive connections are dropped after 15 seconds, a client that trickles
  bytes is cut off at a time budget (an upload only when it stalls), at most 32 synchronous `/v1`
  requests may wait (a connection reset cancels the job; a closed or half-closed client keeps it), and a full job queue is answered
  before the upload is written to disk.
- **An English-only model no longer returns made-up English for a web request.** A web job or
  `/v1` request that names another language while the server's Whisper model is English-only
  (`tiny.en`, ...) is refused with a message naming a multilingual model.
- **Web page download links no longer put the password in the address.** With a password set,
  the page downloads through a header and saves the file from memory, and says why a download
  failed; the address stays free of `?token=` (browser history, download source mark, proxy logs).
- **Oversized web options are clamped instead of dropped.** `vad_min_silence_ms` and the speaker
  count are limited to the same ranges the project file allows.
- **A cloud run on a time range that failed part-way saved shifted subtitles.** The
  `.partial.srt` kept after the failure now carries the original file's timestamps, like a finished
  run, instead of times counted from the start of the range.
- **Make subtitled video: wrong file, silent failure, leftovers.** A download whose file name yt-dlp
  reported wrongly is no longer matched to another chain's hidden `.burn-*` temp, reserved
  `-subbed` placeholder or finished burn, and a folder with several equal candidates now ends the
  row as an error with a reason instead of transcribing a guess. A folder that refuses the
  `-subbed` file ends the row as an error with the reason and keeps the transcript listed. Closing
  the app stops a running burn (chained or manual) before it can start ffmpeg and removes its
  partial, work folder and empty placeholder; the next start removes what a crash left, from a
  journal it re-checks path by path. The watched folder skips only the app's own burn files, never
  a `-subbed` file the user copies in. A burned Persian line that mixes Latin words and digits
  (`... 1.9.3 ... macOS ...`) keeps its clause order, burned videos get the normal file mode
  (0644, not 0600), the macOS bundle check and the Windows install smoke test require ffmpeg's
  `subtitles` filter, and the picture check before the transcription waits at most 5 seconds.

- **An empty `model.bin` counts as not installed everywhere.** The model pickers, the Live tab's model check and the command-line `transcribe` only tested that the file existed, so a download killed halfway looked installed and the engine then failed on the empty file. They now use the same check as the rest of the app (`core.hub.model_weights_present`), which offers the download again.
- **Transcript viewer search folds Persian spelling.** The viewer's search box and Find & Replace now match through a half-space (ZWNJ), Arabic versus Persian kaf and yeh, vowel marks and digit styles, like the global search; Replace still rewrites only the matched part of the original text: a half-space, tatweel or vowel mark at the start or end of the needle must be literally next to the match (the letters between still fold), a decomposed (NFD) paste finds precomposed text, a match never cuts a ligature such as `U+FB01` or `U+FEFB` in half, and **Match case** turns all folding off. The viewer also pairs a transcript with `.aiff`, `.flv`, `.mts`, `.m2ts` and `.vob` media, from one shared list (`core/media_types.py`).
- **Same model advice for 3-5 GB computers.** Quick start gave Medium to a computer with 3-5 GB of memory while "Best for this PC" called it weak and offered Small. Both now use one memory line (`_WEAK_RAM_GB`, 5 GB) and pick the safer Small below it.
- **Chapters file no longer mistaken for the transcript.** With auto-chapters on and `json` not among the output formats, **View transcript**, **Save shareable page** and the word-count fallback opened `<name>.chapters.json` as if it were the transcript. They now share one lookup (`app/domain/task_outputs.py`) that skips the chapters sidecar and prefers the exact `<name>.json`. The queue menu's **View transcript** for a run without a `.json` now explains that the viewer reads `.json` files and offers the file picker.
- **Hardware detection and model advice.** GPUs without efficient float16 (GTX 10-series) now get
  an NVIDIA CUDA (int8) tier in the Hardware wizard, so Apply no longer pins the CPU over the
  automatic CUDA pick. Applying the untouched list while an NVIDIA GPU is unusable saves nothing
  instead of pinning the CPU. Tiers of backends the app does not bundle can no longer be saved.
  Quick start sizes "Best quality" to the computer's memory (a 4 GB PC gets Small, not Large v3);
  the advisor treats 8 GB laptops as capable, counts physical cores, treats unreadable memory or
  cores as weak instead of plentiful, follows a CPU setting in `config.json` or `hardware.json`, and
  no longer says "No usable NVIDIA GPU" on a Mac. Offline, both windows say so instead of promising a
  download, and the GPU-support question (550 MB) is not asked while Work offline is on.
  `python -m core.hardware` no longer fails on a redirected cp1252 console.
- **Optional installs and the NVIDIA Parakeet engine.** Installing GPU support after torch no
  longer deletes `nvidia/cudnn`: shared folders such as `nvidia/` are merged entry by entry. The
  macOS app says the NVIDIA engine cannot download packages instead of announcing an install, the
  engine list no longer shows it as ready when its package is missing, `cuda:1` picks the second
  card, and cancelling while paused stops before another window is decoded.
- **Portable ZIP has the sample clip and icons.** `build_embed_installer.bat` now puts `assets\`
  (window icon, toolbar icons, the "Try it now" sample clip), `LICENSE` and
  `THIRD_PARTY_NOTICES.md` into the build tree, so the Portable ZIP ships them too; the installer
  takes them from the same tree.
- **Upgrades keep your installer choices.** The installer removes the previous version only after
  you click Install (cancelling leaves it in place), keeps its folder and options (desktop icon,
  Explorer entry, voice cloning), waits until the old uninstaller has really finished and stops
  with a message if it fails. The lookup of the previous version now uses the real uninstall key
  name, and Setup asks you to close a running copy of the app first (copies from this version on).
- **Server uploads and downloads.** A non-English upload name keeps its characters (it was saved
  as mojibake); an upload cut off before its declared length no longer becomes a job (HTTP 400,
  chunked uploads get 411); a refused body is discarded within a time limit, so a trickling client
  cannot pin a connection. Job folders this version created and an earlier run left are removed
  at start (older than 6 hours), history rows point at a kept copy of the outputs, a link download can be cancelled and
  has a 4 GB / 2 hour limit, and the job list, webhook and error text no longer carry a link's
  query string. `docx` and `smtv_docx` in one job both surface; the detected language is set
  before a job reads as finished.
- **Cloud engines keep what they already paid for.** A rate limit, server error or timeout is
  retried with a growing wait (never a bad key), and a run that fails after some chunks keeps
  their text as `name.partial.srt` next to the source instead of discarding it. Words of Chinese,
  Japanese and Thai results from Google Cloud are no longer joined with spaces. Gemini now receives hotwords and the
  initial prompt in its prompt; Google Cloud says in the log that it ignores them.
- **Remote AI provider.** Rate limits and timeouts are retried, a cut-short or non-UTF-8 reply
  becomes a normal provider error, replies are size-capped, and a bilingual subtitle saved with
  untranslated segments says how many. The model download uses a part file of its own, so two
  downloads cannot overwrite each other.
- **Text to Voice: Play and Preview work on macOS and Linux.** They called a Windows-only
  function; they now open the file with the system's default app on every OS.
- **Text to Voice never redoes or loses finished work.** Generate on a finished long job offers
  **Use the finished file** instead of speaking everything again and overwriting it; a continued
  job shows the time for the pieces left; each piece is flushed to disk before it counts as done,
  and a piece found cut short (power cut) is spoken again instead of failing every join. Two app
  windows can no longer share one job: a lock file keeps **Start over** from deleting the other
  window's pieces.
- **A voice-clone job continues after a restart.** The job copies its reference clips into its
  folder and speaks from them, so a recorded clip swept from the 7-day scratch folder no longer
  strands the job; Generate with no clips puts the job's copies back in the list. The consent
  record names those copies.
- **Text to Voice splits and checks text better.** Thai and Lao without spaces are no longer cut
  between a leading vowel and its consonant; a scene-break piece (`***`, `---`) is not sent to the
  engine; Kokoro refuses a text mostly in a script none of its voices reads (Persian, Arabic,
  Russian, Korean, Thai, ...) before its 350 MB download and points to OmniVoice; OmniVoice gets one
  language code (`zh`, not `zh-Hans,zh-CN`).
- **Text to Voice safety checks.** A job the disk cannot hold never starts, even when it is too
  short for the confirm step; the voice controls (clips, consent tick, mode, voice, language) stay
  locked while a job is confirmed or runs; an empty OmniVoice result is an error, not a 0-second
  "Done"; OmniVoice's sample rate is read from the model; ffmpeg errors about a non-ASCII path stay
  readable; two runs in the same second get their own scratch folders; the speed store is written
  even while a reader holds it on Windows; the 7-day scratch sweep runs off the UI thread.
- **English-only models no longer turn other languages into wrong English text without a word.**
  Pairing an English-only model (`*.en`, the distilled models) with another language or Auto now
  opens a dialog in the Live tab (on Start and when the language or model changes) and before the
  Transcribe tab queues a file: it says what goes wrong and offers **Switch to <model>** (a
  multilingual model, downloaded if needed), **Choose another model**, **Keep** or **Cancel**.
  Unattended queueing (watched folder, transcribe after download) logs a warning instead, the Live
  tab no longer falls back to an English-only main model for other speech, and its model menu
  marks English-only entries.
- **Worker log lines keep their non-ASCII characters.** The transcription worker writes its
  output as UTF-8, so the log panel no longer shows a replacement character for the dash in
  worker log lines, and faster-whisper's English-only warning appears once per worker instead of
  once every live chunk.
- **Text grows evenly at 125 % and 150 % display scaling.** Buttons, entries, tabs and list rows
  kept the theme's 14-pixel font while labels and text boxes grew; the theme fonts and the list
  row height now follow the display scale, and fixed widths, column widths and wrap lengths
  scale with them.
- **Dark theme is readable.** Status colours (confidence, warnings, links, hints) and the
  transcript viewer's row tints get dark-theme variants with at least 4.5:1 contrast, and
  switching the theme recolours open windows. The hard-coded grey hints now use the theme
  tokens; the light-theme link colour also reaches 4.5:1.
- **Windows fit the screen.** The first window, the transcript viewer and the other dialogs fit
  the work area of their monitor (the taskbar no longer covers the bottom at 125/150 %) and are
  kept inside the screen at 100 % too.
- **Transcript viewer toolbar fits.** The tools are split into two rows, so "Open in Subtitle
  Edit" and the other buttons show their full labels at every scale.
- **Chinese file names and lines keep the Chinese font** when they contain the katakana middle
  dot, the prolonged-sound mark or the other marks Chinese shares with kana.
- **Typing in a long Clone Your Voice text stays smooth.** The script fonts are re-applied once
  per pause instead of on every keystroke (about 0.3 s per key for 100k characters of Myanmar).
- **Transcript viewer edits reach the subtitle files.** Save now also rewrites the SRT, VTT and
  ASS next to the JSON, unless one was changed elsewhere (for example in Subtitle Edit), which is
  left alone with a notice. **Open in Subtitle Edit** offers to save unsaved edits first and, when
  only a JSON was written, creates the SRT for it.
- **Transcript viewer never loses or mangles an edit.** Opening a transcript that is already open
  brings its window forward instead of a second copy whose Save overwrote the first; Save asks
  before overwriting a JSON changed by another program; **Replace** changes only the selected
  occurrence; Find next shows a match hidden by the search filter; a transcript or chapter file
  with a BOM, or a segment whose text, speaker or words are not text, no longer breaks the viewer.
- **Remove fillers keeps real words.** Fillers are now listed per language (none for a language
  without a list or an unknown one), matched as whole words, and the punctuation around them
  stays: German "Er ist" and Danish "Han er" are untouched, "Mm-hmm" stays whole and
  "Hello um, world" becomes "Hello, world".
- **File input takes what Explorer and Finder hand over.** A path pasted with Explorer's "Copy as
  path" (quoted), with spaces around it, or as a `file://` URI is accepted. A file dropped on the
  shortcut opens the app with that file picked, and macOS's `-psn_` launch argument no longer
  stops the app before its window appears; the Explorer "Transcribe with" command, which runs
  without a console, writes its output to `cli-transcribe.log` in the log folder.
- **Watched folder waits for finished files.** A new file is queued once its size and time stayed
  unchanged at two checks in a row; macOS `._` sidecar files and yt-dlp part files
  (`name.f137.mp4`, `name.temp.mp4`) are skipped, and a second event during the model load no
  longer queues the file twice.
- **Window opens on a connected monitor.** A saved position on a monitor that is no longer
  attached (Windows) is replaced by the default centred size. A wrong Subtitle Edit path in
  Advanced is now named in the "not found" message, and `%VARIABLES%` in it are expanded.
- **Live tab says when the microphone or the speech model fails.** A microphone that cannot be
  opened, is unplugged mid-session, or a speech worker that died used to leave "Listening…" over a
  flat meter. The tab now stops the session (what was captured is still transcribed), shows the
  reason, and hints when a microphone sends no sound or only digital silence.
- **Live tab cuts system audio at the right places.** System audio (and a microphone that only
  opens at its own rate) arrives at 44.1/48 kHz; it is now resampled to 16 kHz, so chunks are no
  longer cut ~3x too short and their times are right. A device that refuses 16 kHz is reopened at
  its native rate instead of failing.
- **Live transcripts are not lost on exit, and session audio no longer fills the disk.** Closing
  the app with an unsaved live transcript asks to save it, and anything still unsaved at teardown
  is written to the download folder. The full-session recording is deleted at Stop unless **Keep
  the audio** is ticked (`live_keep_recording`); a kept file's path is logged.
- **Live tab robustness.** Stopping no longer blocks the window when the transcription queue is
  full, a worker that fails every chunk ends the session after three failures, the worker's log
  lines reach the console through the Tk thread, and two sessions started within one second no
  longer share a folder. The read-only transcript now refuses paste, cut, Tab and the Ctrl editing
  keys, and copy works with Command on macOS.
- **Downloads with Persian, Arabic, Russian or CJK titles.** The bundled yt-dlp printed its file
  names in the Windows ANSI code page, so non-Latin characters vanished and the caption-only
  shortcut, the subtitle extras and the saved-file path pointed at no real file. Every yt-dlp call
  (Download tab and local server) now passes `--encoding utf-8`.
- **Download history keeps the real outcome.** A failed download closes its history row with the
  error text instead of showing "interrupted" on the next start; a paused and resumed download
  stays one row; cancelling a paused download closes its row too.
- **Cancel cleans up.** Cancelling a download removes its `.part`, `.ytdl` and fragment files and
  unmerged video/audio streams from the download folder; pause still keeps them for resume.
- **Subtitle language variants.** A subtitle language such as Portuguese, English or Spanish now
  also fetches its regional tracks (`pt-BR`, `en-GB`, `es-419`), without pulling in YouTube's
  machine translations; automatic captions in the subtitle extras (`.txt`, `.otr`, `.docx`) no
  longer repeat every line.
- **Out-of-date yt-dlp.** When this copy of the app cannot update yt-dlp itself (macOS app,
  package-manager builds), a failure that an old yt-dlp causes now says to install the newest app.
  A yt-dlp build whose updater refuses to update is remembered, so downloads no longer start the
  updater every time, and a `--version` call that fails once is asked again instead of turning
  off the YouTube helper until restart.
- **Smaller download fixes.** Time-range downloads get their own file name (`… (clip
  0.00.51-0.01.25).mp4`), so a re-run no longer reports the earlier full video; links with
  invisible direction or zero-width marks at either end (copied from right-to-left pages) are
  recognised; Supreme Master TV "Download all parts" looks the parts up without freezing the
  window, and an unknown page charset or a cut-off page now gives the normal SMTV error.
- **Transcript search finds Persian, Arabic and CJK words.** Chinese and Japanese words inside
  an unspaced sentence ("天气") are found through a trigram index, with a substring scan for
  one- and two-character words. Arabic kaf, yeh and alef maksura match the Persian kaf and yeh, a word typed without the ZWNJ
  matches the ZWNJ form, and accents, Arabic vowel marks, tatweel and digit forms are ignored
  (the same folding runs on the index and on the query). Deleted transcripts leave the index on
  the next pass, a BOM transcript is read normally, and an odd row (null/NaN/Infinity time, a
  number as text) no longer stops the file from being indexed or breaks later searches. The
  index rebuilds once after the update (`PRAGMA user_version`); a SQLite build without the
  trigram tokenizer falls back to the substring scan. **Reindex now** is greyed out while a
  pass runs.
- **PDF transcripts keep Russian, Chinese, Japanese, Persian and Arabic text.** The PDF writer
  used reportlab's built-in Helvetica, so every non-Latin letter became a placeholder glyph and
  the text was lost. It now draws each character with the first system font that has it (Arial,
  Microsoft YaHei, Yu Gothic, … on Windows; Arial Unicode, DejaVu, Noto, … elsewhere), nothing
  bundled; bold labels stay bold in every font, and zero-width joiners and direction marks no
  longer show as bars.
- **PDF transcripts in Persian, Arabic and Urdu read right to left with joined letters.** The
  PDF writer now shapes Arabic-script text with `arabic-reshaper` and orders right-to-left
  lines with `python-bidi` (new dependencies), breaking lines itself so each line reorders on
  its own; timestamps, numbers and Latin words keep their order and the timestamp sits at the
  right. Without the two packages the PDF is still written, unjoined, with one log warning.
  Zero-width joiners and bidi isolate marks are left out before shaping: with them the two
  packages dropped or repeated letters, or failed and lost the whole PDF.
- **Word transcripts in Persian, Arabic and Hebrew read right to left.** DOCX paragraphs whose
  text is mostly RTL letters now carry the Word bidi flag, RTL runs and a complex-script font,
  so they align right with punctuation on the correct side; bold timestamps stay bold there.
- **Plain formats keep the speaker.** TXT, LRC, TSV and oTranscribe output now start a diarised
  segment's text with its `Speaker: ` label, as SRT, VTT, Markdown, DOCX and PDF already did; TSV
  keeps its three columns, and a label never splits a line or hangs on an empty segment.
- **SMTV header names traditional Chinese.** `zh-TW`, `zh-HK` and `zh-Hant` codes no longer show
  as "Chinese (simplified)": the full tag and its longer prefixes are looked up before the base
  code.
- **Edits in the transcript viewer reach every subtitle format.** VTT and ASS wrote the
  per-word karaoke list in preference to the text, so corrections made with Find & Replace or
  filler removal vanished from those files and from Convert. The writers now use the text when
  the words no longer spell it (spacing-only edits keep karaoke, with spaces taken from the
  text, so CJK karaoke no longer gains spaces), and the viewer drops a stale word list on edit.
- **Subtitle text survives a write and a read-back exactly.** VTT now escapes `&`, `<` and `>`
  (text, words and speaker) and Convert decodes them; the SRT/VTT reader removes only known
  formatting tags, so "a < b and c > d" is kept; ASS braces and backslashes (`C:\new`, a
  literal `{\k5}`) and InqScribe text that looks like a timestamp now round-trip. Property tests
  cover every writer/reader pair.
- **Subtitle reader fixes.** A YouTube cue whose first line is a single space keeps its text,
  timecodes without milliseconds are read, unreadable timing lines are counted in the log, UTF-16
  and UTF-32 files are read and a legacy code page (Windows-1256) gets a clear message, and
  OpenAI-style `{"segments": [...]}` JSON is accepted.
- **Timing fixes in the writers.** ASS writes hours past 9 (long media no longer collapses onto
  9:xx:xx); ELAN, JSON and TSV fall back to the start for a missing end (ELAN used milliseconds as
  seconds); SRT and VTT skip blank cues and clamp an end before the start; a bilingual SRT cue
  with an empty original keeps its translation; the ELAN media link is a valid `file:` URI.
- **Chapter titles** no longer stop at "2.0", "Dr." or a leading "...", and chapters no longer
  crash on a missing start time or non-text segment text.
- **Burned-in Persian, Arabic and Chinese subtitles render correctly.** On Windows the burn now
  uses Tahoma for Arabic-script text and Microsoft YaHei for Chinese (the default font drew a
  missing-glyph box inside common Persian words and mixed Chinese glyph weights), and every
  right-to-left line is wrapped in invisible RLM marks so a final "." "!" or "»" stays at the end.
- **Burn subtitles never replaces its source.** Saving the burned video under the source video's
  own name is refused instead of overwriting the original, and a temp folder whose path holds
  `,` `;` `[` `]` or `'` no longer breaks the burn.
- **Task actions use the files the job really wrote.** After a re-run (`name (1).srt`) or with an
  output template, **Burn subtitles into video** and **Export → oTranscribe** read the task's own
  SRT instead of the previous run's `name.srt`, **View transcript** plays the task's source media
  (the viewer also pairs `name (1).json`, `name.en-translated.json`, `.opus`, `.mov`, `.m4v`, `.avi`,
  `.wma` and `.ts`), and **Open folder** / "Saved N files in …" show the outputs' folder.
- **oTranscribe export asks before replacing an `.otr`** that may hold your edits (replace, keep
  both, or cancel) and writes atomically with LF line ends; importing an `.otr` keeps paragraphs
  typed without a timestamp, and a JSON with a BOM exports too.
- **ELAN, InqScribe and Express Scribe outputs get the extensions those tools open.** Transcriptions
  now write `.eaf`, `.inqscr` and `.txt` (they wrote `.elan`, `.inqscribe` and `.express_scribe`),
  the same names File → Convert uses. Existing `.elan` / `.inqscribe` files still convert. With
  both TXT and Express Scribe selected, the second is `name.express_scribe.txt`.
- **File → Convert never overwrites an existing file.** When the default target exists the output
  goes to `name (1).ext`; the write is atomic, and a source with no cues is an error instead of an
  empty file over the old one. Converted ELAN/oTranscribe/Markdown files no longer name the
  transcript file as their media or title.
- The word-count fallback of a translate run reads `name.en-translated.json`.
- **The loop guard no longer deletes real repeated speech.** Three identical lines in a row used to
  be collapsed to one, so a prayer's "Amen." x4 or a chorus lost text with only a log line. Now only
  back-to-back copies count (gap under 0.25 s, each under 5 s): runs of 3-7 such copies are kept and
  marked `repeated-line` for review, and only 8 or more are treated as a decoder loop and dropped
  to one line (that limit is by design; each dropped run is logged with its span).
- **Cancel, pause and progress work while a loop is dropped**, and the guard never restarts a
  decode once the job is cancelled; a cancelled run keeps its checkpoint at the last kept line.
- **A resumed job saves checkpoints while it runs**, so a late crash no longer repeats the whole
  remaining part, and a cancel on its last segment skips the post-processing. A decoder error in
  the middle of a file saves the segments decoded since the last checkpoint before it is reported.
- **"No speech recognised" is said** in the log, the Last Result card and the history record when a
  file produces no text; the (empty) output files are still written.
- **Interrupted checkpoint writes are cleaned up at startup.** The sweep looked for `*.json.tmp`
  while the writer names its scratch `<key>.json.<random>.tmp`. A non-default `vad_window_s` or
  `loop_guard_repeats` now joins the checkpoint fingerprint, so a changed setting cannot resume a
  partial made with the old one.
- **LAN/web server jobs no longer die at their first checkpoint.** The server's task object lacked
  the checkpoint-failure counter the engine reads every 10 segments or 20 s, so a longer job ended
  with an `AttributeError` and no output.
- **Two jobs waiting for one loading model no longer lose a worker.** A second caller (watched
  folder, crash resume) waiting for the same loading worker used to burn the full wait (2 min, 20
  on macOS) and then shut down the worker the other job was using; every waiter now wakes on
  ready, and the wait ends when the window closes.
- **The window no longer freezes for seconds after a temporary worker's last job.** The worker
  is stopped on a helper thread; closing the app still waits for it.
- **A worker whose process died without a final message no longer leaves its job "running"
  forever.** After 10 seconds the job is ended as failed. A worker that fails to start or dies
  idle no longer leaves a dead entry behind.
- **Voice cloning worker:** an unwritable log folder no longer stops it before it starts, and a
  malformed, deeply nested output line no longer stops its reader.
- **The Kokoro voice model download resumes.** Cancelling or losing the connection keeps the
  partial file (~350 MB), and the next try continues it instead of starting over; a damaged
  archive is removed so the retry starts clean.
- **Feature installs check free disk space first** (torch-based features need about 3 GB), both
  before pip starts and before its files are copied into place, with a clear message instead of
  a failed copy. Two app windows or workers no longer install into the extras folder at the same
  time, and a package locked by the running app asks to reopen the app.
- **The model download window's elapsed time** restarts when a download is retried in another
  folder.
- **Watched folder and folder drag-and-drop take more formats:** `.ts .m2ts .mts .vob .wmv .wma
  .avi .m4v .3gp .flv .mpg .mpeg .mka`. A `.ts` file that is TypeScript source is skipped.
- **Settings are no longer lost or reverted.** A moment when `config.json` could not be opened
  (another save in flight, an antivirus scan) used to rename the good file aside and reset every
  setting; it is now retried and the file kept. A damaged file is replaced by its `.bak`, a file
  saved in the Windows ANSI code page is read, and a refused save is retried and then reported
  (Advanced stays open and shows the error).
- **The app's own save no longer undoes other processes' changes.** Saving writes only the keys
  the app changed over the current file, and counters go through one locked transaction, so the
  cloud-minutes counters a worker records (and the free-tier warning that reads them) survive the
  save after each job and at exit. The online model catalog is no longer copied into
  `config.json`, so a corrected entry reaches every user; a hand-written `config_url` now survives
  saves too.
- **Old copies of the model catalog are cleaned up.** Earlier versions copied the shipped model
  catalog into `config.json`, where it hid later fixes. On the first launch, a copy identical to
  a catalog a release shipped is removed (the previous file stays as `config.json.bak`); a
  catalog with any hand edit is kept.
- **Privacy switches fail closed.** A damaged or hand-edited value of Work offline, usage
  statistics or the update check now reads as offline / off instead of on, `"true"` and `"false"`
  strings are understood, and a switch whose saved choice was lost with a damaged file stays
  closed in every process. Saving Advanced no longer reverts a File-menu Work offline change made
  while it was open.
- **Settings survive more edge cases.** A `config.json` with a UTF-8 BOM is read; a settings save
  that finds another process holding the lock waits up to 8 s and then reports a "busy" error
  instead of writing over that process's change; nested objects merge field by field; a copy made
  with `cfg.copy()` still saves only its changes; a damaged file is never overwritten when it
  cannot be kept as `.corrupt`; `config.json.bak` is rotated atomically.
- **A restore from the backup keeps the network off.** `config.json.bak` is the generation before
  the last save, so it may predate turning Work offline on: any restore from it (and any read that
  cannot know the saved choice) now turns Work offline on and usage statistics and the update
  check off, and writes that back, until the user changes them again.
- **The Help-menu update dot clears after a release is withdrawn.**
- **An oversized `.whisperproject.json` is ignored** (over 1 MB) instead of being parsed on every
  job.
- **A half-downloaded Whisper model no longer looks installed.** A model folder without its
  `model.bin` (a killed download) now brings up the download prompt instead of failing in the
  worker with "Unable to open file 'model.bin'", also when offline or when the mirror's checksum
  list is unreachable; offline, such a folder is left as it is.
- **Model downloads resume.** A retry keeps huggingface.co's unfinished files, so an interrupted
  multi-GB download continues instead of starting from zero; a model that came from huggingface.co
  is no longer checked against the zip mirror's checksum list on the next launch.
- **Clear model download errors.** The error box now says why a download failed (not enough disk
  space, huggingface.co unreachable or blocked, both sources' reasons), the free space is checked
  before a zip download and before unpacking (a finished archive is kept), a model folder on a
  missing drive offers another folder, and a login page answering the checksum list counts as a
  network problem. The AI Layer model download refuses a truncated file.
- **Never two speech models, never an orphan worker.** Transcribe no longer starts a second model
  worker while one is still loading (for a watched folder, crash resume or a download), and Cancel
  then Generate in Text to Voice waits until the cancelled voice worker is gone. When the app dies,
  its transcription worker (even with a paused task, which keeps its resume checkpoint) and its
  voice worker now exit instead of running on unseen; a timed-out yt-dlp update now ends the whole
  update process tree on time.
- **Resumed transcriptions are not offered again.** After "Yes" to "Resume interrupted
  transcriptions?", the offered rows (duplicates of the same file too) are retired, so the next
  launch does not ask again; a second app instance no longer marks the first one's running jobs
  as interrupted.
- **Closing the window could leave the app running.** Exit cancelled pending timers in a way that
  broke the teardown of the scrollable tabs, so the window stayed half-empty and the process kept
  running; the window now closes and the app ends. Exit also hides the window before it stops busy
  workers (which now stop together, so a model or engine switch no longer freezes the window for
  several seconds per worker), and closing during "Starting…" of web access no longer waits for
  the first-run model download.
- **Errors no longer vanish silently.** An error in any window callback, and a crash while the app
  starts, now goes to `app.log` with a short message; one failing step no longer stops the queue
  pump, a worker that dies before its exit is reported no longer leaves its task "running", and a
  stray non-object line from a transcription or Live worker no longer ends the reader.
- **File names and transcript lines in Indic scripts, Sinhala, Thai, Lao, Khmer, Myanmar, Chinese
  and Japanese are drawn in full on Windows.** Text boxes and lists use Segoe UI instead of
  Courier New or Windows 10's Arial fallback, at the same box and row heights, and Sinhala and
  Myanmar a font of their own (`app/theme/script_fonts.py`); list rows long enough for Tk to split
  a cluster keep the default font, except Sinhala rows with joined conjuncts, which the default
  font would pull apart. Chinese and Japanese get a regional font in text boxes and one-column
  lists, chosen by kana or by the transcript's language where the app knows it (not for a
  transcript opened from the file picker).
- **The test suite no longer writes into the real per-user folders.** Tests used to add log
  files, history rows and job folders under the developer's own app data and could reach the real
  `config.json`; an autouse fixture now redirects every platformdirs user folder to a temp tree,
  with a guard test that fails if the redirect breaks.
- **"Use captions instead" no longer fails while the browser is open.** When yt-dlp cannot copy
  the browser's cookie database (`Could not copy Chrome cookie database`), the caption fetch now
  retries once without browser cookies and logs one line saying so, as the media download already
  did. The caption step that runs before a download got the same fallback.
- **The yt-dlp updater no longer carries a "rejected" mark over to a replacement file.** The
  mark is matched by file size and modification time, so a new copy written in the same timer
  tick as the rejected one could be refused too. Copying the bundled binary into place now
  drops the old record; a new test pins the two files to the same size and time.
- **A resume checkpoint is no longer lost when two writers race for the same source.**
  Writing it retried a locked target only five times (about 0.2 s); on a busy machine
  that ran out and raised `PermissionError`. The retry is now bounded by time (1 s).
- **A stuck checkpoint file no longer slows a transcription.** A read-only or permanently
  locked checkpoint target made every periodic write wait out the retry window. The window
  is now 1 s, and after three failed writes in a row the periodic writer stops for that run
  (cancel and final writes still try; outputs and history save as before). A write that fails
  with any exception type now removes its scratch file.
- **Long recordings with music no longer lose most of their speech.**
  faster-whisper ran the Silero VAD over the whole file in one pass, so after
  loud music its state could stay at "not speech" for minutes: on a 62-minute
  lecture it kept 512 s of speech where a fresh state every 30 s finds
  1,615 s, and the lost minutes came out as one-word segments. The VAD state
  is now reset every 30 s (`vad_window_s`, `core.vad_window`).
- **A repetition loop no longer runs to the end of the file.** When three
  segments in a row have the same text, decoding restarts from the second one
  without the previous text as a prompt (once per file); later runs are cut to
  one line, and checkpoints never hold the loop (`loop_guard_repeats`,
  `core.loop_guard`).
- **`gui.py transcribe --formats/--diarization` no longer change the app's
  saved settings**; they apply to that run only. `--model` is still saved, as
  its help says.
- **Word times of a Transcribe-tab time range were not moved onto the file's
  timeline** with faster-whisper 1.1+ (its segments became dataclasses), so
  words of a range starting at 100 s were stamped from 0 s.
- **Turning usage stats off now sticks.** The Advanced dialog's choice was
  stripped from `config.json` on every save, so stats came back on at the
  next start. An OFF choice is now saved and kept; the online app config can
  never set `telemetry_opt_in` (`LOCAL_ONLY_KEYS`). The default stays on.
- **macOS: the bundled yt-dlp could be blocked by Gatekeeper after a
  browser download** ("can't be opened because Apple cannot check it", then
  killed). Every file of a browser-downloaded `.dmg` is quarantined; the app
  now removes that flag from its own bundled yt-dlp/ffmpeg/deno at every
  start (`core.paths.clear_bundled_quarantine`), and `test_dmg.sh` checks
  it. The macOS build also refuses a `bin/yt-dlp` that is yt-dlp's Python
  script instead of the self-contained `yt-dlp_macos`: the script runs on
  whatever `python3` the Mac has, and an app opened from Finder gets Apple's
  Python 3.9, which yt-dlp no longer supports ("Only Python versions 3.10 and
  above are supported by yt-dlp", seen on v1.9.3 after such a swap). The app
  itself runs on its bundled Python 3.12.
- **macOS: the Live tab could never get the microphone.** macOS 10.14+
  terminates an app that opens the microphone without
  `NSMicrophoneUsageDescription` in its Info.plist, and no build had the
  key. The `.app` (PyInstaller spec) and the `install.command` launcher now
  declare it, and `verify_mac_bundle.sh` fails a bundle that lacks it.
  `install.command` also stopped stamping a hard-coded `1.3.6` as the
  launcher's version; it reads `core.__version__`.
- **Every transcription failed in a fresh install or build made on or after
  2026-09-29** with `open() got an unexpected keyword argument
  'metadata_errors'`. PyAV 19.0.0 (released 2026-09-29) removed that
  argument of `av.open()`, which faster-whisper 1.2.1 still passes when it
  decodes audio, and faster-whisper only requires `av>=11`, so pip picked
  the new release. Found by the macOS build's smoke test (both archs).
  `av>=11,<19` is now pinned in `requirements.txt`, `pyproject.toml` and
  `constraints-macos.txt`; an existing venv needs `pip install "av<19"`.
  Builds and installs made before 2026-09-29 (including the v1.9.3
  downloads) are not affected.
- **macOS: the "Loading the Whisper model" dialog was off-centre** (placed
  by its top-left corner). It now uses the dialog's requested size.
- **Advanced settings: Save/Cancel could sit under the macOS Dock** on a
  1280x800 screen. The dialog now fits above the Dock and keeps the button
  row visible when the window is short.
- **macOS app: word-timing refinement (stable-ts) offered a 700 MB download
  that could not work** in the packaged app (it has no pip). The app now
  says the feature needs a source install and continues without it.
- **"Model not downloaded yet" stayed on the Transcribe tab** after the
  model downloaded on first use. The engine and model lines now refresh.
- **Slow Macs: YouTube format lookups could time out** or lose the Deno
  helper (the macOS yt-dlp needs ~25 s just to start on an older Mac). The
  version check and the format lookup now wait up to 2 minutes.

### Security

- **The Windows build bundles FFmpeg 9.0.2.** The pinned FFmpeg (a 2026-05-06 snapshot) lacked the
  fixes for six published FFmpeg vulnerabilities (CVE-2026-8461, -30998, -30999, -66038, -70629,
  -70631), which matter because the app decodes files and streams it did not create. The pin in
  `platform/windows/build-deps.json` and the source offer in `platform/ffmpeg-source.json` now name
  the gyan.dev 9.0.2 essentials build (same GPL configuration) and the official 9.0.2 source.
- **Dependency floors match what ships.** `Pillow` now needs 12.3.0 or newer (35 published advisories
  hit the old 10.0 floor; the SMTV tab opens image bytes from a remote site), `numpy` is declared
  (`>=1.26,<3`, it is imported directly), and `tokenizers` and `pywhispercpp` are listed in
  `pyproject.toml` the way `requirements.txt` and the installers already had them. A test keeps the
  two files and the macOS constraints in step.
- **No credential file can enter a build.** The macOS spec no longer bundles a Google Cloud key
  file found in the build folder (the Windows builds had already dropped this), and a test fails
  when any spec, the build script or an installer script names a credential file.
- **Web pages can no longer drive the local web server.** JSON job requests need
  `Content-Type: application/json` (else 415), the page cannot be framed or loaded by another
  site, and without an access password the server refuses requests from another web origin and
  answers only addresses that name this computer directly (IP address, `localhost`,
  `host.docker.internal`, its name), which stops cross-site job submissions and DNS rebinding.
  With a password, another origin must send it in a header, not in `?token=`.
- **The access password stays out of logs and links.** A `?token=` value is logged as
  `token=[redacted]`; the browser page now accepts a link with `?token=` (it answered 401) and
  removes it from the address bar; `gui.py serve` uses the app's Access password unless `--token`
  is given (`--token=` serves without one). Webhook URLs are logged by origin only.
- **Server error messages no longer show paths on the server**, and an upload with a very long
  file name is saved under a shortened name instead of failing.
- **A silent client can no longer freeze the server.** Idle connections close after 60 seconds,
  the HTTPS handshake runs on the client's own connection with a 10-second limit (one idle
  connection used to stop every HTTPS request), the body of a refused upload is read for at most
  10 seconds, and on Windows a second server can no longer bind a port that is in use.
- **A `.whisperproject.json` in a downloaded or shared folder can no longer redirect your data.**
  Project files may now only set per-file transcription choices (formats, prompt, voice detection,
  speakers, chapters and similar; list in `docs/CONFIG.md`). Engine, URL, API key, token, webhook,
  stats, AI, server, folder and model keys are ignored and logged once by name, so such a file can
  no longer send audio, transcripts or your keys to another service. Numbers outside a sane range
  (a 0-second chapter, a huge batch) are dropped too.

## [1.9.3] — 2026-09-27

Windows, macOS and Linux. (There is no 1.9.2.)

### Fixed

- **A link copied from inside a playlist downloaded the whole playlist.**
  Downloads now fetch only the linked video.
- **A video with no sound failed with "tuple index out of range".** It now
  says the file has no audio track.
- **Chrome/Edge/Brave cookie errors on Windows** now suggest Firefox instead
  of "close the browser", which does not help there.
- **NVIDIA GPUs were never used (#7).** Hardware Autodetect called a
  CTranslate2 function that does not exist, so every machine silently fell
  back to CPU. It now uses the real API; a CPU choice saved by the old
  probe is re-checked automatically.
- **A GPU that fails on its first real use falls back to CPU at load time**
  (one short warm-up pass), instead of failing the first transcription.
- **"Save and use" in Hardware Autodetect takes effect right away** (it
  needed an app restart), and the one-time "running on CPU" warning now
  appears when an NVIDIA GPU is present but unusable.
- **The link check on paste now uses the browser log-in cookies** too, so
  Instagram/Facebook links no longer fail it when cookies are set; a
  "login required" error says what to do.
- **The first-download prompt, the engine status line and the CLI show the
  selected model's real size** instead of always "about 3 GB".
- **"Engine: Checking…" can no longer stay forever** (falls back to the
  quick status after 15 s).
- **Changing the model while a transcription runs asks first** instead of
  stopping it silently.
- **The SMTV "Download all parts" checkbox no longer overlaps the format
  status line.**
- **Frozen builds call `multiprocessing.freeze_support()`** before anything
  else.
- **The GPU-to-CPU fallback frees the failed GPU model first**, so a large
  model is no longer held in memory twice while the CPU copy loads.
- **The "running on CPU" check no longer freezes the window**: it runs once
  per session in the background instead of on every model load.
- **The CLI downloads a Whisper model only for the faster-whisper engine**
  (other engines load their own way).
- **Saving Advanced settings no longer undoes a cookie pick** made in the
  Download tab meanwhile.
- **The web server says why a URL job for a local address is refused.**

### Changed

- **Settings are simpler**: the Google Cloud and Gemini setups are folded
  away (click to open), the VAD sliders sit behind "Fine-tune", and buttons
  are no longer clipped on small screens.
- **The window fits laptop screens** (sized to the screen; tall tabs
  scroll).
- **`requirements.txt` no longer installs stable-ts** (it pulled in torch +
  CUDA, ~5 GB); word alignment installs it on demand as before.

### Added

- **YouTube works again without a system Deno (#8)**: yt-dlp is given a
  JavaScript runtime, and the Download tab offers a one-click, checksum-
  verified **Install YouTube helper** (Deno, ~42 MB, no admin rights). It is
  only passed to a yt-dlp new enough to use it; otherwise the error says to
  update yt-dlp. The Windows installer and Portable ZIP ship Deno in
  `bin\`, so YouTube works there with no click at all.
- **Hardware Autodetect explains an unusable NVIDIA GPU** (reason + fix),
  offers **Install GPU support** (NVIDIA cuBLAS, ~550 MB) when that is the
  missing piece, and **Copy diagnostics** for bug reports
  (`python -m core.hardware` prints the same report).
- **"Log-in cookies" picker in the Download tab** (same setting as Advanced
  settings; Safari is now offered on macOS).
- **"Best for this PC…"** next to the model picker suggests the fastest and
  the most accurate model for this computer's GPU or CPU/RAM.
- **CLI: `transcribe --model SLUG`**, and a missing model is downloaded
  instead of failing with "model not loaded".

## [1.9.1] — 2026-09-24

macOS-only release: assets rebuilt from master with the pending commits
that had landed after 1.9.0 shipped; then rebuilt again the same day to
also fix real-world video downloading (coworker QA feedback against 1.9.0
flagged both issues).

### Changed

- **Video Tiling now restricted to an approved-URL allow-list** —
  following coworker QA feedback, Start Tiling refuses any URL not on a
  short pre-approved list (one entry today), instead of accepting any
  stream.

### Fixed

- **Downloading videos was broken in the packaged macOS app** — none of
  the bundled `ffmpeg`/`ffprobe`/`ffplay`/`yt-dlp` tools were actually
  resolvable at runtime. PyInstaller's macOS `BUNDLE` step relocates all
  of them into `Contents/Frameworks/bin/` and leaves nothing at
  `Contents/MacOS/bin/`, which is the path `core.paths` (used by the app
  itself) actually resolves tools through — so every one of them silently
  fell back to a bare name via `PATH` lookup, which fails on a real user's
  Mac. (Transcription still worked because it decodes audio via the
  bundled PyAV wheel, not the external ffmpeg binary.) The packaging spec
  now symlinks every `Contents/Frameworks/bin/` entry into
  `Contents/MacOS/bin/` so `core.paths` finds them.
- `platform/macos/pyinstaller/smoke_test_app.sh` and `verify_mac_bundle.sh`
  now check that same `Contents/MacOS/bin/` runtime path and hard-fail the
  build if a bundled tool is missing there (no network needed — this alone
  would have caught the regression above). The smoke test also attempts a
  real, non-simulated download + ffmpeg merge through that path; on a real
  machine (e.g. the release VM) that's a hard failure too, and only
  degrades to best-effort on `GITHUB_ACTIONS` runners specifically, since
  their IPs are routinely YouTube-bot-blocked regardless of the app.

## [1.9.0] — 2026-09-23

The macOS assets were built from `0bbabc3`; the Windows Setup + Portable
were built later from master and also include the first block below.

### Windows build additions

#### Added

- **New "Supreme Master TV" tab** — an introduction to the channel (watch
  live, about, schedule) plus its video library: search, program shortcuts,
  28 site languages, thumbnail cards with Watch / Download / Transcribe.
  Nothing is fetched until the tab is first opened.
- **Live tab: its own "Model:" choice**, defaulting to Tiny (keeps up on any
  computer). Downloaded models show in bold, missing ones greyed with a
  Download button right there. "Automatic" and any catalog model can be
  picked. The Live language now defaults to English.
- **Clone Your Voice / Text to Voice: a model picker and ready-made voices.**
  Kokoro (54 voices, 9 languages, fast on CPU, ~350 MB on first use) needs
  no recording; OmniVoice can now also design a voice (gender, age, pitch,
  accent) or pick one itself. Language, speed, and text up to 5,000
  characters (was 500).

#### Changed

- **Live tab level display: iOS 9-style Siri waves plus a peak meter**
  (green/yellow/red, peak hold, dB readout) instead of bars (ported from
  SiriWave, MIT).
- **Tab order**: Transcribe, Queue, Download Videos, Live, Clone Your Voice
  / Text to Voice, Video Tiling, Web / LAN access, and Supreme Master TV
  always last.
- **Live tab auto-detect locks the language after the first confident
  chunk**, instead of re-detecting on every chunk (which doubled the time
  each chunk took).

#### Fixed

- **Background checks started while the window was being built could lose
  their result** (e.g. the engine status line at startup): the app's
  main-thread queue now exists before any tab is built.
- **Live tab Stop no longer throws away speech still waiting to be
  transcribed.** The microphone stops at once and the rest is finished;
  pressing "Discard rest" skips it.

### Added

- **Pick the Whisper model straight from the Transcribe tab** — a "Model:"
  row under the existing "Engine:" row, with a "✓ Downloaded" hint. No need
  to open Advanced settings just to change model size.
- **See and change the model folder** in Advanced settings' "Model & engine"
  section (view the path, "Change…", "Open folder").
- **Clone Your Voice / Text to Voice** — a new, independent tab, off by
  default and opt-in at install time: record or load 1-3 short reference
  clips, type text, and generate that text spoken in the cloned voice via
  OmniVoice (Apache-2.0), running locally. Downloads its ~2GB speech model
  on first use; fully offline after that.

### Changed

- **Advanced settings is shorter.** An engine's setup section (Gemini,
  Google Cloud, NVIDIA Parakeet) now appears only while that engine is
  picked, and the remote-LLM fields only while the Remote provider is
  picked. VAD, denoise, Demucs, hallucination flagging and the noisy-audio
  preset moved into one "Silence & noise" section.
- **Removed four settings that weren't pulling their weight**: the
  cross-file voice fingerprint checkbox (nothing in the app ever read it),
  "Transcribe after download" (the Download Videos tab has its own), "Batch
  size (CUDA only)" and "Output filename template" (both still settable in
  `config.json`). "Word alignment" is now a plain checkbox.

### Fixed

- **Portable / run-from-source users lost their settings and models after the
  rename.** Only the Windows installer carried data over from the old
  `WhisperProject` profile; the app now does it itself on launch (copies
  settings/history, reuses the old model folder, moves the whisper.cpp / LLM
  model caches), so already-downloaded models are no longer reported missing.
- **Clearer reason when Hardware Autodetect falls back to CPU on a CUDA
  GPU.** The self-healing CUDA→CPU downgrade used to always blame missing
  cuDNN/cuBLAS runtime libraries. It now recognizes the separate case where
  the GPU's compute capability is simply newer than the installed
  CTranslate2 build supports yet (reported for an RTX 5060/Blackwell
  `sm_120` laptop GPU, #7) and says so instead of pointing at the wrong
  cause.
- **Clone Your Voice / Text to Voice hardened further** (still off by
  default, unreleased). A follow-up adversarial review found and fixed two
  real bugs — every generation failure was silently freezing the tab with
  no error shown, and Cancel could be silently ignored right after the
  one-time setup finishes — plus several smaller leak/UI-freeze issues.
  A reference clip longer than 10s is now trimmed automatically instead
  of only being warned about and used untrimmed.
- **The Live tab could get stuck on "Loading the speech model…" forever**
  if starting a live session failed for any reason — no error dialog, no
  way to tell it had actually failed. The error-handling callback itself
  was silently crashing before it could show anything.

### macOS

- **The macOS app actually works now, and was tested on a real Mac.**
  Earlier `.dmg` builds bundled a Homebrew ffmpeg without its ~18 dylibs
  (and built for macOS 15 only), no working yt-dlp, and declared the wrong
  minimum macOS. The build now bundles self-contained ffmpeg/ffprobe/ffplay
  + yt-dlp, verifies every file in the `.app`, and reads its version from
  the app. Intel build runs on macOS 10.15+. Details:
  `docs/MACOS_BUILD_NOTES.md`.
- **`install.command` (run from source) no longer aborts on Intel Macs**
  (sdist-only PyAV, optional pywhispercpp compile failure) and no longer
  installs stable-ts there, whose torch crashed every transcription
  (`OMP: Error #15`).

## [1.8.0] — 2026-08-23

### Added

- **Remote LLM provider.** Advanced Settings' AI Layer section can now
  point the summarize/action-items/ask/translate tools at your own
  OpenAI-compatible endpoint (OpenAI itself, or a self-hosted
  Ollama/LM Studio/OpenRouter) instead of only the bundled local model.
- **Chapters + AI Tools tabs in the transcript viewer.** The right panel
  is now a Media/Chapters/AI Tools notebook: Chapters lists the sidecar
  chapter file and seeks the player on click; AI Tools exposes
  summarize/action items/ask, plus a per-segment translate pass that
  saves a bilingual `.srt` (original + translated line per cue).
- **Transcript search** — `Help > Search transcripts...` opens a
  full-text search dialog over your transcripts.
- **"Apply noisy-audio preset" button** in Advanced Settings — one click
  sets VAD/denoise/hallucination-detection to values reasonable for
  non-studio audio, instead of five separate sliders.

### Fixed

- **A failed format lookup (Facebook, Instagram, or any other site) now
  tells you why.** Previously, once yt-dlp's initial probe failed, the
  Download button just repeated "Wait for formats to load" forever — the
  real error sat in a small, easy-to-miss status label and never reached
  the download log. Clicking Download now shows that real reason (and
  logs it), instead of a dead-end message that implies the app is still
  loading when it has already given up.
- **A download could fail even for a fully public video.** With "Cookies
  from browser" on and the browser still open, yt-dlp's own cookie-jar
  read failed and broke the download outright — even when the video
  never needed cookies. It now retries once without cookies before
  giving up.
- **CLI log lines could crash mid-run on Windows** when a file name held
  a character the console's legacy codepage cannot encode (e.g. an
  emoji pulled from a social-media title) — the console now substitutes
  the character instead of raising.
- **Bilingual-subtitle translations could come back wrapped in stray
  quote marks** (a local-LLM quirk on short segments) — now stripped
  before the line is written to the `.srt`.
- **Transcript search dialog:** pressing Escape could leave a background
  search/reindex touching an already-closed window; a slower, older
  search could overwrite a newer one's results; the results list itself
  was invisible due to a Treeview parenting bug. All three fixed.
- **The AI panel could keep using a stale LLM provider** after Advanced
  Settings' provider/URL/key/model was changed while the transcript
  viewer stayed open.

## [1.7.0] — 2026-08-15

### Fixed

- **`save_config()` refuses a drastic silent shrink and keeps a backup** —
  a real config.json was found silently reduced from ~90 keys to 3 keys
  during ordinary use this cycle; the root cause was not pinned down
  despite a real, instrumented investigation. Saving now refuses to
  write a config with under 40% of the key count currently on disk
  (logging an error instead), and keeps a rotating `config.json.bak` of
  the last good state on every normal write.

- **Editing "Hotwords" in Advanced settings could be silently undone** —
  saving Advanced settings correctly wrote the new hotwords to disk, but
  the Transcribe tab kept its own frozen copy of whatever hotwords value
  existed when the app launched (left over from a UI redesign; that copy
  has no visible field of its own). Merely changing the language dropdown
  or the "Identify speakers" / "Word timestamps" checkboxes afterward
  re-saved preferences using that stale copy, overwriting the fresh
  Advanced-dialog edit with no warning. Fixed by no longer writing that
  stale copy back into config.

### Added

- **Advanced settings: "Enable VAD (skip silent segments)" checkbox** —
  Voice Activity Detection was always on with no way to turn it off from
  the desktop app, even though the engine and the optional LAN/web server
  both already supported disabling it. The three VAD tuning sliders (min
  silence, threshold, speech pad) now grey out while it's unchecked.

### Security

- **"Convert transcript" ELAN (`.eaf`) import: reject a DOCTYPE** — a
  crafted `.eaf` with a `DOCTYPE`/entity block could previously hang or
  balloon memory ("billion laughs") when imported; such files are now
  refused outright with a clear error. Found during an attacker's-eye
  pass over the whole codebase; every other input-parsing path checked
  in that pass (SSRF guard on the online-config URL, zip-slip guard on
  the model download, upload path/filename sanitising in the LAN server,
  constant-time token compare) was already hardened.

### Fixed

- **Engine-status / hardware-probe background threads hardened against a
  native-fault risk class** — a real Windows native fault was traced to
  Python's garbage collector running mid-import of a heavy optional
  package on a background probe thread. Every such probe now disables GC
  for its risky operation. See ADR 0008 in `docs/DECISIONS.md` for the
  full investigation.

- **That same GC-import guard used 10 separate locks instead of one
  shared lock**, so two probes on different threads did not actually
  serialize against each other and could still race. Found in a
  second-pass review; factored into one shared
  `core._gc_import_guard.gc_disabled_import()`.

- **Semantic search silently scored dimension-mismatched embeddings** —
  a stored embedding from a different model/dimension than the current
  query embedder was compared anyway via `zip()`, which silently
  truncates instead of erroring. `core.search._semantic_query` now
  skips a dimension-mismatched row.

- **`requirements.txt` no longer bundles `google-cloud-speech` /
  `google-cloud-storage`** — leftover from when a bundled service-account
  key made Google Cloud STT the default engine (see "Retired: the bundled
  Google Cloud key" above). Now genuinely on-demand via
  `core/optional_deps.py`, like every other optional backend.

### Added

- **Transcript viewer: "Edit timestamp..." (right-click a segment)** —
  hand-edit a segment's start/end time (HH:MM:SS.mmm). Only that segment
  changes; a resulting overlap with the previous segment or a sub-1s
  duration gets a light-orange row highlight as a warning, never a
  blocked save. Inspired by a comparable faster-whisper GUI's editable
  timestamp table.

- **Download tab: "Clear completed" button** — the Queue tab has always
  had one; the Download tab was missing the parity button (owner-noticed
  gap while reviewing the frontend, 2026-08-15).

- **LAN web page: source preview, Reset, Copy-transcript, Recent jobs** —
  picking a file now shows an instant local audio/video preview; a Reset
  button clears the form back to defaults; the transcript view has a
  one-click Copy button; and the Submit view shows the last 3 jobs so you
  don't have to switch tabs to see something is still running. Ergonomics
  borrowed from `voice-pro`'s Gradio frontend (see
  `docs/GAPS_VS_VOICE_PRO_2026.md` item 7) without adding Gradio itself.
- **Advanced dialog: "Restore transcription defaults" button** — resets
  the VAD, hallucination-detection, alignment, batch size, denoise,
  Demucs, auto-chapters and voiceprint options back to their defaults in
  one click. Deliberately scoped to per-job tuning knobs only — output
  formats, the hotwords/prompt text, model/backend choice, watched
  folder, and cloud credentials are left untouched. Nothing is written
  until you click Save, so Cancel undoes this too.

- **Advanced dialog: consistent section headers + a split-up "Whisper
  extras"** — the 3 cloud/NVIDIA sections now use the same short-title +
  hover-help header as the other 7 (previously plain, long run-on titles
  with no hover-help). The old 10-row "Whisper extras" grab-bag is now two
  focused sections, "Model & engine" and "Prompt, hotwords & output
  naming". Part of an ongoing readability pass (owner request,
  2026-08-14) — more rounds land alongside this one.
- **Advanced dialog: hover-help on every output format + a few more bare
  spots, and a grouped nav sidebar** — each of the 15 output-format
  checkboxes (SRT/VTT/ELAN/InqScribe/Express Scribe/etc.) now has a
  one-line "what is this" tooltip instead of a bare acronym; the Google
  Cloud "Cloud Storage bucket" field, "Detect speakers" checkbox, and
  "Minimise to system tray" checkbox gained tooltips too. The "Jump to"
  sidebar now groups its 11 links under small captions ("Alternate
  engines", "App preferences") so the 3 opt-in cloud/NVIDIA sections read
  as clearly optional rather than blending into one long list.
- **Advanced dialog: 3 more hover-help gaps closed** — the AI Layer's
  "Enable local LLM" and "Generate auto-chapter markers" checkboxes and
  the Downloads section's "Transcribe after download" checkbox now
  explain themselves on hover, matching every other control in the
  dialog. The "Enable local LLM" caption also no longer overclaims
  summary/Q&A support it has no UI for yet.

### Fixed

- **Hover-help icons were technically working but easy to miss** — the
  owner reported seeing no tooltips despite earlier sessions saying this
  was done. Root-caused with a real OS-level mouse-move + screenshot test
  (not Tk's synthetic events, which earlier sessions relied on): the
  popup mechanism itself was fine, but the "ⓘ" glyph was the same size
  and weight as body text. Now bigger and bold everywhere it's used
  (Advanced dialog, all tabs, Live tab, transcript viewer).
- **Installer: Video Tiling defaulted to installed, worded as a
  confusing double-negative** ("Do NOT include the Video Tiling
  feature", unticked by default = installed). Now a plain, positively
  worded opt-in checkbox, unticked by default = not installed (owner
  request, 2026-08-15).
- **Error dialogs could open on the wrong monitor** — the same
  negative-coordinate clamping bug already fixed for tooltips
  (`max(x, 0)` yanks a dialog onto the primary monitor even when its
  parent window lives on a secondary monitor placed to its left).
  `error_dialog.py` now only clamps when the parent itself is on the
  primary display.
- **Live tab transcript couldn't be selected/copied by dragging the
  mouse** — `state="disabled"` blocks all mouse interaction on a Tk
  Text widget, not just typing. It now stays selectable/copyable; a
  `<Key>` filter blocks typing instead (Ctrl+C/Ctrl+A and navigation
  keys still pass through).
- **Advanced dialog silently cleared "Detect speakers" for Google Cloud
  STT** — saving with that backend selected always reset the diarization
  checkbox back off, even though the backend has fully supported
  diarization since it was added. It now saves correctly; the tooltip
  explains the real caveat instead (speaker numbering restarts each
  ~1-minute chunk in Standard mode).
- **Live tab's default "Microphone" source did not work out of the box** —
  `sounddevice` (and, on Windows, `PyAudioWPatch` for the "System audio"
  source) were never in `requirements.txt`, so no shipped install actually
  had them; every user hit "sounddevice not installed" the first time they
  opened the Live tab. Both now ship by default, like the app's other small
  UI dependencies (`tkinterdnd2`, `python-vlc`), instead of requiring a
  manual `pip install` a non-technical user has no way to run.
- **Download tab: typing a Start/End time directly left the position
  slider stale, and the next drag on either slider silently discarded
  the typed value.** `_on_download_scale` only ever wrote slider ->
  field, never the reverse, so a manually-typed time was invisible to
  the sliders until something moved one and snapped it back to 0:00:00.
  Typing now moves the matching slider too. Found in a same-day
  self-review (real running app, not just source reading), verified
  with a real before/after screenshot.
- **Nine fixes from an adversarial frontend review** (`app/` only, isolated
  from the rest of the repo) — download queue selection was lost on every
  event tick (now preserved, matching the transcription queue); the yt-dlp
  auto-update check poisoned its 24h retry backoff on any timeout/failure;
  download error detection missed yt-dlp's lowercase `[error]` lines;
  one bad download event could wedge the whole download progress pump;
  relocating the model hub folder could silently redirect a different
  model's path to `large-v3`'s cache folder; switching engines mid-job now
  warns before force-stopping active work instead of silently killing it;
  a live-worker write path used `assert` for a check that vanishes under
  `-O`; the transcript viewer's right-click menu could leave a stuck
  pointer grab; and the hub-setup dialog's "Cancel" button (which doesn't
  cancel) is now labeled "Skip for now".
- **Eight more fixes from a second adversarial review** (same isolated
  `app/`, this time `claude-opus-4-6-thinking`) — a download-service
  refactor from the round above had left a duplicate self-re-arming timer
  that compounded on every progress event; a secondary-monitor tooltip
  could render on the wrong screen edge (negative-x `wm_geometry`); one
  locked/failing file in a watched folder could stall every other file
  queued behind it on every drain tick; the Live tab could raise
  `UnboundLocalError` inside its own crash handler; the model-download
  dialog could close with no error shown if the underlying exception had
  no message; the console's Copy (not Copy All) silently did nothing while
  the log widget sat disabled; a hand-edited config with quoted monitor
  indices was silently dropped instead of coerced; and Esc now confirms
  before cancelling a running transcription or download instead of killing
  it on one accidental keystroke.

## [1.6.0] — 2026-08-12

> Live tab + adaptive denoise release. Real-time microphone/system-audio
> transcription, an opt-in noise filter that measures before it acts, ASS/SSA
> subtitle output with real karaoke timing, a Windows source-install updater,
> and a fix for an `nvidia_asr` dependency clash that broke every build since
> whenever `tokenizers` last shipped a release newer than `transformers`
> accepts. pyright `app/ core/` 0/0/0; hermetic suite green.

### Security

- **No cloud credential is bundled any more, and the old one is revoked.**
  Builds since v1.3.9 shipped a maintainer-owned Google Cloud service-account
  key inside the package, which also made Google Cloud STT the default engine
  — every install transcribed through one shared account. The key was revoked
  by the maintainer; the build steps that copied it are removed. See
  [SECURITY.md](../SECURITY.md).

### Added

- **`platform\windows\update.bat`** — a one-command updater for a source
  (git clone) install on Windows, matching what Linux already had. It
  refuses to run against an installed build, and verifies the app still
  imports afterwards. The installed app's own update check stays
  notify-only on purpose.
- **ASS / SSA subtitle support** — a new `ass` output format, and `.ass`
  / `.ssa` files can now be converted *from* as well. ASS is what video
  editors and karaoke tools expect, and it is the first format that
  carries our per-word timings as real karaoke highlighting; speaker
  labels go in its dedicated actor column instead of being glued onto
  the subtitle text.
- **The README is now available in 7 more languages** — Chinese, Japanese,
  Korean, German, Spanish, French and Portuguese — reachable from a flag
  switcher at the top of each one. They are generated by
  `tools/make_i18n_readmes.py` so the layout and links cannot drift apart.
- **New Live tab: transcribe a microphone or the system audio as it
  happens.** Text appears as you speak instead of after a file finishes.
  Chunks are cut at natural pauses so words are not split in half,
  silence is never sent to the model, and the tab says so when the
  machine cannot keep up rather than skipping audio silently. System-audio
  capture is Windows-only. See [LIVE.md](LIVE.md).
- **Adaptive audio denoise before transcription** (**Advanced > AI Layer**,
  off by default). Cuts hallucinated lines and misheard words on noisy
  recordings. It measures each file first and leaves already-clean audio
  untouched, then checks its own output and falls back to the original if
  the filter removed speech instead of noise. Bundled ffmpeg only — no
  extra download or dependency. See [DENOISE.md](DENOISE.md).

### Docs

- **26-way STT model comparison** across all 8 Google Cloud STT v2 models
  and all 18 local faster-whisper models on a hard real-world clip (weak
  audio, overlapping speakers). Found a real hallucination bug in the
  Whisper Large-v3-Turbo family (fabricates unrelated text on ambiguous
  audio) — confirms the app's `large-v3` default over Turbo. See
  [STT_MODEL_COMPARISON_2026-08.md](evaluations/STT_MODEL_COMPARISON_2026-08.md).

### Changed

- **The default engine is always offline faster-whisper.** It no longer flips
  to Google Cloud STT because a key file exists next to the app. Cloud STT is
  now reached only by an explicit pick in **Advanced > Backend** with your own
  service-account JSON.
- **Resuming a cancelled job now re-checks the pre-processing settings.**
  Changing vocal separation or denoise between cancel and resume used to
  splice differently-conditioned halves into one transcript; the partial is
  now invalidated and re-run instead.
- **A failed or cancelled transcription no longer posts usage
  stats.** It used to send a fake "0 words, 0:00" row indistinguishable
  from a genuine empty transcription — e.g. every job against a backend
  with no valid key. The local history record is unaffected; only the
  external stats POST is now skipped for a non-success.

### Fixed

- **The `nvidia_asr` (Parakeet) backend could fail to import on a freshly
  built installer with a `tokenizers>=X,<=Y is required` error.** The
  bundled `faster-whisper` pinned `tokenizers` only loosely, so a build done
  on the wrong day could bundle a `tokenizers` release newer than
  `transformers` accepts, and the on-demand `nvidia_asr` install could never
  override it. `tokenizers` and `transformers` are now pinned to a verified
  matching pair, `docs/BUILD.md` has a re-check step before every release
  build, and the backend's error message and status probe both report the
  real cause instead of a generic import failure.

## [1.5.0] — 2026-07-03

> SMTV release. The SMTV docx header now shows the detected language, SMTV
> and oTranscribe join the Convert-transcript targets, and the format
> picker shows each target's real file extension in a curated
> (common-first) order. The project (and its GitHub repo) is renamed to
> `whisper_app`.
> pyright `app/ core/` 0/0/0; hermetic suite green.

### Added

- **SMTV docx header now shows the detected language.** Row 2 / column 3
  used to always read the literal "Foreign Language"; it is now replaced
  with the language faster-whisper detected (e.g. "Korean"), matching the
  title row and the "[... starts]" cue that already did this. With no
  detected language the header keeps its original generic text.
- **SMTV added to File → Convert transcript.** The format picker now
  offers `smtv_docx` alongside the existing text targets. Since a generic
  transcript file carries no language metadata, the emitted docx is filled
  the same way the writer already treats "no language detected" (neutral
  cue labels); the work title is taken from the source file's name.
- **oTranscribe (.otr) added to File → Convert transcript.** `.otr` was
  already importable there but not offered as an output — the app could
  only export it from a live transcription task or a downloaded subtitle,
  never from an arbitrary transcript file already on disk. A new
  `core.writers.otr` (backed by a new public
  `core.integrations.otranscribe.segments_to_otr()`) closes that gap.
- **Convert-format picker is more user-friendly.** A human-simulation pass
  on the dialog found the combobox showed bare internal registry names
  (`elan`, `smtv_docx`, `otr`, …) in plain alphabetical order, so there was
  no way to tell what file extension a pick would actually produce, and the
  four formats almost everyone wants (`srt`/`vtt`/`txt`/`json`) were buried
  among niche ones. It now shows `name (.ext)` for every target (via a new
  `core.convert.output_extension_for()`) and lists the common four first.

### Fixed

- **NVIDIA Parakeet could fail to load with a confusing `tokenizers>=X,<=Y
  required` error** — the `tokenizers` copy bundled at build time (pulled in
  by faster-whisper) could drift newer than the on-demand `transformers`
  install accepts, and retrying the on-demand install could never fix it
  (the bundled copy always wins on `sys.path`). `transformers` and
  `tokenizers` are now pinned to a verified-compatible pair, and both the
  error message and the Advanced-dialog status line now name the real
  cause up front instead of only surfacing it after a failed transcription.
- **A failed alternative engine (whisper.cpp / cloud / NVIDIA) startup
  misdiagnosed as a missing Whisper model** (2026-07-18) — the app
  force-opened the mandatory ~3 GB Whisper download modal and buried the
  real error in the console. It now shows the engine's own error dialog
  instead.
- **Liveness watchdog killed a healthy worker during a first-run engine
  download** (2026-07-18) — the worker's heartbeat thread only started
  after the model load, so a multi-GB silent download (NVIDIA HF weights,
  whisper.cpp ggml) blew the 120 s timeout and restarted the worker in a
  loop. The heartbeat now starts before the load.
- **Engine-status probe crashed its thread on Python 3.14**
  (2026-07-18) — it called `self.after()` off-thread; now routed through
  `post_to_main()` like every other background-thread callback.
- **NVIDIA backend: unrecognised-architecture load errors now say the
  real cause** (2026-07-18) — e.g. `nvidia/nemotron-3.5-asr-streaming-0.6b`
  needs `transformers >= 5.14`; older versions failed with a generic
  message. Verified end-to-end: with transformers 5.14.1 that model loads
  and transcribes correctly through the GUI.
- **macOS dmg build scripts now arch-suffix the output filename**
  (2026-07-18) — `builddmg.command` / `compileall-whisper-mac.sh` derive
  x64/arm64 from `uname -m`, so a single-arch build can no longer ship
  under an arch-less (or "universal") name.
- **SMTV docx filename was not actually fixed** — a colleague reported the
  "Convert transcript" / transcription SMTV output "sometimes" landing under
  an unexpected `(1)`/`(2)`-suffixed name. Root cause: `_write_outputs`
  computed one shared re-run-safety index across ALL requested formats,
  including `smtv_docx` — so a pre-existing `.srt`/`.json` from an earlier
  run pushed the SMTV file to a numbered suffix on its very first write,
  even though no SMTV file had been written for that source before.
  `smtv_docx` is now excluded from the shared index and always resolves to
  its documented fixed, recognisable filename (overwriting in place on
  re-run, which is the intended "one canonical team file" behaviour).
- **`stats_url` hyphen/underscore mismatch** — the published
  `configuration.json` (the online-config master copy) pointed at
  `transcription-stats.php` (404) while `core/config.py`'s
  `DEFAULT_CONFIG` pointed at the real `transcription_stats.php` (200).
  Anyone whose effective config resolved the online copy would have had
  usage stats silently go nowhere. Fixed to agree; added a
  regression test so the two can't drift apart unnoticed again.
- **macOS build didn't work** — the `arm64`/`x86_64` `.dmg`s built by
  Claude and uploaded 2026-07-04 were broken (owner-reported, no repro
  details available). A colleague built a working replacement and it
  was uploaded 2026-07-15, replacing both prior macOS assets. On
  2026-07-18 the colleague clarified it is Intel/x64-only (not
  universal), so the asset was renamed
  `WhisperProject-v1.5.0-macOS-x64.dmg`.

### Changed

- **Project renamed** `whisper_project_direct_download_v2` →
  `whisper_app` (GitHub repo + local checkout folder name). The
  update-checker, `pyproject.toml` project URLs, the Homebrew formula,
  and the clone instructions in the READMEs / install docs now point at
  the new repo name.
- **`.otr` (oTranscribe) added to File → Convert transcript** — it was
  already importable there but never offered as an output; a new
  `core.writers.otr` closes the gap (also shows up as a transcription
  output checkbox in Advanced settings, same registry).
- **Convert-format picker** now shows `name (.ext)` for every target and
  lists the four common formats (srt/vtt/txt/json) first, instead of
  bare alphabetically-sorted internal registry keys.
- **macOS builds added to this release** — `WhisperProject-v1.5.0-macOS-
  arm64.dmg` / `-x86_64.dmg`, built via `macos-app.yml` on real Apple
  Silicon + Intel runners (the underlying `compileall-whisper-mac.sh`
  duplicate-invocation bug is fixed). Same version, no separate macOS
  release notes — Windows and macOS ship the same v1.5.0 feature set.

## [1.4.0] — 2026-06-22

> Engine cleanup + safety release. Removes the dead-end sherpa-onnx Parakeet
> engine in favour of the working transformers-based one, adds a "Prepare
> model now" button for it, stops a handful of app-level config keys from
> ever being persisted to disk, makes the Windows installers silently clean
> up the previous version before upgrading, and fixes the SMTV docx output's
> stale modified timestamp. pyright `app/ core/` 0/0/0; hermetic suite green.

### Added

- **"Prepare Parakeet model now..." button** in Advanced settings (NVIDIA
  Parakeet / FastConformer section) — installs `transformers`/`torch`/
  `librosa` and downloads the model ahead of time, mirroring the existing
  whisper.cpp download button, instead of the user discovering the wait mid-
  transcription. New `nvidia_asr` extras group in `pyproject.toml`
  (`transformers`/`torch`/`librosa`) for source checkouts that want to
  pre-install the backend's deps the same way `backend_cpp`/`alignment` do.
- Both Windows installers (`installer.iss`, `installer_embed.iss`) now
  silently uninstall a previously-installed version (looked up via the
  registry by the shared `AppId`) before laying down new files, so an
  in-place upgrade can no longer leave orphaned files behind from a version
  that removed/renamed something. The hub-folder deletion prompt is skipped
  during that automatic step (`UninstallSilent` guard) so a multi-GB model
  hub outside the install dir is never wiped without an explicit, interactive
  Yes. `installer_embed.iss` also moved its `config.json` cleanup (added by a
  colleague's `167ccf8`, originally an unconditional `[UninstallDelete]`
  entry) into the same `UninstallSilent`-guarded code path — otherwise every
  silent upgrade triggered by the new pre-install step above would have
  wiped the user's `hub_folder`, API keys, and preferences on every release.

### Changed

- **Removed the incomplete sherpa-onnx `parakeet` engine** from the engine
  picker. It duplicated the now fully-working `nvidia_asr` (transformers)
  Parakeet backend but never got a model downloader, so selecting it just
  produced a permanent "model files missing" warning with no way to fix it
  from the UI.
- `core.config.save_config` now strips `telemetry_opt_in`, `config_url`,
  `stats_url`, `ffplay_downloads`, and `latest_version` before writing
  `config.json` — these are re-derived from `DEFAULT_CONFIG` / the online
  config fetch on every load, so persisting them only risked pinning a stale
  value across an upgrade. Also cleans them out of any `config.json` that
  already has them from before this rule existed.

### Fixed

- The SMTV transcription `.docx` output's "modified" document property no
  longer carries straight through from the bundled template — every
  generated docx now reports the actual transcription time instead of
  whenever the template was last authored.

- **Local NVIDIA Parakeet / FastConformer engine** (`nvidia_asr`) — a new
  **fully offline** transcription engine that runs a Hugging Face transformers
  `automatic-speech-recognition` model entirely on this machine (no audio leaves
  the device). The default is NVIDIA's transformers-native multilingual
  FastConformer model `nvidia/parakeet-tdt-0.6b-v3`; it is configurable via
  `nvidia_asr_model_id` to any transformers ASR model id or local folder. Pick
  "NVIDIA Parakeet TDT v3 — local" in the Transcribe-tab engine picker or
  Advanced > Backend. The heavy libraries (`transformers` + `torch` + `librosa`)
  and the model weights are not bundled — they install / download on first use (a
  few GB, one time), like the openai-whisper backend, so the base install stays
  slim. The file is transcribed window by window (`nvidia_asr_chunk_seconds`) for
  progress + cancel; word timestamps are used when the model provides them, else
  one segment per window. New config keys `nvidia_asr_model_id` / `_device` /
  `_dtype` / `_chunk_seconds` (see [`CONFIG.md`](CONFIG.md)). New module
  `core/backends/nvidia_asr.py`; registered in the engine factory, the shared
  `availability` registry, the Advanced dialog, and `optional_deps`. Hermetic
  tests in `tests/core/test_nvidia_asr.py`; verified end-to-end on real speech
  with `parakeet-tdt-0.6b-v3`. pyright `app/ core/` 0/0/0; hermetic suite green.
  (NVIDIA's exact `nemotron-3.5-asr-streaming-0.6b` repo ships only a NeMo
  `.nemo` checkpoint that transformers cannot load — its parakeet sibling is the
  default; a different model needs the NeMo toolkit.)

## [1.3.9] — 2026-06-08

> Frontend-stability + cloud-default release on top of v1.3.8. Adds an engine
> picker to the Transcribe tab so the transcription engine can be chosen without
> opening Advanced settings, makes Google Cloud STT the default engine in trusted
> builds that ship a key (fully offline faster-whisper otherwise), and folds in a
> small batch of frontend stability fixes. pyright `app/ core/` 0/0/0; hermetic
> suite green.

### Added

- **Transcribe-tab engine picker** — choose the transcription engine (offline
  Faster-Whisper, whisper.cpp, Parakeet, Gemini cloud, Google Cloud STT) right on
  the Transcribe tab, with a readiness line (✓ Ready / ⚠ needs setup) for the
  chosen engine. Switching the engine restarts the worker so the change takes
  effect on the next transcription. The engine list + availability live in the
  new `core/backends/availability.py` shared by the tab and the Advanced dialog.
- **Google Cloud STT as the default engine** in builds that bundle a
  service-account key (`creds/gcloud_stt.json`, never committed — gitignored,
  build-tree only); a source checkout with no key stays fully offline on
  faster-whisper. The Advanced dialog now shows when the bundled key is loaded
  and auto-runs the connection test on open.

### Fixed

- **Worker stdin reader** could park forever on a Windows pipe — now uses a
  bounded `readline` so short JSON commands return promptly.
- **Checkpoint probe** no longer needs `model_path` set: it resolves the model
  folder from the configured model + hub folder, so the ~3 GB download dialog is
  not shown when the model is already present.
- **Download time-range sliders** no longer cross over — dragging one knob past
  the other snaps both so the visible range stays valid.
- **Engine switch now restarts the worker.** The live worker snapshots the
  backend at spawn and the dispatch preferred that stale value, so a switch did
  not take effect until the process restarted; both the picker and the Advanced
  dialog now stop the worker on a backend change.
- **CLI** `transcribe --formats` choices come from the writer registry (so
  `smtv_docx` is accepted) and the CLI reports the real written paths + live
  progress.
- The Advanced dialog refuses to save the unsupported Google Cloud STT +
  diarization combination.
- **Offline-model download has a HuggingFace fallback.** When the smch.ir
  mirror 404s / fails for a model, the same model is fetched from
  huggingface.co via faster-whisper's own download map — which resolves each
  model's correct upstream repo (e.g. `large-v3-turbo` →
  `mobiuslabsgmbh/...`, `distil-large-v3.5` → `distil-whisper/...`, not the
  `Systran/...` guess that 401'd).
- **Google Cloud STT client is now bundled** in the slim tree (was installed
  on first use), so the cloud engine works immediately with no "could not
  install … check internet" wait, and grpcio is built for the bundled
  Python so it can't be shadowed by a wrong-version cache.
- **On-demand extras dir is appended to `sys.path`, not prepended**, so a
  bundled library always wins over a stale on-demand copy in the user cache
  — repairing machines whose pylibs held a broken, wrong-Python grpcio.
- **Transcribe-tab readiness is a real check now** — the engine status line
  genuinely probes (model on disk, client actually imports, key present) on
  a background thread instead of always reading "Ready".
- **Advanced settings order** — the less-important Gemini "Google API key"
  field now sits below the Google Cloud Speech-to-Text section.

## [1.3.8] — 2026-06-06

> Hardening release on top of v1.3.7: the Phase 1–6 feature work (Google
> Cloud / Gemini cloud STT, the optional LAN/web server, transcript-format
> conversion, the SMTV team `.docx`, the multi-monitor Video Tiling rewrite,
> three-level merged config, multi-model picker, ffplay
> auto-download, and macOS groundwork) **plus a 44-finding adversarial audit
> fixpack** — every finding independently confirmed by skeptic review and
> covered by a hermetic regression test. pyright `app/ core/` 0/0/0; hermetic
> suite green.

### Fixed — adversarial audit fixpack (44 confirmed bugs)

- **Data loss:** transcript-format conversion overwrote the source file in
  place on a case-only extension difference (Windows); cloud STT collapsed a
  whole file into one chunk when the duration was unreadable (truncating long
  transcripts); the SMTV `.docx` writer rendered a literal `"None"` for a null
  segment.
- **Crashes / launch failures:** a non-finite (`Infinity`) numeric in a
  hand-edited config crashed startup; a non-string `model.name` crashed config
  load; the Advanced dialog's free-text Batch-size field crashed Save; a
  non-`dict` `words` entry crashed conversion; the TSV writer raised on
  non-finite timestamps; a non-ASCII LAN-server auth token bricked the server.
- **Reliability / concurrency:** the tray exit latch stayed stuck after a
  declined quit (minimise-to-tray broke permanently); a stopped-then-restarted
  Video Tiling run could revive the old worker; the LAN server leaked a worker
  (and the hot model) when a paused job was stopped; download pause/resume and
  the tiling run-token had races/TOCTOU windows; sqlite reads raced the writer
  thread.
- **Windows process teardown:** a graceful kill of the yt-dlp/ffmpeg tree could
  orphan the process and hold the file handle — now escalates to a forced kill.
- **Resource / security:** the LAN multipart upload was fully buffered in RAM
  (now streamed); JSON bodies and the online-config fetch are now size-capped;
  `stats_url` and URL-job hosts get scheme / SSRF validation; aborted optional
  pip installs no longer orphan their child tree.
- **Smaller correctness:** LRC timestamps no longer emit `:60.00`; SMTV episode
  URLs with a query string / fragment are recognised; per-chunk cloud
  diarization labels stay consistent; cloud RPCs have timeouts and honour
  cancel; the multi-monitor index is now a stable total order.

### Added

- **Optional LAN / web server mode.** `python gui.py serve` starts a
  stdlib-only HTTP server (no new dependency) so a phone or another PC can
  send a file or a URL to transcribe from a browser. It binds to loopback
  (`127.0.0.1`) by default — no Windows firewall prompt — and `--lan` is an
  explicit opt-in to listen on the local network. Optional `--port`,
  `--host`, `--token` (shared-secret gate) and `--max-upload-mb` (upload
  cap). The page and a small JSON API accept an upload **or** a URL job,
  poll progress, and download the result; transcription runs in-process and
  sequentially so the ~3 GB model stays hot, behind a bounded queue. Jobs
  are recorded to history. New Tk-free `core/server/` package; new config
  keys `server_port` / `server_max_upload_mb`. (Verified live on this
  machine: `GET /api/health`, `/api/formats`, and `/` all 200.)
- **Optional Google Gemini cloud Speech-to-Text backend** (`cloud_stt`).
  Paste a free AI Studio API key and transcribe over the Gemini API via
  stdlib REST (default model `gemini-3.5-flash`, configurable), with chunked
  upload through the Files API. A loud privacy opt-in makes clear this
  **uploads your audio to Google and breaks the offline guarantee**. An
  honest *local* minutes-used counter (the $300 free credit is **not**
  readable from an API key, so we don't pretend to show it) plus a link to
  Google's billing console. New config keys `cloud_stt_api_key` /
  `cloud_stt_model` / `cloud_stt_minutes_used` / `cloud_stt_free_minutes_cap`
  / `cloud_stt_chunk_seconds`. *(The real end-to-end Google call is
  UNTESTED here — no API key in this environment; live-test with your own
  key before relying on it.)*
- **Opt-in update check** (notify-only — it never auto-installs). A new
  `core/updates.py` queries the GitHub releases API; a Help-menu "Check for
  updates" runs it on demand and a throttled quiet check runs at launch. It
  is silent on a private repo, offline, or when already up to date. New
  config keys `update_check_enabled` / `last_update_check`. Also documented
  that the Standard installer already upgrades **in place** over the
  previous version (stable Inno `AppId` — no uninstall needed).
- **Always-visible per-task action bars** under both Queue tabs —
  Pause / Resume / Cancel / Re-run / Remove buttons on each row (plus a
  click on the status cell to toggle), so the controls are discoverable
  without the right-click menu (which, with Esc, still works). Download
  "pause" is **stop-and-continue**: it keeps the `.part` and resumes via
  yt-dlp `-c`/`--continue`; pause is disabled for Supreme Master TV
  downloads, which have no resume point.
- **Multi-monitor Video Tiling.** The Tiling tab was rewritten from a
  single-screen `ffplay tile=NxN` into a Tk-free multi-monitor engine
  (ported from the maintainer's `video-tiler` v1.1): one download is fanned
  out to one `ffplay` per selected monitor, with `poll()` liveness,
  exponential-backoff reconnect, self-healing `yt-dlp -U`, more robust
  extraction (player-client fallbacks, retries, height-based format),
  http(s) URL validation, and clean teardown via
  `core._proc.kill_process_tree` (fixes orphaned ffmpeg/yt-dlp children).
  New `core/monitors.py` detects screens (screeninfo → ctypes Win32 →
  single-monitor fallback). UI adds Quality / Mute / Multi-monitor and a
  "Monitors…" chooser with Identify and Auto-restart. New config keys
  `tiling_quality` / `tiling_mute` / `tiling_multi_monitor` /
  `tiling_selected_monitors` / `tiling_auto_restart`. New optional
  dependency: **screeninfo** (multi-monitor degrades gracefully without it).

#### Phase 2 (added later in the same local batch)

- **Real Google Cloud Speech-to-Text backend** (`google_cloud_stt`) — a
  second, more capable cloud option alongside the simple Gemini one. It
  authenticates with a **service-account JSON file** (not a pasted key) and
  uses the official `google-cloud-speech` **v2** client, which is installed
  **on demand on first use** (via `core/optional_deps.py`) — not bundled.
  Two modes:
  - **Standard / online** — decodes with the bundled ffmpeg, splits the
    local file into ≤ ~55 s chunks, calls `recognize()` inline per chunk,
    and offsets + stitches the timestamps. No Cloud Storage needed
    (~$0.016 / min).
  - **Batch** — uses v2 `BatchRecognize` through a user-supplied Google
    Cloud Storage bucket (`gs://`) with `DYNAMIC_BATCHING` (~$0.004 / min,
    ~75 % cheaper) at the cost of up to ~24 h turnaround.

  Supports word-level timestamps and speaker diarization. The earlier
  Gemini backend (`cloud_stt`) is **kept** as the simpler paste-a-key
  alternative; both are clearly labelled in the UI. *(The real Google Cloud
  network path is **UNTESTED** here — no service-account JSON in this
  environment; live-test before relying on it — see the handoff.)*
- **Cloud STT settings UI** (`app/dialogs/advanced.py`) — the backend
  dropdown now shows human labels for both cloud options, and a dedicated
  **Google Cloud Speech-to-Text** section adds: a service-account JSON file
  picker; a "How do I get this file?" step-by-step help dialog with
  clickable links to the exact Google Cloud console pages; a non-blocking
  **Test connection** button (installs the Google libs on demand, then
  validates the JSON + auth); a **Batch-mode** toggle with a GCS bucket
  field; a **diarization** toggle; and a **live usage display**.
- **Free-tier usage tracking** — a local **monthly** minutes counter (it
  resets each calendar month) plus an honest estimated-cost line
  ("X / 60 free minutes this month; estimated $Y of the $300 credit"),
  clearly labelled a *local estimate* with a link to the real Google
  billing console (the true remaining credit is **not** readable from the
  key). New config keys `gcloud_stt_minutes_used` /
  `gcloud_stt_minutes_month` / `gcloud_stt_free_minutes_cap`.
- **One-click Web / LAN access** — a new **Web / LAN access** tab
  (`app/app.py` + `app/widgets/tabs.py`, backed by a `core/server`
  `ServerHandle`) with a single **Start/Stop** toggle, a port field (with a
  free-port fallback when the chosen port is busy), a **Share on local
  network** checkbox (loopback by default vs `0.0.0.0` with a plain-language
  firewall note), an optional **access password** (token), the reachable
  URL(s) including the LAN IP, an **Open in browser** button, non-blocking
  start/stop, and auto-stop on app exit. New config keys `server_share_lan`
  / `server_token` (`server_port` / `server_max_upload_mb` already existed
  from the Phase-1 `gui.py serve` work).
- **About dialog enriched** (`app/app.py` `_show_about`) — a **What's new**
  section plus plain-language descriptions of all the cloud options, the
  Web / LAN access, the per-task controls, multi-monitor tiling, and the
  update check / in-place upgrade, with clickable helpful links.

#### Phase 3 (added later in the same local batch)

- **Seek / scrub transport bar in the VLC transcript preview.** The
  built-in transcript player now has a draggable position bar with a
  live `MM:SS` time readout, ±5 s / ±10 s skip buttons, and keyboard
  control, so you can scrub to a moment instead of only play/pause. It
  degrades gracefully when VLC is absent (the transport bar simply isn't
  shown).
- **Web / LAN feature parity with the desktop app.** A browser job can now
  carry the same **per-job advanced options** as the desktop (VAD, word
  timestamps, diarization, clip range, etc.), applied via a per-job
  `.whisperproject.json` override; a new `GET /api/jobs` lists all jobs;
  **pause / resume** routes were added; outputs are taken from the
  engine's `task.output_paths`; and the page is now a small **3-view
  browser UI** (Submit / Jobs / Result with the transcript shown inline).
  Uploads are **streamed to disk** (no full-RAM buffering). HTTP hardening:
  the request body is drained on an early reject (no broken-pipe noise) and
  the access token is compared in **constant time**. *(Security boundary:
  the cloud / alternate backends are deliberately NOT per-job switchable
  over the web — a remote submitter can't redirect your audio to a cloud
  backend.)*
- **"SMTV transcription" docx output format** (registry key `smtv_docx`,
  UI label **"SMTV transcription"**). It fills the transcription team's
  bundled Word template (`core/writers/templates/smtv_template.docx`) — a
  4-column table (auto row number; `Time Code` as `HH:MM:SS.m`; `Foreign
  Language` = the transcript text; `English Translation` left empty for the
  human translator), with a title line
  `"<work title> -Transcription in <language> – Translation in English"`
  and the output filename matched to it. The table grows past the template's
  31 pre-formatted rows, and a `.docx` extension is forced.
- **Installer opt-out for Video Tiling.** `installer_embed.iss` adds a
  **"do NOT include Video Tiling"** task; selecting it drops a
  `{app}\no_tiling.flag` marker and the app then hides the Video Tiling tab
  (`core.hub.tiling_tab_enabled()`).

### Changed

- **The model now downloads to a writable location by default.** The
  first-run hub default moved from the install directory (under Program
  Files — "access is denied" for a non-admin user) to
  `%LOCALAPPDATA%\WhisperProject\Cache\models`. The model-download dialog
  surfaces a typed `ModelDestinationNotWritable` and offers a re-pick, the
  hub-folder picker probes writability when you click OK, and the default
  hub is aligned with `model_folder_for`'s empty-hub fallback
  (`HUB_SUBFOLDER_NAME = "models"`) so an existing `Cache\models` model is
  **reused, not re-downloaded** (~3 GB saved). Verified on this machine with
  a real `load_config()` probe.

#### Phase 3

- **Google Cloud STT defaults are now `chirp_2` / `us-central1`** (were
  `long` / `global`). This was **live-verified** against the owner's
  service-account JSON: the previous
  `long` / `global` pairing rejected language auto-detect, whereas `chirp_2`
  supports auto-detect and multilingual input. New config defaults
  `gcloud_stt_model = "chirp_2"` and `gcloud_stt_location = "us-central1"`
  in `config.py`.

### Fixed

- **GPU/CPU autodetect is hardened and self-healing.** A cheap cuDNN/cuBLAS
  runtime-load gate means CUDA is only chosen when it's actually usable, and
  a failed CUDA model load now falls back to **CPU int8** instead of
  crashing the worker (and instead of falsely prompting a ~3 GB
  re-download). The effective device is reported additively on the worker
  `ready` event and shown as a live GPU/CPU badge (Transcribe header + Queue
  status); a one-time "running on CPU (slower)" warning is gated to the
  GPU-detected-but-unusable / downgrade case (config key
  `cpu_warning_shown`).
- **Network / UNC drag-and-drop no longer silently drops the file.** A
  backslash-preserving, brace-aware splitter replaces `tk.splitlist`, which
  was collapsing the leading `\\` of a `\\server\share\file` drop.

#### Phase 3 (reported issues + a deep adversarial review)

- **Every Web / LAN job crashed** with
  `'_CancelledTask' object has no attribute 'paused'`. The server's task
  object now mirrors the engine's read contract (renamed `_ServerTask`),
  and the test fakes were hardened so the gap can't regress.
- **"View transcript" closed the whole app.** The root cause was libvlc
  `set_hwnd` on an *unrealized* Tk window — a native crash that bypassed
  `try`/`except` entirely. The HWND bind is now **deferred until the window
  is mapped**, with a graceful fallback; the viewer also now opens the
  actual transcript `.json` instead of popping a spurious file-picker.
- **"Re-detect hardware" froze the UI.** The probe ran on the Tk main
  thread (plus an unbounded cuDNN/cuBLAS `ctypes.CDLL` probe). It now runs
  **off-thread** behind a generation-token guard, with a **timeout-bounded**
  DLL probe.
- **The Queue per-task action bar was unusable** — the 500 ms `refresh()`
  rebuilt the tree and wiped the row selection on every tick. Selection is
  now **preserved across the rebuild**.
- **Off-thread Tk writes fixed.** The Video Tiling log callback and four
  Advanced-dialog worker handlers now marshal back through the main thread
  via a new `App.log_threadsafe`; the tiling status colour is now applied.
- **Smaller fixes** — a status-cell click defers via `after_idle`;
  `start_tiling` guards a bad grid spinbox; `pause_download` only pauses a
  *running* download; the theme + download-folder `save_config` calls are
  guarded; `minimise_to_tray` / `telemetry_opt_in` were added to
  `DEFAULT_CONFIG`; a multi-file enqueue gates the model **once**; the
  Advanced mouse-wheel binding is released on close; and the server handle
  is registered **before** `start()`.
- **Google Cloud STT timing + language correctness** (live-verified with
  the owner's service-account JSON). Language codes are mapped ISO → BCP-47
  (Google v2 rejects a bare `"en"`); word time offsets are **always**
  requested and the words are re-segmented into properly-timed phrases — a
  real run produced **5 correctly-timed subtitle segments** instead of one
  0–30 s blob.

### Docs

- **Evaluation: skip Google's Gemma 4 12B as a transcription backend.**
  `docs/evaluations/GEMMA4_EVALUATION_2026-06.md` recommends a SKIP — a 30 s
  audio cap, a torch/BF16/~24 GB-VRAM requirement, no word timestamps, and
  no WER win over the current stack — while sketching a possible
  future-adjunct path and a hardware gate.
- **New `docs/CLOUD_STT_GOOGLE.md`** (Phase 2) — service-account setup,
  the Standard-vs-Batch trade-off, the GCS-bucket requirement for batch,
  and the honest "the real $300-credit balance is not readable from the
  key" usage note. `docs/SERVER.md` updated for the one-click Web / LAN
  access toggle (alongside the existing `gui.py serve` CLI).

#### Phase 3

- `docs/CONFIG.md` and `docs/CLOUD_STT_GOOGLE.md` updated for the new
  `chirp_2` / `us-central1` Google Cloud STT defaults (was `long` /
  `global`) and the auto-detect / multilingual reason behind the change.
- `docs/SERVER.md` updated for the Web / LAN feature parity — per-job
  advanced options, the `GET /api/jobs` list, the pause / resume routes,
  the 3-view browser UI, and streamed uploads — plus the note that cloud /
  alternate backends are **not** per-job switchable over the web.

## [1.3.7] — 2026-05-29

Senior-architect deep audit (8 parallel read-only shards → fix batches).
pyright `app/ core/` 0/0/0 and the hermetic suite stay green; no shipped
Windows behaviour changed at spawn time. Highlights:

### Security

- **Subtitle burning no longer breaks/injects on punctuated titles.** The
  SRT path went straight into ffmpeg's `subtitles=` filter graph escaping
  only `\` and `:`, but `' , ; [ ]` are filtergraph metacharacters and a
  downloaded video's title (hence its `.srt` name) is attacker-influenced.
  Burning now happens from a temp copy with a graph-safe ASCII name; the
  Windows drive-colon escape is gated to Windows so a POSIX colon path
  isn't mangled.

### Fixed

- **Orphaned grandchild processes.** Killing a worker (or cancelling/
  exiting a download) left its ffmpeg/ffprobe/demucs grandchildren running
  on Windows (`TerminateProcess` doesn't cascade) — burning CPU/RAM,
  holding file handles, leaking GPU memory. New `core/_proc.py` kills the
  whole tree (`taskkill /T` / `os.killpg`); the worker + yt-dlp are spawned
  isolated for it.
- **Alternate backends ignored the Transcribe-tab time range** — a clipped
  request on whisper.cpp / Parakeet silently transcribed and wrote the
  whole file. They now slice `[start,end]` and offset onto the timeline.
- **Model-loading modal could hang forever** if the worker failed to load
  or died before "ready" (only Cancel escaped); it now closes on those
  events and no longer stacks a second modal.
- **Model re-download loop is bounded** (was `while True`) so a bad mirror
  or a captive-portal MD5 body can't re-download ~3 GB forever; the MD5
  manifest parser rejects non-hex lines.
- **On-demand optional installs** (PyTorch features) gained cancel + a
  timeout and stage-then-merge, so a stalled or failed pip can't hang the
  modal or leave a half-written package that crashes the worker later.
- **Format lookups no longer die for the session** when yt-dlp returns
  non-object JSON — the poll loop is self-healing.
- **Hallucination "suspect" flags now reach the JSON** so the transcript
  viewer's red-row review actually works.
- **Resource hygiene**: history DB closed on exit; `partials/` swept of
  orphaned slices + aged-out checkpoints (and cleared when crash-resume is
  declined); demucs vocal-cache bounded; the recorder streams to disk
  (no multi-hour-recording OOM); the yt-dlp pipe is reaped on error.
- **Smaller correctness fixes**: per-format writer isolation verified;
  VTT word `start=None` no longer aborts the file; history paths derived
  via `splitext`; per-folder override defaults no longer leak between
  files; the resume progress bar advances instead of pinning at 99%; LLM
  chapter generation runs under the liveness watchdog; whisper.cpp model
  download verifies length; Parakeet surfaces a clean ffmpeg-decode error;
  download/format/worker loops short-circuit during shutdown.
- The About dialog stopped advertising two not-yet-wired capabilities
  (cross-file voiceprint matching, semantic/FTS5 search).

### Cross-platform

- `core.tiling` added to both PyInstaller specs' hidden-import lists.
- macOS `install.command` materialises ffmpeg/ffprobe into `bin/` (so the
  double-clicked `.app` finds them regardless of its minimal PATH) and the
  static-ffmpeg unzip is non-fatal under `set -e`. *(macOS unverified on
  real hardware.)*

## [1.3.6] — 2026-05-26

A new Video Tiling tab + the groundwork for running on Linux and macOS.

### Added

- **Video Tiling tab.** Paste a live-stream URL (YouTube, X/Twitter, and
  the other yt-dlp sites), pick a grid size, and the stream fills the
  screen as an N×N "video wall" (ports the maintainer's `video-tiler`).
  Uses **ffplay**, which isn't bundled — the tab shows how to add it when
  it's missing, so the base download stays the same size.
- **Linux support** (`platform/linux/`): a one-step `install.sh` (venv +
  deps + `yt-dlp` + a static `ffmpeg` fallback + desktop launcher), a
  headless `whisper-transcribe` CLI for servers, plus `update.sh` /
  `uninstall.sh` and a README.
- **macOS groundwork** (`platform/macos/`): a double-click `install.command`,
  a Gatekeeper `unblock.command` (`xattr -dr com.apple.quarantine`), and a
  README covering the unsigned-app install flow. Marked needs-real-Mac
  validation.

### Changed

- **Cross-platform core hardening.** `yt-dlp`/`ffmpeg`/`ffprobe` resolve to
  the right per-OS binary (bundled or on PATH); `--ffmpeg-location` is only
  passed when a bundled ffmpeg exists; VLC discovery now covers macOS
  (`VLC.app`) and Linux library dirs as well as the Windows registry. The
  Windows build is unchanged.
- Added a `.gitattributes` pinning LF on shell/`.command` scripts so they
  run on Linux/macOS regardless of git's autocrlf.

## [1.3.5] — 2026-05-25

Real pause/resume/cancel + a post-slim hardening pass (five parallel
code-audit shards over everything that changed in v1.3.x).

### Added

- **Pause / Resume now actually work, and Cancel keeps your progress.**
  Previously Pause did nothing to a running job and Cancel killed the
  worker and threw away the partial transcript. The worker now reads
  pause/resume/cancel on a side channel while it's transcribing: Pause
  halts at the next segment, Resume continues, and Cancel saves a
  resumable checkpoint (so "Re-run" picks up where you stopped) instead
  of discarding it.

### Fixed

- **A docx-only (or pdf-only) result no longer looks lost.** The "Last
  result" card and the history record now list the files the worker
  actually wrote — including docx/pdf and de-duped `name (1).srt` names —
  instead of guessing from settings (which only knew srt/json/txt/…).
- **You can cancel an auto-transcribe from the Download row.** Right-
  clicking a row that shows "transcribing" now offers Cancel (the menu
  was empty before).
- **A sub-second download end time no longer corrupts the range** (e.g.
  `1:30.999` no longer became a bogus `0:01:301`).
- **One broken output writer no longer discards the others.** A failing
  format is logged and skipped; the formats that wrote fine are kept
  (only an all-formats failure raises).
- Pausing a task that hadn't started yet no longer strands it.
- Progress bars tolerate a non-finite percentage without erroring.

### Changed

- On-demand optional-feature installs are serialized (two requests can't
  race into a half-written package) and their progress log is delivered
  to the UI thread safely.
- The slim build also drops the orphaned `llvmlite` native-lib folder
  (~30–40 MB) and the build's sanity check imports the docx/pdf writers,
  so a future prune mistake fails the build instead of silently breaking
  docx again.

## [1.3.4] — 2026-05-25

Much smaller install + a docx fix.

### Changed

- **Install size cut from ~1.5 GB to ~800 MB.** PyTorch and the heavy ML
  libraries it drags in (sympy/networkx/numba/llvmlite) are no longer
  bundled — they were only needed by two optional features.

### Added

- **On-demand optional features.** Word-timestamp alignment (stable-ts)
  and the openai-whisper backend now download their support (~700 MB,
  PyTorch) on first use into a user folder, the same way the Whisper model
  is fetched. Declining just runs without that feature. Core transcription,
  subtitles, diarization, and downloads are unaffected and need no
  download.

### Fixed

- **DOCX / PDF output now actually written.** The long-lived worker read
  its config once at startup, so a docx/pdf format ticked afterward never
  reached it; the selected output formats are now sent with each job.

## [1.3.3] — 2026-05-25

Features + a follow-up bug-hunt (the time-slice and download flows).

### Added

- **Position slider on the Download tab.** After a video is probed, drag
  the Start / End sliders (0 .. video length) to fill the time-range
  fields instead of typing.
- **Portable ZIP** is now a first-class download — the full embeddable-
  Python environment + a `Run Whisper Project.bat` launcher. No install;
  update by swapping `app\` / `core\` files.

### Changed

- **License changed from MIT to BSD-3-Clause.** Added a root `LICENSE`
  and a `THIRD_PARTY_NOTICES.md` summarizing the bundled components'
  licenses (FFmpeg, yt-dlp, the Python runtime + packages).

### Fixed

- **A clipped transcription that was cancelled then resumed** no longer
  transcribes past the end of the clip (a clipped run now neither resumes
  nor writes a whole-file checkpoint).
- **A reversed time range (end before start)** no longer makes the
  download fetch nothing — it degrades to "from start to the end".
- The Download-tab sliders no longer wipe a manually-typed range when the
  format probe finishes, and ignore stray drags before a video is probed.
- The login/cookie download hint no longer fires on unrelated errors
  (it matched substrings like "stor**age**"/"**page**").

## [1.3.2] — 2026-05-25

Security + features release. A dedicated security/concurrency/resource
bug-hunt (four more parallel audit shards) plus the most-requested
feature.

### Added

- **Transcribe a time-slice of a file.** The Transcribe tab now has
  Start / End fields (default 0:00:00 = whole file), so you can transcribe
  e.g. 5 minutes out of a 10-hour recording. Segment timestamps stay on
  the original timeline.

### Security

- **yt-dlp option injection closed.** A pasted "URL" beginning with "-"
  was handed to yt-dlp without a "--" end-of-options separator, so it
  could be parsed as a flag (e.g. `--exec` → command execution) — and the
  format probe fires on paste. All three yt-dlp argv builders now insert
  "--" before the URL.
- **Zip-slip guard** on model-archive extraction: members that would
  resolve outside the cache dir are now rejected.

### Fixed

- **Failed downloads now say WHY.** Instead of "yt-dlp exited with code
  N", the queue shows yt-dlp's real error line; for login-walled sites
  (Facebook / Instagram) it adds a hint to enable "Cookies from browser"
  in Advanced settings.
- **Progress percentage stays visible during start-up.** The "working"
  animation kept the number (it had briefly hidden it behind a moving
  bar), so you can always see how far along a transcription is.
- **Corrupt-but-readable media** (ffprobe reports "N/A" duration) no
  longer aborts the run with an opaque error — it transcribes anyway.
- **Model-path fix when a hub folder is selected** (contributed).

## [1.3.1] — 2026-05-25

Reliability release — a focused bug-hunt (tracing each UI action through
the code, four parallel audits) on top of v1.3.0.

### Fixed

- **Auto-transcribe after a download silently produced no transcript when
  the title had a non-ASCII character** (apostrophe, accent, emoji, CJK).
  yt-dlp wrote stdout in the Windows code page, so the saved path came back
  mojibake'd and didn't match the real file. Now forces UTF-8 output, plus
  a **self-healing fallback** that finds the actual downloaded file when
  the parsed path is wrong — so even an unheard-of character can't lose the
  transcript.
- **Picking a non-English language crashed transcription with no output.**
  A region tag ("en-US") or a multi-value picker code ("zh-Hans,zh-CN",
  "pt,pt-BR,pt-PT", "he,iw") was passed straight to faster-whisper, which
  rejected it. Language hints are now normalized to a base ISO code on
  every transcription path.
- **The viewer said "VLC isn't installed" when VLC was installed.** It now
  locates VLC via the registry / Program Files, and the message spells out
  that a 64-bit VLC is required (a 32-bit VLC can't load into the 64-bit
  app).
- **Cancelling a download that had moved on to transcribing** left the
  transcription running and silently undid the cancel; **re-running a
  time-range download** fetched the full video. Both fixed.
- **Optional features no longer crash the app on probe.** Speaker
  diarization / alternate engines that fail to load a native library now
  just show as unavailable instead of taking the app down.
- **The Transcribe tab rejects a missing / mistyped file** with a clear
  message instead of failing deep in the worker.

### Added

- **An animated "working" bar** in the queue while a task is starting up
  (model load) so it's clear something is happening before the percentage
  begins.
- **The download time-range Start / End fields are pre-filled with
  0:00:00** so they're easier to edit (leaving both = the full video).

## [1.3.0] — 2026-05-25

UX + reliability release on top of v1.2.0 — bug fixes and visibility
improvements found while running the app on real downloads.

### Added

- **Graphical progress bars in the queue rows.** The transcription and
  download queues draw a block bar (e.g. `████░░░░░░ 42%`) next to the
  number, so progress is visible at a glance instead of just a figure.
- **The version is visible.** The window title shows `Whisper Project
  v1.3.0`, and the Standard installer's Start-menu / desktop shortcut is
  named with the version — so you can tell which build is installed.
- **The Download tab shows transcription progress.** After an
  auto-transcribe-from-download, the download row reads "transcribing"
  and mirrors the live transcription progress, then flips to "finished",
  so a slow transcription no longer looks like a stalled, idle 100%.

### Changed

- **The "Last result" card no longer dominates the Transcribe tab** — it
  sizes to its content instead of expanding to fill the lower half.
- **The transcription language resets to "Auto" on every launch** and is
  no longer persisted; every other transcribe preference is still saved.

### Fixed

- **Auto-transcribe after a video+audio download.** yt-dlp merges the two
  streams into one file and deletes the per-stream fragments; the
  saved-path parser had been matching the now-deleted audio fragment, so
  auto-transcribe hit "No such file or directory" and silently did
  nothing. It now resolves the merged output (and the
  already-downloaded / extracted-audio cases too). Seen on Facebook reels
  and YouTube Shorts.

## [1.2.0] — 2026-05-25

UX + accessibility release on top of v1.1.0 — mostly things the operator
hit while using the app on a Persian keyboard.

### Added

- **Copy / paste works everywhere now** — a right-click menu (Copy / Cut
  / Paste / Select all) on every text field, plus a copyable log console
  (right-click → Copy / Copy all / Clear). Mouse-driven, so it never
  depends on the keyboard layout.
- **Bulk queue actions.** Select multiple rows in the transcription or
  download queue and Cancel / Re-run / Resume / Remove them all at once.
- **Scrollable queues.** Both queue lists get an auto-hiding vertical
  scrollbar that appears only when the list outgrows the visible area.
- **Model visibility + on-demand install.** The Advanced model picker
  marks each model "downloaded" / "needs download", and a "Download now"
  button installs the selected model without starting a transcription.
- **Open file from the Download tab** — a finished download's context
  menu can open the media file directly (not just its folder).

### Fixed

- **Clipboard shortcuts under a non-Latin keyboard layout.** Ctrl+C / V /
  X / A keyed off the Latin keysym, so copy/paste/cut/select-all were
  dead while a Persian (or Arabic, Russian, …) layout was active. They
  now dispatch by physical keycode.
- **Transcript outputs no longer overwrite a previous run** — a re-run
  writes `name (1).srt` / `name (1).json` (a shared index) instead of
  clobbering the earlier files.
- **The About dialog** shows the live app version (it was hard-coded to
  an old number) and opens in one click (it used to be a menu whose only
  item was another "About").

## [1.1.0] — 2026-05-25

Maintenance release — bug fixes plus one opt-in feature. Restores audio
in video downloads, removes several UI freezes and nags, makes the
model-hub and download-folder choices stick, fails a truncated SMTV
download instead of shipping a corrupt file, and adds browser-cookie
support so login-walled sites (Facebook / Instagram / TikTok stories,
age-gated YouTube Shorts) can download.

### Added

- **Download from login-walled / age-gated sites via browser cookies.**
  A new "Cookies from browser" picker in Advanced → Downloads passes
  yt-dlp's `--cookies-from-browser`, so Facebook / Instagram / TikTok
  stories and age-restricted YouTube Shorts can download using your
  logged-in browser session. Off by default; pick your browser
  (Chrome / Edge / Firefox / …) to enable.

### Fixed

- **Video downloads were silent (no audio).** yt-dlp's format selector
  was emitted as `video…/bestvideo+audio…/best` without grouping, so
  yt-dlp's `/` precedence selected a video-only stream and the merged
  file had no audio. Each stream group is now parenthesized:
  `(video…)+(audio…)/best`.
- **Model-load froze the UI on several paths.** Three main-thread
  enqueue paths — auto-transcribe-after-download, crash-resume
  ("Resume interrupted transcriptions?" → Yes), and the watched
  folder — waited synchronously for the Whisper model to load (up to
  the 120 s timeout), freezing the whole app. They now share one
  non-blocking helper that spawns the worker and polls for readiness
  with `after()`, so the UI stays responsive and the task is queued
  once the model is ready.
- **The model hub folder you picked was ignored.** A `model_path`
  derived from the *default* hub during startup was being written to
  `config.json`, then treated on the next launch as an explicit
  per-model override that outranked your chosen `hub_folder` — so the
  model always loaded from `<app>/hub` and `model_path` looked like it
  "reset" every launch. Auto-derived model paths are no longer
  persisted; a genuinely custom path is still kept.
- **The crash-resume prompt reappeared on every launch.** Declining
  "Resume interrupted transcriptions?" left the rows flagged
  `interrupted`, so the same prompt returned next time. Declining now
  clears the flag on the offered rows; genuine future crashes still
  prompt.
- **A download folder on a removable / network drive was forgotten.**
  If the drive was detached at launch, the folder was cleared *and the
  cleared value was written back to config*, so the choice was lost
  permanently. The cleared value is no longer persisted while the drive
  is merely unmounted — the folder returns when the drive does. (Same
  class as the `model_path` fix above.)
- **A truncated Supreme Master TV download was treated as success.** If
  the CDN dropped the connection mid-transfer, the partial file was
  renamed to the final name and auto-transcribed — a clean-looking but
  corrupt result. The download now fails and reports an error when fewer
  than the advertised (Content-Length) bytes arrive.

### Changed

- The **Advanced settings** dialog is now resizable and scrolls, so it
  fits on smaller screens.
- The **About** dialog no longer shows the source-repository URL.

## [1.0.3] — 2026-05-23

UX + memory release. Adds the optional time-range download
collaborators asked for and changes the model-load policy so
idle launches don't pay for ~2 GB of RAM the user may never use.

### Added

- **Time-range video download.** New optional Start / End fields
  on the Download tab. Fill either (or both) in `H:MM:SS`,
  `MM:SS`, or seconds, and yt-dlp's `--download-sections`
  fetches only that slice. The Queue row label shows a
  `trim 0:51 → 1:25` badge so it's obvious which jobs are
  partial. The transcribe step naturally runs proportionally
  faster — most of the savings come from the smaller audio,
  not the smaller download. Supreme Master TV URLs are not
  sliced in this release (the SMTV scraper has no slicing path);
  one clear WARN log line + a known-limitation note in
  `docs/integrations/smtv-brief.md`.
- **Lazy Whisper-model load.** The app no longer preloads the
  3 GB Whisper model on launch. Idle RAM drops by ~2 GB.
  The first transcribe of a session shows a modal "Loading
  Whisper model…" dialog with an indeterminate progressbar; the
  worker spawns and loads, the dialog dismisses, the transcribe
  proceeds. Subsequent transcribes reuse the alive worker — only
  the first one pays the load. Crash-resume and watched-folder
  enqueues go through the same gate without showing a modal
  (headless mode, 120 s timeout).

### Changed

- `App._on_start` no longer calls `start_standby()`. The method
  is kept as a deprecated proxy for backwards compatibility with
  any test that still calls it.

### Documentation

- `docs/integrations/smtv-brief.md` — added the time-range
  limitation note.

### Shipped artefacts

Same shape as v1.0.2: Portable + Setup-Standard only. The
Compact pipeline still exists in the repo + still builds, but no
Compact EXE is published.

## [1.0.2] — 2026-05-23

Reliability + UX release. Closes the long-uptime + multi-hour-file
gaps the 2026-05-23 stability audit catalogued, and lands the
resume-from-cancellation feature.

### Added

- **Resume from cancellation / pause / crash.** The transcribe
  loop now writes a periodic checkpoint
  (`%LOCALAPPDATA%/WhisperProject/partials/<sha1>.json`) every 10
  segments or 20 s. Cancelling, pausing or crashing keeps the
  checkpoint on disk; a new Resume command on cancelled rows
  slices the source audio from the last segment boundary,
  transcribes only the remainder, merges with the already-done
  segments, and runs the post-pipeline (diarisation, chapters,
  alignment, voiceprint) on the full merged result. faster-whisper
  backend only; whisper.cpp and Parakeet fall back to a fresh
  re-run with a clear log line. Validates source mtime/size and a
  config fingerprint before resuming, so a changed file or model
  silently starts fresh instead of producing garbage.
- **Pause command in the queue right-click menu** for running
  tasks. The engine already supported `task.paused`; the menu
  entry was the only missing UI surface.
- **About dialog feature inventory.** The previous one-line
  `messagebox.showinfo` is replaced by a scrollable Toplevel
  listing every capability of the app grouped into nine
  sections — Transcription engine, Output formats,
  Post-processing, Video download, Transcript viewer, Workflow
  + system integration, Search + statistics, Keyboard shortcuts,
  Privacy. Many capabilities ship enabled by default but live
  behind the Advanced dialog with no main-UI surface; this
  dialog is the canonical "what does this app actually do"
  reference.

### Fixed

- **3 GB re-download on the launch after the first-run hub picker.**
  (Originally fixed in v1.0.1; carried forward.) The hub-folder
  dialog was asynchronous and the worker spawned with an empty
  `hub_folder`, downloading the model to a path the next launch
  wouldn't resolve to. Aligned the empty-hub fallback in
  `_apply_runtime_fallbacks` with the dialog's default and
  deferred `start_standby()` until the dialog answers.
- **Worker liveness watchdog kills diarisation on long files.**
  `_run_post_pipeline` now plumbs `progress_cb` into
  `diarization.diarize`, mapping sherpa-onnx's 0..1 tick into the
  90..99 percent slot. Bumped `LIVENESS_TIMEOUT_S` from 30 s to
  120 s as defence in depth.
- **Same watchdog pattern in four more silent C calls.** New
  `core/_liveness_tick.py` context manager wraps
  `stable_ts.model.align(...)`, the Demucs CLI subprocess, the
  Parakeet `decode_stream(...)` call, and the whisper.cpp
  `model.transcribe(...)` call. Without this, every alt-backend
  transcription and every alignment / Demucs run on slow CPU was
  one watchdog tick away from a mid-flight kill.
- **`.whisperproject.json` overrides leak across files.**
  `_apply_runtime_overrides` mutated the module-level config in
  place. The long-lived worker carried a folder-A override into
  folder-B's files. Now wrapped in `_runtime_overrides_scope`
  which snapshots and restores touched keys around each file —
  with eight regression tests.
- **`tk.after(0, ...)` from background threads.** On Python 3.14
  this raises `RuntimeError`; on earlier 3.x it's undefined and
  the existing `try/except: pass` blocks silently dropped the
  callback. Added an `App._main_thread_calls` queue + drainer +
  `post_to_main(fn)` helper; rerouted burn-subs, hardware-wizard
  benchmark, and tray-click callbacks through it.
- **Demucs temp-directory leak.** `tempfile.mkdtemp(...)` in
  `core/separator.py` was never removed on the success path,
  leaking 30–50 MB per separation. Cleanup now lives in a
  `finally:`.

### Documentation

- `docs/STABILITY_AUDIT_2026-05-23.md` — 26-item audit driven by
  the diarisation-watchdog bug. 7 P0 / 9 P1 / 10 P2 with
  file:line + symptom + suggested fix. P0s plus the
  highest-leverage P1 are closed in this release; the rest are
  the next-session punch list.

### Shipped artefacts

This release skips the Setup-Compact installer (Portable +
Setup-Standard cover the same audiences). Two EXEs uploaded to
the v1.0.2 release page.

## [1.0.1] — 2026-05-23

First stable release. Marks the project as feature-complete + freeze-ready
after an audit-driven hardening sweep (~62 of 72 audit items closed, the
rest deferred with documented rationale), plus a pre-ship fix for a
fresh-install model re-download race caught during verification.

### Fixed

- **3 GB re-download on the launch after the first-run hub picker.**
  On a fresh install the first-run hub-folder dialog was asynchronous:
  it opened, returned the default path immediately, and `_on_start`
  fired `start_standby()` while the user was still reading the
  dialog. The worker then computed `model_path` from an empty
  `hub_folder` and downloaded the model under
  `%LOCALAPPDATA%\WhisperProject\Cache\models\`. When the user
  accepted the dialog default (`<app_dir>\hub`), the next launch
  resolved `model_path` to a directory the model was never
  extracted into, triggered a `startup_error`, and re-downloaded
  the full 3 GB archive. Fixed by:
    * Aligning the empty-hub fallback in
      `_apply_runtime_fallbacks` with the dialog's default
      (`default_hub_folder()`), so accepting the default is a no-op
      for the model location.
    * Deferring `start_standby()` in `App._on_start` until the hub
      dialog's `on_done` callback fires, so the worker starts with
      the user's actual choice even when they pick a custom folder.
  Regression test added in `tests/core/test_hub.py`.

### Added — v0.8 Phase 1 (Shards A + B)

- **Hallucination detector** — flags suspect Whisper segments via
  three signals: Bag-of-Hallucinations wordlist, 1/2/3-gram
  repetition, and (optional) VAD-disagreement. Annotates JSON with
  `seg["suspect"] = True` + `suspect_reason`. Transcript viewer
  highlights flagged rows in red. Toggle:
  `hallucination_detect_enabled`.
- **Multi-model picker** — Large v3 (default), Large v3 Turbo, and
  Distil Large v3.5 selectable from the Advanced dialog. Slug-keyed
  registry; existing config keeps working unchanged.
- **Hardware autodetect wizard** — probes CUDA → QNN/NPU → OpenVINO
  → DirectML → CPU int8, persists the choice in `hardware.json`,
  re-validates at every model load.

### Added — v0.8 Phase 2 (live + AI layer foundations)

- `core/recorder.py` — mic + WASAPI loopback recorder.
- `core/llm.py` — local LLM panel (Qwen2.5-1.5B, download-on-first-use).
- `core/separator.py` — Demucs vocal-separation pre-process.

### Added — v0.8 Phase 3 (data + recognition expansion)

- `core/backends/parakeet.py` — sherpa-onnx Parakeet TDT v3 backend.
- `core/search.py` — semantic + FTS5 search across saved transcripts.
- `core/chapters.py` — auto-chapter markers via long-silence heuristic.
- `core/voiceprint.py` — cross-file speaker fingerprint DB.

### Added — Model Hub Folder feature

- First-run dialog asks where to store Whisper model files; choice
  is persisted to `config.json` under `hub_folder`. Default
  suggestion: `<app>/hub`. Inno Setup uninstaller asks whether to
  delete out-of-tree hub folders.

### Hardened — audit-driven (R-series)

- WAL journal mode + integrity check on `history.db` (crash-safe).
- Worker IPC: per-worker UUID session token + 5 s heartbeat + 30 s
  liveness watchdog. stdin writes moved off Tk thread. History row
  inserted BEFORE dispatch.
- Structured 4-step worker shutdown (stdin → wait → terminate → kill).
- INFO logs at every device / backend / model decision point.
- `--safe-mode` CLI flag: backs up `config.json` aside, fires fresh
  first-run dialog.
- `safe_thread` helper: every daemon thread now logs uncaught
  exceptions with full stack trace.

### Tests

535 unit + integration tests (+260 from 0.7.x baseline of 275).
10/10 real-file end-to-end against the SMTV reference clip. 7/7
smoke + end-to-end against the real Whisper model. pyright `app/
core/` 0 errors, 0 warnings, 0 informations.

### Documentation

- `docs/SENIOR_REVIEW_2026-05-21.md` — engineering audit
- `docs/EXECUTION_ROADMAP.md` — derived patch plan (35+ items)
- `docs/FINAL_FREEZE_AUDIT_2026-05-21.md` — pre-release sign-off
- `docs/RELEASE_PROCESS.md` — the ship sequence
- `docs/README.md` — navigation index for `docs/`
- `docs/roadmap/` — future-release research (v0.9 + beyond)

## [0.7.1] — 2026-05-20

Version bump packaging the Session-14 hands-off polish push, listed
in detail below under the original 0.7.0 history. Same source as the
final 0.7.0 build; rebranded so the three installer EXEs reflect the
new feature surface (backends, viewer enhancements, tray, …).

## [0.7.0] — 2026-05-20

### Added — Session 14 (hands-off polish from `HANDOFF_NEXT_SESSION.md`)

- **Filename templating** — `output_filename_template` config key is now honoured by every writer. Tokens `{base}`, `{ext}`, `{lang}`, `{date}`, `{speaker_count}` resolve at write time. Templates may include sibling subdirectories (`transcripts/{base}.{ext}`) — those folders are created on the fly. Malformed templates fall back to the legacy `{base}.{ext}` layout so a corrupt config never blocks a write.
- **Pluggable Whisper backends** — `core/backends/` houses an ABC plus two implementations. `faster_whisper` (default) preserves the CTranslate2 path with module-level `MODEL`/`PIPELINE` globals; `whisper_cpp` drives pywhispercpp on quantised ggml models (~1.1 GB for large-v3-q5_0). The Advanced dialog grows a backend picker and a "Download whisper.cpp model..." button.
- **Word-level alignment refinement** — `core/alignment.py` post-processes Whisper segments through stable-ts when `config["alignment"] == "stable_ts"`. Loads stable-ts's `tiny` Whisper model for the DTW alignment pass so word boundaries lock to ±50 ms.
- **Viewer enhancements (find/replace, speaker rename, fillers, confidence colours, karaoke)** — `Ctrl+F` opens a Find-and-Replace dialog with case-insensitive default + match-case toggle. Right-click on a segment with a speaker label → "Rename ... (everywhere)..." rewrites every same-labelled segment. Word-confidence colour coding (green ≥ 0.85, amber ≥ 0.6, red below) when segments carry `words` with probabilities. "Remove fillers" button strips `uh`/`um`/`er`/… with a whole-word regex. Karaoke wraps the active word in `[brackets]` in the side panel as VLC plays. `Ctrl+S` saves all edits atomically via `core.writers.json_writer`.
- **System tray + minimise-to-tray + native toast** — `app/widgets/tray.py` wraps pystray + Pillow on a daemon thread. Right-click menu: Show / Hide / Exit. Icon flips between a hollow blue ring (idle) and a filled red dot (active job). `config["minimise_to_tray"]` (opt-in) redirects `WM_DELETE_WINDOW` to hide-window. Completed transcriptions trigger `TrayController.notify(...)` so the user sees a native toast even when minimised.
- **High-DPI scaling** — `App._apply_hidpi_scaling()` reads `winfo_fpixels('1i')` at startup and computes Tk's scaling factor so fonts and paddings don't shrink to a 1 cm icon on 125 / 150 % Windows displays.
- **Anonymous opt-in telemetry** — `app/observability.py` is now gated on `config["telemetry_opt_in"]` (Advanced dialog checkbox). Sentry crash reporting requires that *and* `$SENTRY_DSN`; launch ping requires that *and* `$WHISPER_TELEMETRY_URL`. The ping carries `{os, version, python, anonymised_id}` only — `anonymised_id` is a SHA-256 of a one-shot UUID4 stored under `user_cache_dir()/telemetry_id`.
- **Auto-resume after crash** — `App._maybe_offer_crash_resume` runs on launch: if `history.db` flagged rows interrupted on the *previous* run and the source files still exist, prompts to re-enqueue them.
- **Per-folder `.whisperproject.json` overrides** — `core.config.merge_project_overrides` walks up from each transcribed file and overlays the closest `.whisperproject.json` on top of the global config. Dict-valued keys (`model`, etc.) deep-merge one level. Bad JSON / non-object roots are silently ignored.
- **Watched-folder UI wiring** — the existing `core.watcher.FolderWatcher` class is now wired through the Advanced dialog. New media files dropped into the configured folder are stability-checked (size stable for 1.2 s) then auto-enqueued via a Tk-safe `after()` hop. Stops/restarts cleanly when the user picks a new folder.
- **Windows Explorer "Transcribe with Whisper Project"** — both `installer.iss` and `installer_embed.iss` ship an optional shell-extension task (`shellext`) that writes the appropriate registry entries under `HKCR\*\shell\WhisperProjectTranscribe`. Hits the existing v0.7.0 CLI mode (`gui.py transcribe "%1"`).

### Added — Session 13 (gap-closing push)

- **Speaker diarization** via `sherpa-onnx` (no HuggingFace token). Toggle on the Transcribe tab. SRT / JSON / MD / DOCX writers all carry the speaker label. ONNX models live in `bin/diarization/` and ship with each installer.
- **In-app transcript viewer** (`Help → Open transcript viewer…`, plus "View transcript" button on the Last Result card). Segment table with type-as-you-search filter, double-click to seek, embedded `python-vlc` playback when libvlc is installed (falls back gracefully).
- **DOCX export** via `python-docx`. New binary-write path in `_write_outputs` with atomic `.part → os.replace` semantics preserved.
- **Markdown export** — stdlib only. Heading + per-segment timestamps + optional `_Speaker N:_` italics.
- **Drag-and-drop** (one or many files, or a URL) onto the window. Powered by `tkinterdnd2`; the App stays usable when the dep is missing.
- **Recent files submenu** populated from `history.db` (last 10 unique files). `File → Recent files`.
- **Window geometry persistence** — saves on exit, restores on next launch.
- **Multi-file Browse…** — selecting several files in the dialog enqueues them all.
- **Keyboard shortcuts** — `Ctrl+O` Browse, `Ctrl+Enter` Transcribe, `Esc` Cancel running, `Ctrl+Q` Exit.
- **GitHub Actions CI** (`.github/workflows/ci.yml`). Pyright + the unit suite on every push and PR. Matrix: Windows + Ubuntu, Python 3.11 + 3.12. Ubuntu wraps the pytest invocation in `xvfb-run`.

### Added

- **Session 12** — Three independent installation methods, all shipped from a single branch (`release/v0.7.0-installer-3-options`) on a single tag (`v0.7.0`):
  - **Method A — Portable** (`WhisperProject-v0.7.0-Portable.exe`, ~190 MB). PyInstaller `--onefile` build via `whisper_project_onefile.spec`. One file, no install, unpacks to `%TEMP%\_MEI*` per launch.
  - **Method B — Setup-Compact** (`WhisperProject-v0.7.0-Setup-Compact.exe`, ~137 MB). PyInstaller onedir from `whisper_project_onedir.spec` wrapped in `installer.iss` (Inno Setup 6, LZMA2 ultra). Real installer with Start Menu / desktop / Add-Remove-Programs entries.
  - **Method C — Setup-Standard** (`WhisperProject-v0.7.0-Setup-Standard.exe`, ~153 MB). Embeds a full `cpython-3.11.15+20260510-x86_64-pc-windows-msvc-install_only` distribution from [python-build-standalone](https://github.com/astral-sh/python-build-standalone), pip-installs `requirements.txt` into the bundle, copies the source tree, and wraps it via `installer_embed.iss`. Shortcuts launch `pythonw.exe gui.py`; the source is browsable on disk after install.
  - `build_embed_installer.bat` orchestrates the Method C tree.
  - All three pass `tests/smoke/test_exe_real_e2e.py::test_exe_worker_transcribes_real_video` on a clean install location with a real video, confirmed via the dual-launcher conftest fixture (`WHISPER_SMOKE_GUI` env var selects the embeddable-Python flavour).
- **Session 11** — Supreme Master TV download integration. New module `core/integrations/smtv.py` (stdlib only) scrapes any `/{lang}1/v/<id>.html` episode page for video qualities (1080p/720p/396p), the MP3 audio file, the article-text transcript, and the sibling-parts playlist; the Download tab automatically routes SMTV URLs through this module instead of yt-dlp. Sub-features:
  - **Series download.** When a multi-part episode is pasted, a "Download all parts of this series (SMTV)" checkbox appears (default ON) and enqueues one task per sibling part.
  - **MP3 audio mode.** SMTV serves real MP3 files directly; the Audio mode dropdown shows `MP3 (audio only)` and the download path skips ffmpeg entirely.
  - **Transcript persistence.** The page's article-text body is saved next to the media as `<base>.txt` (UTF-8). Auto-transcribe-after-download still runs unchanged on top, so users get two transcript surfaces — the site's editorial transcript and whisper's SRT/JSON.
  - 23 unit tests under `tests/integrations/test_smtv.py` against three HTML fixtures; 2 live-network smoke tests under `tests/smoke/test_smtv_smoke.py` (skipped offline). `docs/integrations/smtv-research.md`, `smtv-brief.md`, `smtv-acceptance.md` document the URL contract and SMTV-T1..T8 verification tokens.
- **Session 8** — `tests/smoke/` integration suite for the compiled exe. Three pytest files (`test_exe_real_e2e.py`, `test_app_headless.py`, plus a `conftest.py` with skip-guards for missing model / video / exe) and a `README.md` explaining why these tests have to live alongside the unit suite — packaging bugs are invisible from source-side. `test_exe_real_e2e.py` spawns `WhisperProject.exe --worker`, sends the actual JSON `transcribe` command, and asserts SRT + JSON land on disk; `test_app_headless.py` drives the Tk App in a withdrawn window through every service. Regression guards `test_exe_bundles_silero_vad_asset` and `test_exe_bundles_ffmpeg` lock in the Session 8 packaging fix.
- **Session 8** — `docs/SESSION_8_PACKAGING_FIX.md` documenting the silero_vad_v6.onnx packaging bug and why source-side tests didn't catch it.
- **Session 7** — `docs/architecture-diagrams.md` (Mermaid simple overview + SVG embed + pointer to prose ARCHITECTURE.md). Hyphenated filename to avoid a case-insensitive Windows clash with the existing `ARCHITECTURE.md`. The Mermaid view uses the same color palette as the SVG so the two diagrams feel related at a glance. README now links to it as the first "Project documentation" entry.
- **Session 7** — `docs/NEXT_SESSION_HANDOFF.md` — two-minute briefing for any future architect. Includes the current commit/branch/tag inventory, a 60-second orientation command list, the candidate phases ranked by impact-per-effort, the hard rules (single branch, no tokens, `bin/` ignored, Tk single-threaded, JSON protocol sacred), what's explicitly out of scope (Persian/Arabic, cloud LLMs, mobile, streaming), where to look when something feels weird, files not to touch, and a one-paragraph user prompt to start the next session.

### Fixed

- **Session 9** — `App.destroy()` now cancels every pending `tk.after()` callback before tearing down the Tcl interpreter. Previously, the service poll loops (`TranscriptionService.poll`, `FormatService.poll`, `DownloadService.poll`) reschedule themselves every tick; on shutdown those pending callbacks fired into a destroyed interpreter and spammed the log with hundreds of `invalid command name "<id>poll"` errors. Now the override iterates `tk.call("after", "info")` and calls `after_cancel` on each id before delegating to `super().destroy()`.
- **Session 9** — `core/transcriber.py:load_model_async` no longer swallows exceptions. The background-thread wrapper had a bare `except Exception: pass` that hid a real model-corruption case in the field for a whole session. Now it logs via `logger.exception` and forwards the message to `status_cb` if provided.
- **Session 9** — `core/transcriber.py:get_duration` now passes `timeout=60` and (on Windows) `creationflags=subprocess.CREATE_NO_WINDOW` to the bundled ffprobe call. A wedged ffprobe used to hang transcription indefinitely with no cancel, and the windowed exe popped a black console window for every probed file.
- **Session 9** — `messagebox.showinfo("About", ...)` now passes `parent=self` so the dialog centers on the app window instead of the screen.
- **Session 8** — `whisper_project.spec` now collects `faster_whisper`'s data files via `collect_data_files('faster_whisper')`. Without this, the compiled exe crashed the moment a user clicked **Transcribe** with VAD enabled (the default) because `silero_vad_v6.onnx` was absent from the bundle. The bug was invisible from `python gui.py` because source-side code resolves the asset from `site-packages/faster_whisper/assets/`. Only spawning the compiled `WhisperProject.exe --worker` and sending a real `transcribe` command exposed it. Now covered by the smoke suite — see Added above.
- **Session 8** — `whisper_project.spec` retains the Session 8a `contents_directory='.'` on the `EXE()` call so bundled `bin/` lands beside the exe, not inside `_internal/`. The `build.bat` xcopy fallback is no longer triggered on a clean build.

### Changed

- **Session 12** — `whisper_project.spec` renamed to `whisper_project_onefile.spec` to disambiguate from the new onedir variant. EXE `name=` field updated to `WhisperProject-v0.7.0-Portable`. `installer.iss` `OutputBaseFilename=` updated to `WhisperProject-v0.7.0-Setup-Compact`. Both .gitignore whitelist entries follow the rename.
- **Session 12** — `tests/smoke/conftest.py` and `tests/smoke/test_exe_real_e2e.py` gained dual-launcher support. The new `gui_script` fixture reads `WHISPER_SMOKE_GUI` and, when set, makes the worker subprocess launch as `[pythonw, gui.py, "--worker"]` instead of `[exe, "--worker"]` — required to verify Method C without writing a third smoke file.
- **Session 12** — `installer_embed.iss` carries a `[UninstallDelete]` block that sweeps `__pycache__` and the install subdirectories on uninstall. Inno Setup otherwise leaves Python's runtime-generated `*.pyc` files behind because they weren't recorded in the install manifest.
- **Session 12** — Repo cleanup: nine phase-acceptance plans + briefs + session writeups (PHASE_0/1/1B/2A/3A/NEXT acceptance, PHASE_1 brief, PHASE_NEXT brief, NEXT_SESSION_HANDOFF, SESSION_8_PACKAGING_FIX, SESSION_SINGLE_FILE_EXE, SESSION_DUAL_DELIVERABLE) moved into `docs/history/` to keep the active docs surface at-a-glance. README rewritten 190 → ~60 lines. BUILD.md rewritten to cover all three pipelines.
- **Session 11** — `app/services/format_service.py` and `app/services/download_service.py` now branch on SMTV URLs (`core.integrations.smtv.parse_episode_id` and a `kind: "smtv"` marker on the format dict) and bypass the yt-dlp probe / spawn entirely. No behaviour change for YouTube or any other URL.
- **Session 11** — Both PyInstaller specs (`whisper_project_onefile.spec` and `whisper_project_onedir.spec`) gain `core.integrations.smtv` in `hiddenimports` so the module survives onefile bundling and onedir-via-installer packaging.
- **Session 7** — `docs/MANUAL_STEPS.md` scrubbed: the `## A. Security` block that named two leaked GitHub PAT prefixes was removed. Sections re-lettered (B → A through H → G) so the file still reads cleanly. The Summary was rewritten to drop the "two human-required items" framing; there's now exactly one open human decision — which Phase to ship next.
- **Session 7** — `README.md` "Project documentation" footer now points at `architecture-diagrams.md` first, then the direct SVG link, then the prose ARCHITECTURE.md, so a new reader hits the visuals before the prose.

### Notes

- The leaked PAT prefixes still appear in this repo's history at commit `6d97a5f`'s diff. With the tokens revoked (which the user was asked to do; see Session 7's pending-actions note in `SESSION_LOG.md`), those strings are inert. Standard guidance for accidental-token-commit is "revoke + move on" rather than rewrite history; we followed it.

- **Session 6 research** — `docs/COMPETITIVE_ANALYSIS_2026.md` (~2900 words, ~40 cited sources). 2026 STT landscape scoped to EN + CJK + FR + DE (Persian/Arabic explicitly excluded). Covers Alibaba FunAudioLLM (SenseVoice / FunASR / CapsWriter), NVIDIA NeMo (Parakeet-TDT-0.6B-v3 / Canary-1B-v2), Whisper speedups (Insanely-Fast-Whisper / WhisperX / stable-ts / WhisperKit / Whisper-Streaming / WhisperLive / pywhispercpp), Tencent Covo-Audio, and 17 commercial products (Deepgram Nova-3, AssemblyAI Universal-3-Pro + LeMUR, ElevenLabs Scribe v2, Descript, MacWhisper 12, Apple Voice Memos iOS 18, etc.). Synthesizes 15 candidate features ranked by impact, Chinese-language gotchas (tokenization, punctuation, simplified/traditional, line-length, CPS), best-model-per-language matrix, and a five-feature Descript-style Phase 4 editor blueprint.
- **`docs/architecture.svg`** — 1500×1100 layered system diagram, color-coded by role (user / UI / core / subprocess workers / external processes / filesystem / test+build / external network). Drop shadows, dashed-for-async arrows, red "killer flow" callout for Phase 3a auto-transcribe-after-download. Renders inline on GitHub. Authored after four reflection passes.
- **`docs/ROADMAP.md`** restructured (Session 6) — new **Phase 6 — CJK polish + pluggable backends** with 8 sub-items: SenseVoice + Parakeet pluggable backends, Chinese punctuation post-processor (FunASR `ct-punc`), CJK-aware line splitting per Netflix style guide, simplified↔traditional via OpenCC, number/date normalization via cn2an, hallucination + repetition cleanup, stable-ts integration for word-perfect timestamps, sound-event tagging for SDH. Old Phase 6 (Hardening) renumbered to Phase 7 with no content loss. **Phase 4 (editor) rewritten** to drop the RTL Persian items (de-scoped — user audience is now 94% Chinese) and adopt the Descript-style blueprint: edit-back-to-subtitle with re-flowed timestamps, gap/silence panel, speaker labels with global rename, multilingual filler-word bulk operations (EN/FR/DE/ZH dictionaries) with dual caption-only vs. cut modes, CJK-aware subtitle linter.
- `README.md` documentation footer updated to point at `docs/architecture.svg` and `docs/COMPETITIVE_ANALYSIS_2026.md`.
- **Final compile** — `whisper_project.spec` (PyInstaller `--onedir`, deterministic, committed) + `build.bat` at the repo root with documented exit codes (0 success / 1 PyInstaller failure / 2 verification failure / 3 smoke launch failure). Build verifies the four required runtime files (`WhisperProject.exe` plus `bin/ffmpeg.exe`, `bin/ffprobe.exe`, `bin/yt-dlp.exe`) and falls back to a manual `xcopy` of `bin/` if PyInstaller's `datas` silently dropped it (which it does — caught on the first build). `docs/BUILD.md` documents modes, exit codes, the `bin/` fallback, and explains why `config.json` is intentionally not in `dist/` (Phase 1.2 placed it in `%LOCALAPPDATA%`). `.gitignore` now keeps the committed `whisper_project.spec` while ignoring stray local `.spec` files.
- **Phase 3a** — yt-dlp killer features. New SQLite history DB at `%LOCALAPPDATA%\WhisperProject\history.db` with `downloads` and `transcriptions` tables, `mark_interrupted()` on startup, and a `Statistics` menu item showing download/transcription counts, total minutes, and top languages. SponsorBlock category checkboxes in the Advanced dialog (`sponsorblock_categories` config key) — when set, the categories are appended to yt-dlp via `--sponsorblock-remove`. Auto-transcribe-after-download wiring is fully active: a finished media download with `auto_transcribe_after_download=True` enqueues a `TranscriptionTask` with the captured language hint. The `--progress-template "%(progress)j"` JSON parser landed in Phase 1b is now the live progress source for download rows. Right-click history actions on both queue tabs: `Open output folder`, `Re-run`, `Remove`. 17 new unit tests (history 11, auto-transcribe wiring 6).
- **Phase 2a** — Whisper masterpiece. VAD on by default, configurable via three knobs (`vad_min_silence_ms`, `vad_threshold`, `vad_speech_pad_ms`). Word-level timestamps as an opt-in (`word_timestamps`). Language detection captured from `info.language`/`info.language_probability`, posted via a new `language_detected` worker event, and rendered in a new `language` column on the Transcription Queue tab. New `core/writers/` package — six pure writers (`srt`, `vtt`, `tsv`, `txt`, `json`, `lrc`) + a `get_writer` registry. Output formats are user-selectable from a new `Advanced...` dialog (defaults: `["srt", "json"]`). VTT emits karaoke-style `<HH:MM:SS.ms><c>word</c>` cues when words are present. `BatchedInferencePipeline` wraps the model on CUDA when available. `initial_prompt` and `hotwords` plumbing in place (UI in Phase 2b). 39 new unit tests + 4 real-audio smoke tests + 3 end-to-end tests.
- **Phase 1b** — Foundation refactor. The 1296-line `gui.py` becomes an 11-line `--worker`-aware entry point; the rest is now an `app/` package with `app.py` (Tk root, ~430 lines), `dialogs/`, `domain/`, `services/` (DownloadService, FormatService, TranscriptionService, IntegrationsService), `widgets/` (console + tab builders), and `observability.py` (env-gated Sentry). Per-instance queues replace module globals (closes AUDIT B3). `pyproject.toml` lands at the repo root with `[project.optional-dependencies]` for `dev`, `crash_reporting`, `theme_detection`. (PHASE_NEXT_BRIEF Phase 1b)
- **Phase 1b / tests** — `tests/core/` adds 71 new unit tests (config 9, model_manager 10, worker_protocol 10, subtitle_lang_args 10, download_command 20, transcriber_helpers 12). `core/` line coverage rises to 77% overall; testable modules sit at 81–92%.
- **Phase 1b / type hints** — `from __future__ import annotations` + complete type signatures across every `core/` module. `pyright core/` is clean (0 errors, 0 warnings).
- **Phase 1b / observability** — `app/observability.py` opt-in Sentry hook. Activated only when `SENTRY_DSN` env var is set. No DSN ever in code, config, or git history.
- **Phase 1b / acceptance** — `docs/PHASE_1B_ACCEPTANCE.md` with grep-able tests 1B-T1 through 1B-T7.
- `README.md` at project root — first-class entry point for new readers
- `docs/ARCHITECTURE.md` — describes the current process model, layout, key flows, and design rationale
- `docs/AUDIT.md` — full audit findings tagged critical / high / medium / low
- `docs/ROADMAP.md` — six-phase plan based on competitive analysis of nine Whisper GUI projects and eight yt-dlp GUI projects
- `docs/CHANGELOG.md` — this file
- `docs/CONFIG.md` — `config.json` field reference
- `docs/DECISIONS.md` — short ADRs for the load-bearing architectural choices
- `docs/PHASE_1_ACCEPTANCE.md` — machine-parseable test plan for Phase 1a (theme + platformdirs + logging)
- `.gitignore` — first proper gitignore for the project
- `requirements.txt` — runtime dependencies, with Phase 1/2 additions commented for later
- `Phase 0 fixes` — see "Changed" and "Fixed" below
- **Phase 1.1** — Sun Valley theme via `sv-ttk`. Selectable Light / Dark / System under `View` menu, persisted via the new `theme` config key. Transcribe tab `tk.Label`/`tk.Button`/`tk.Entry` widgets converted to `ttk` equivalents so the theme applies uniformly. (ROADMAP 1.1)
- **Phase 1.2** — `platformdirs`-backed config, cache, and log directories. `core/config.py` now exposes `user_config_dir()`, `user_cache_dir()`, `user_log_dir()`, `user_data_dir()`. New `migrate_config_location()` runs on every `load_config()` call: a legacy `config.json` next to source is copied to `%LOCALAPPDATA%\WhisperProject\config.json` and the original renamed to `.migrated.bak`. `model_path` defaults derived from `user_cache_dir()`. (ROADMAP 1.2)
- **Phase 1.3** — `core/logging_setup.py` with `setup_logging()`, `get_ui_logger()`, and `open_log_folder()`. `RotatingFileHandler` writes to `<user_log_dir>/app.log` (5 MB × 3). Both `gui.py` and `core/worker.py` call `setup_logging` at startup. Every previous `print()` outside the worker's JSON `emit()` is now a `logging.getLogger(__name__).info/warning/error` call. New `Help → Open log folder` menu item. (ROADMAP 1.3)
- **Phase 1.5** — `sv-ttk>=2.6.0` and `platformdirs>=4.0.0` promoted from "Phase 1 additions (uncomment when implementing)" to active dependencies. (ROADMAP 1.5)
- `docs/integrations/` — new home for cross-tool integration notes. Contains a `README.md` index, a research note + implementation brief for **oTranscribe** (web-based manual transcription tool). The pattern is: every integration gets a research note authored before code, a hands-off brief that drives an autonomous session, and an acceptance plan added when the work lands. Documents survive the merge — never deleted.
- `docs/integrations/otranscribe-research.md` — full schema of the `.otr` file format (plain JSON with four keys: `text` HTML, `media`, `media-source`, `media-time`), the timestamp `<span>` HTML structure, oTranscribe's import/export limitations (imports only `.otr`; exports `.otr`/`.txt`/`.md` with no SRT/VTT), keyboard shortcuts, and a three-tier integration plan (MVP converters / UI buttons / power features).
- `docs/integrations/otranscribe-brief.md` — implementation brief modeled on `docs/PHASE_1_BRIEF.md`. Three public functions (`srt_to_otr`, `whisper_json_to_otr`, `otr_to_srt`), three UI additions (Export menu item, Import button, Help → Open oTranscribe), pytest fixtures, nine grep-able acceptance tests, hands-off push policy, and the eight known traps that survived Phase 1's discovery (newlines inside `text`, NBSP after the timestamp span, no zero-padding on the hour, etc.).
- **Phase 2-oTranscribe** — bidirectional `.otr` file-format converter at `core/integrations/otranscribe.py`. Public surface: `fmt_otr_time`, `srt_to_otr`, `whisper_json_to_otr`, `otr_to_srt`. Stdlib only (`json`, `html`, `html.parser`, `re`, `pathlib`); zero new runtime deps.
- **Phase 2-oTranscribe / UI** — `Transcription Queue` right-click on a `finished` task gains `Export → oTranscribe (.otr)` (writes `<base>.otr` next to the existing `<base>.srt`). `Transcribe` tab gains an `Import .otr → SRT...` button that runs through two file pickers. `Help → Open oTranscribe...` opens the official site in the user's browser.
- **Phase 2-oTranscribe / tests** — `tests/integrations/test_otranscribe.py` with nine pytest cases (display format, ASCII round-trip, Persian round-trip, whisper-JSON conversion, NBSP boundary, single-line `text`, last-segment end inference, `media` basename only, smoke). Fixtures under `tests/integrations/fixtures/`.
- `docs/integrations/otranscribe-acceptance.md` — machine-parseable acceptance plan for the oTranscribe integration with a mandatory final JSON block.

### Fixed

- **CRITICAL**: `yt-dlp --update` no longer blocks every download. The unconditional pre-download update call previously broke offline use and any case where GitHub was rate-limiting. Update is now gated to once per launch (and only when the user opts in via `auto_update_yt_dlp` setting). Failures log and continue. (AUDIT A1)
- **CRITICAL**: `core/transcriber.py`'s `detect_device` no longer swallows `KeyboardInterrupt` and `SystemExit` via a bare `except:` (AUDIT A2)
- **CRITICAL**: `get_duration` in `core/transcriber.py` now resolves `ffprobe` from the bundled `bin/` folder instead of expecting it on `PATH` (AUDIT A3)
- **HIGH**: `current_video_language` is now only captured when the lookup result still matches the current URL — fixes wrong-language hint after rapid URL changes (AUDIT A4)
- **HIGH**: Partial subtitle files are deleted when the subtitle phase is cancelled mid-write (AUDIT A5)
- **HIGH**: `config.json` is written atomically (`.tmp` + `os.replace`) so a crash during save can no longer leave the file corrupt (AUDIT C1)
- **HIGH**: `load_config` falls back to baked-in defaults if `config.json` is missing or invalid, instead of crashing at startup (AUDIT C2)
- **CRITICAL**: `load_config` now repairs unreachable `model_path` (e.g. config referencing an unmounted drive like `X:\`) by substituting `%LOCALAPPDATA%\WhisperProject\models\<model-folder>`. Unreachable `download_folder` is cleared so the UI re-prompts. This fixes the `[WinError 3] The system cannot find the path specified: 'X:\\'` crash during model setup. (AUDIT C7, escalated from LOW after a real user hit it.)

### Changed

- `transcriber.py`'s busy-wait loop in `transcribe()` replaced with an `assert MODEL_READY` since the only call path goes through `load_existing_model` first (AUDIT B6)

---

## [0.3.0] — 2026-05-11

### Added

- Automatic subtitle download in the "Download Videos" tab — checkbox plus 30-language combo (`docs/auto-subtitles-feature.md`)
- Per-phase status indicator next to the subtitle combo
- `download_subtitles_enabled` and `download_subtitle_lang` persisted to `config.json`
- Subtitle phase explicit `--- Subtitle phase: … ---` markers in the console log
- `--write-auto-subs` AND `--write-subs` in one yt-dlp call — yt-dlp prefers manual captions when available

### Changed

- `SUBTITLE_LANGUAGES` reordered to Automatic, English, then alphabetical (was: arbitrary regional grouping)
- Multi-variant language entries collapse `zh-Hans,zh-CN`, `no,nb`, `he,iw`, `id,in`, `pt,pt-BR,pt-PT`, `es,es-419`
- Subtitle combo starts in `state="disabled"` to avoid a readonly→disabled flash on launch

### Fixed

- `--sub-langs en.*` was matching translated captions like `en-de-DE`, `en-ja`, `en-pt-BR`, downloading 7 files instead of 1. Now uses exact codes joined with commas.
- "no subtitles" detection regex now matches yt-dlp's actual output (`There are no subtitles for the requested languages` / `no automatic captions for the requested languages`) instead of the never-triggered `WARNING: There are no` pattern

---

## [0.2.0] — 2026-05-07

### Added

- Bundled `yt-dlp.exe` in `bin/` for video downloads
- "Download Videos" tab with URL input, format detection via `yt-dlp --dump-single-json`, audio-only and audio+video modes, output format selection
- Download queue with progress, cancel, remove

---

## [0.1.0] — Initial version

### Added

- Tk GUI for `faster-whisper` transcription
- Worker subprocess model with JSON event protocol
- Resumable, MD5-verified model download from a CDN mirror
- Transcription queue with cancel, pause/resume, retry
- Multiple parallel workers (`parallel_workers` config)
- SRT and JSON output next to the input file
