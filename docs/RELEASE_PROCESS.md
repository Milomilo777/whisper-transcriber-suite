# Release process

The exact sequence to ship a new build of Whisper Project. This was
originally written for a private-distribution workflow; the repo and
its GitHub releases are now public (`gh release create`/`gh release
view` against `Milomilo777/whisper-transcriber-suite`) — "Step 8 — Distribute" below
is stale on that point, everything else still applies.

If anything here disagrees with `CLAUDE.md`, CLAUDE.md wins (it's
auto-loaded into every Claude Code session and represents durable
rules).

---

## Same-version rebuild (no version bump) — RETIRED, do not use (2026-08-23)

**Retired.** The `--clobber` step below resets the affected asset's
GitHub download count to zero (it deletes-then-reuploads under the
hood). See CLAUDE.md "Never `--clobber` an existing release asset" —
cut a new patch version (Steps 1-10 below) instead, even for a small
same-day fix. Left below for historical reference only.

Use this — NOT Steps 1-10 below — when source changed but the release
should stay the SAME version number (a same-day fix/polish pass, not a
new release). Full copy-pasteable recipe: `docs/BUILD.md` → "Rebuild
without bumping the version". Short version:

1. Confirm `core/__init__.py` / `installer_embed.iss` / `pyproject.toml`
   still show the version you intend to ship (don't touch them).
2. `pyright app core` + `pytest tests/ --ignore=tests/smoke` clean.
3. `build_embed_installer.bat` → ISCC `installer_embed.iss` →
   `shutil.make_archive(...)` for the Portable zip (see BUILD.md for
   exact commands).
4. `gh release upload vX.Y.Z <the two files> --clobber` — updates the
   EXISTING release's assets in place, no new tag.
4b. macOS (optional, if the source changes affect it too): dispatch
    `macos-app.yml` (`gh workflow run macos-app.yml --ref master`),
    watch both matrix legs finish, `gh run download` the two `.dmg`s,
    then `gh release upload` them alongside the Windows assets. Full
    commands: `docs/BUILD.md` → "Step 4b".
5. Update `docs/CHANGELOG.md` (add bullets under the existing version
   heading, don't create a new one) and `docs/SESSION_HANDOFF_NEXT.md`.

---

## Step 0 — Decide what's shipping

* Read `docs/SESSION_HANDOFF_NEXT.md` — "what's pending" should be
  empty / acknowledged.
* Read `docs/FINAL_FREEZE_AUDIT_2026-05-21.md` (or the most recent
  freeze audit). Every blocker for this release should be either
  closed or consciously deferred with rationale.
* Open `docs/CHANGELOG.md`. Drafting the changelog entry first
  helps you spot anything that didn't actually land.

## Step 1 — Bump the version

Bump `pyproject.toml` from the `*-dev` suffix to the release number.

```
- version = "0.8.0-dev"
+ version = "0.8.0"
```

This single change should be its own commit so a future `git blame`
can point at the version bump cleanly.

## Step 2 — Update the changelog

In `docs/CHANGELOG.md`:

* Add a dated entry under `## [Unreleased]` → bump it to
  `## [0.8.0] — YYYY-MM-DD`.
* Summarise: new features, fixes, breaking changes, deprecations.
* Link to the relevant commits when possible.

## Step 3 — Write release notes

Create `docs/RELEASE_NOTES_v0.8.0.md` (mirroring the v0.7.0 / v0.7.1
shape). Sections to include:

* **What's new** — user-facing additions.
* **What changed** — behaviour changes (incl. silent ones).
* **Migration notes** — anything users need to do (delete an old
  cache, rename a config, etc.). For private distribution, be
  generous here — your users will read this.
* **Bug fixes** — short list.
* **Known issues** — items deferred to the next release.

## Step 4 — Run the full validation matrix

All of these must be green BEFORE building:

```cmd
pyright app/ core/                          ::  0 errors, 0 warnings
pytest tests/ --ignore=tests/smoke          ::  full unit + real-file E2E
pytest tests/core/test_transcribe_smoke.py  ::  smoke + end-to-end
pytest tests/core/test_transcribe_end_to_end.py
```

If anything's red, fix it before continuing. **Do not** ship a known
flake — your users will hit it.

## Step 5 — Build the three deliverables

From the repo root, in order:

```cmd
:: Portable (single-file EXE, ~447 MB at v0.7.1)
pyinstaller --noconfirm --clean whisper_project_onefile.spec
::    →  dist\WhisperProject-vX.Y.Z-Portable.exe

:: One-dir build (input to Setup-Compact)
pyinstaller --noconfirm --clean whisper_project_onedir.spec
::    →  dist_onedir\WhisperProject\

:: Embed-Python tree (input to Setup-Standard)
build_embed_installer.bat
::    →  embed_build\

:: Setup-Compact installer
"C:\Users\Owner\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
::    →  dist_installer\WhisperProject-vX.Y.Z-Setup-Compact.exe

:: Setup-Standard installer
"C:\Users\Owner\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer_embed.iss
::    →  dist_installer\WhisperProject-vX.Y.Z-Setup-Standard.exe
```

Update the version-string portions of `installer.iss` /
`installer_embed.iss` (line ~13: `AppVersion=…`,
`OutputBaseFilename=…`) before running ISCC. The PyInstaller
specs read the version from `pyproject.toml` automatically.

## Step 6 — Manual install + uninstall test

This is the test that catches release blockers. Do not skip.

For EACH of the three deliverables:

1. **Fresh user profile** — delete (or rename):
   * `%LOCALAPPDATA%\WhisperProject\`
   * The previous version's install directory under
     `C:\Program Files\WhisperProject\`
2. **Install** — run the EXE / Setup; pick the default folder.
3. **First-launch** — confirm the hub-folder dialog appears.
   * For one variant: pick the default `<app>/hub`.
   * For one variant: pick `D:\models` (outside the install dir).
4. **Transcribe** — drop a short file into the Transcribe tab.
   * Wait for it to finish.
   * Confirm `.srt` + `.json` were written next to the source.
   * Open the JSON viewer; confirm segments load.
5. **Uninstall** — run the uninstaller (or use Add/Remove Programs).
   * Variant 1 (hub inside app): no prompt; hub gone with install.
   * Variant 2 (hub on D:): prompted to delete the hub. Click No
     once; verify hub stays. Reinstall + uninstall again; click
     Yes; verify hub is gone.

If any step fails, **fix the bug and rebuild from Step 5**. Do not
ship the release with a known install / uninstall regression.

6. **In-place upgrade** (Standard installer) — without uninstalling,
   run the NEW `...-Setup-Standard.exe` over the existing install.
   `installer_embed.iss` uses a stable `AppId`, so this upgrades the
   files in place: the user does NOT need to uninstall first. Confirm
   the new version launches, the Start-menu shortcut still works, and
   `%LOCALAPPDATA%\WhisperProject\config.json` (settings + hub choice)
   survives. This is the path most existing users take to update; the
   in-app **Help → Check for updates...** notify-only check just points
   them at the download page (`core.updates`, opt-in, never auto-installs).

## Step 7 — Tag + push

```cmd
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

Force-push to a tag is pre-authorised in CLAUDE.md only for
v0.7.0 — for any newer tag you'd be re-tagging, which means
something went wrong; investigate before forcing.

## Step 8 — Distribute

Upload to your private channel:

* Three `*.exe` files
* The release notes (`docs/RELEASE_NOTES_vX.Y.Z.md`) — paste into
  the announcement.
* If the changelog mentioned migration notes (Step 3), repeat
  them in the announcement.

## Step 9 — Bump `pyproject.toml` to the next `-dev`

```
- version = "0.8.0"
+ version = "0.8.1-dev"
```

Commit. This signals on `main` that the next release is in progress
and prevents accidental re-release of the same artefact.

## Step 10 — Update SESSION_HANDOFF_NEXT.md

Set "Current state" to reflect the post-release state:

* Last release tag = vX.Y.Z
* Working branch = whatever's active for the next round
* Pending items = empty or "post-release tidy-up"

---

## Troubleshooting the release

### "Inno Setup compile failed"

Most often a Pascal-Script syntax error. The `[Code]` block is
parsed lazily — read the ISCC output carefully; it gives you a
line number inside the `.iss`.

### "PyInstaller built but the EXE crashes on launch"

* Run the EXE from a terminal so you can see the traceback
  (`WhisperProject-vX.Y.Z-Portable.exe`).
* Most common cause: a `hiddenimports` entry missing from the
  spec. Add the module name + rebuild.

### "First-launch hub dialog doesn't appear"

* `%LOCALAPPDATA%\WhisperProject\config.json` may have stale
  `hub_folder` value from a previous test. Delete the file and
  retry.
* Or: use `--safe-mode` to back up + reset config in one step.

### "Uninstall doesn't prompt to delete the hub"

* Confirm `installer.iss` (and `installer_embed.iss`) both contain
  the `[Code]` section with `CurUninstallStepChanged`.
* Confirm the parity test passes:
  `pytest tests/core/test_inno_uninstall_parser.py`.
* Confirm `config.json` actually has `hub_folder` set to a path
  OUTSIDE the install dir.

---

## Appendix — the long-term maintenance loop

Roughly every six months:

* Re-read `docs/SENIOR_REVIEW_2026-05-21.md` and the latest freeze
  audit. Items that survive two reviews are real technical debt;
  budget time to fix.
* Re-run `pyright app/ core/` on `main`. Tightening the baseline
  catches drift early.
* Confirm `requirements.txt` and `pyproject.toml` still agree.
* Bump major dependencies (faster-whisper, sherpa-onnx,
  pywhispercpp) one at a time, with a real-file E2E run between
  each. The model file format changes from time to time; the
  smoke test is your canary.

Update this document whenever the steps change. The version of
RELEASE_PROCESS.md that lives next to the tag is the one that
applied for that release.
