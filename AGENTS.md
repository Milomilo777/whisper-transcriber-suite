# AGENTS.md — Whisper Transcriber Suite

Rules and commands for anyone changing this repository: human contributors and AI coding agents
(Claude Code, Codex, Cursor, Copilot, …). `CLAUDE.md` only imports this file. If a document under
`docs/` disagrees with this file, this file wins.

## What this is

A desktop app (Python + Tkinter, Windows first, macOS and Linux builds too) that downloads
audio/video with yt-dlp and transcribes it locally with Whisper (faster-whisper by default), plus a
local HTTP API. User docs: `README.md` and `docs/README.md`; code map: `docs/ARCHITECTURE.md`.

## Layout

| Path | Contents |
|---|---|
| `gui.py`, `app/` | Tk GUI: `app.py`, `dialogs/`, `widgets/`, `services/`, `domain/` |
| `core/` | Engine: `transcriber.py`, `worker.py` (transcription subprocess), `backends/` (ASR engines), `writers/` (output formats), `server/` (HTTP API), `integrations/`, `config.py` |
| `tests/` | Hermetic suite; `tests/smoke/` needs real resources |
| `docs/` | User and maintainer docs; translated READMEs in `docs/i18n/` |
| `site/` | Project website and `llms.txt` |
| `platform/` | Per-OS packaging (`windows/`, `macos/`, `linux/`) and the stats server |
| `tools/` | Maintenance scripts (site data, graphics, e2e checks) |
| `bin/` | Bundled binaries (ffmpeg, yt-dlp, deno); not tracked, see `docs/BUILD.md` |

## Build and test

- Setup: `pip install -r requirements.txt`, then `pip install pyright pytest`.
- Run from source: `python gui.py` (or `run_from_source.bat`).
- Gate before every commit; both must pass:
  - `pyright app core`: 0 errors and 0 warnings. The baseline is 0 errors / 0 warnings /
    0 informations; keep it.
  - `python -m pytest tests/ --ignore=tests/smoke -q`: the hermetic suite.
  - `run_tests.bat` runs both on Windows and prints PASS or FAIL.
- `tests/smoke/` needs a real Whisper model, a test video and a network connection, and skips
  itself when they are absent; `docs/TESTING.md` and `tests/smoke/README.md` list the
  `WHISPER_SMOKE_*` variables that point it at them.
- Windows builds: `docs/BUILD.md`. Releases: `docs/RELEASE_PROCESS.md`. macOS builds:
  `docs/MACOS_BUILD_NOTES.md`.

## Shipped builds

- Published for Windows: the installer (`build_embed_installer.bat` → `installer_embed.iss`) and the
  Portable ZIP (an archive of the same `embed_build\` tree). macOS ships `.dmg` files built as
  `docs/MACOS_BUILD_NOTES.md` describes.
- The PyInstaller onefile (`whisper_project_onefile.spec`) and Compact/onedir
  (`whisper_project_onedir.spec` + `installer.iss`) pipelines are kept working but not published.
  Adding a module means updating the hidden-import lists of both specs and of
  `platform/macos/pyinstaller/whisper_project_mac.spec`, so no pipeline rots.
- Build only from a committed tree: every modified file is either committed or deliberate scratch.

## Code rules

- English only in code, comments, docs and commit messages; the translated READMEs in
  `docs/i18n/` are the exception. Features that accept non-English content (for example SMTV URLs)
  are a per-input capability, not a reason to add non-English UI or docs text.
- Persist completed work before reporting success. Transcription results are irreplaceable: output
  files, the history entry and any resume checkpoint are written BEFORE the UI or worker reports
  done. A delivery failure (worker crash, dropped queue event, UI-thread error) must never discard
  finished work. New transcription paths keep this order: save first, report second.
- Credit external code. When code is copied from, ported from or substantially inspired by another
  project, a Stack Overflow answer, a blog post or a paper, add at the implementation site:
  `# Adapted from <ProjectName> (<URL>) — <brief description of what was borrowed>`.
  General patterns and standard-library usage need no credit.

## Commits and changelog

- One coherent change per commit, even if that means several small commits in a row; do not squash
  across logical groups.
- Message: imperative subject of at most 70 characters, a blank line, then a body that explains why.
- `docs/CHANGELOG.md` (Keep a Changelog) bullets stay skimmable: 1–3 sentences on what changed and
  the fix. The investigation (repro, root cause, alternatives) goes in the commit message.
- `*.local.md` files are local notes and git-ignored; never commit them. Tracked files carry only
  what a contributor needs: what changed, the technical why, how to build and test, what is left.
  No personal data, secrets, private correspondence or machine-specific paths.

## Guardrails

Keep these in every clone; they protect users and release history.

- `master` is the single mainline. No force-push or history rewrite on it without an explicit
  maintainer request. The `archive/*` tags preserve old branch tips; keep them.
- Releases need the maintainer's explicit go-ahead every time: version bump, release build,
  `git tag`, `gh release create` and `gh release edit`. A broad "fix things" mandate is not that
  go-ahead. Batch several fixes into one release rather than releasing for every change.
- Never delete a published GitHub release, and never delete, move or force-push a published tag
  (`v1.0.3` and later are public; moving one invalidates artifacts users already downloaded),
  unless the maintainer names that release or tag in the same session.
- Never delete or re-upload a published release asset: not with `gh release upload --clobber`,
  not with `gh release delete-asset` + `upload`, not even for one platform's files. GitHub deletes
  the asset object either way and its download count is lost for good. To ship a fix, cut a new
  patch version with new file names. To fix a file name, rename the asset through the API
  (`PATCH /repos/{owner}/{repo}/releases/assets/{id}`), which keeps the count. The "rebuild
  without bumping the version" recipes still shown in `docs/BUILD.md` and
  `docs/RELEASE_PROCESS.md` are retired.
- `README.md` "Download" section: every release adds its own per-version download badge
  (shields.io `.../downloads/<owner>/<repo>/vX.Y.Z/total`); never remove an older one.
- macOS: never build or dispatch a macOS artifact (the local `platform/macos/` pipeline or
  `gh workflow run macos-app.yml`) unless the result will be verified on a real macOS system (a
  real Mac or a supervised macOS VM); a passing CI smoke test alone does not count. Read
  `docs/MACOS_BUILD_NOTES.md` before any macOS build work.
- Do not apply real code signing (a Windows certificate, an Apple Developer ID) or edit
  `.git/config` unless the maintainer asks; the ad-hoc signing inside the macOS pipeline is part
  of the build.
- A new capability is run end to end on real hardware and data before it ships (a real microphone
  for audio capture, a real file for a new format or backend). The automated gate does not
  replace this.
