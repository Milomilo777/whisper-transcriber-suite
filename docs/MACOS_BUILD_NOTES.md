# macOS build notes — what broke, why, and how the pipeline works now

_First written 2026-09-23 after building and testing v1.9.0 on a real Intel Mac
(macOS 10.15 in a VirtualBox VM) and on GitHub's Apple-silicon + Intel runners.
The full run log with every error verbatim is kept outside the repository; this file holds the lessons._

**Read this before touching** `platform/macos/**` or `.github/workflows/macos-app.yml`.

## TL;DR — the pipeline

**One command:** `bash platform/macos/build_mac.sh` runs every step below
(plus the 10.15 onnxruntime workaround) and leaves
`dist/WhisperTranscriberSuite-vX.Y.Z-macOS-<arch>.dmg`.
The repo-root `whisper_project_onedir.spec` / `whisper_project_onefile.spec`
hand over to the macOS spec when run on a Mac (see "Building with the
repo-root spec on a Mac" below), and the macOS spec fetches missing tools
and refuses a Python without Tk 8.6.

```bash
bash platform/macos/pyinstaller/fetch_mac_binaries.sh            # pinned self-contained ffmpeg/ffprobe + yt-dlp + deno + diarization models -> bin/
/usr/local/bin/python3.12 -m venv .buildenv && . .buildenv/bin/activate   # python.org 3.12 (has Tk 8.6)
grep -viE '^\s*(pywhispercpp|stable-ts)' requirements.txt > /tmp/req-slim.txt
pip install --prefer-binary -c platform/macos/pyinstaller/constraints-macos.txt -r /tmp/req-slim.txt pyinstaller
pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec
bash platform/macos/pyinstaller/verify_mac_bundle.sh               # every Mach-O self-contained?
bash platform/macos/pyinstaller/smoke_test_app.sh "dist/Whisper Transcriber Suite.app" python tiny
bash platform/macos/pyinstaller/builddmg.command                   # create-dmg, or hdiutil fallback
```
Release file name: `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` / `-arm64.dmg`.
CI (`macos-app.yml`, manual dispatch) runs exactly these steps on both archs.

## Building with the repo-root spec on a Mac (the colleague's way)

Also supported (restored 2026-09-27): the habit of the colleague who built the
earlier Mac versions. From the repo root, in the build venv (python.org Python
3.12 with Tk 8.6, slim requirements as in the TL;DR):

```bash
rm -rf dist
pyinstaller --noconfirm --clean whisper_project_onedir.spec   # or whisper_project_onefile.spec
rm -rf dist/dmg/ && mkdir dist/dmg && cp -R "dist/Whisper Transcriber Suite.app" dist/dmg/
rm -f "dist/Whisper Transcriber Suite.dmg"
create-dmg --volname "Whisper Transcriber Suite" --window-pos 200 120 --window-size 600 320   --icon-size 100 --icon "Whisper Transcriber Suite.app" 170 130   --hide-extension "Whisper Transcriber Suite.app" --app-drop-link 430 130   "dist/Whisper Transcriber Suite.dmg" "dist/dmg/"
```

- On macOS both repo-root specs run `whisper_project_mac.spec` and stop, so
  this gives the same verified `.app` as the TL;DR (tools fetched into `bin/`
  when missing, Tk 8.6 checked, minimum macOS computed). Windows is unchanged.
- A `BUNDLE(coll, name='Whisper Project.app', ...)` line appended to the root
  spec (the old local edit) is harmless: the hand-over stops before it.
- The app is **`Whisper Transcriber Suite.app`**, not `Whisper Project.app`;
  an old script that copies `dist/Whisper Project.app` needs that name
  changed. `bash platform/macos/pyinstaller/builddmg.command` does the dmg
  step with the right name (and falls back to `hdiutil` without create-dmg).
- `bash platform/macos/pyinstaller/compileall-whisper-mac.sh` (the
  colleague's committed script) is the same thing in one command:
  clean `dist/`, mac spec, `builddmg.command`.
- Use the **slim** venv. With torch / openai-whisper / stable-ts installed
  (an older venv) the build still finishes (5.4 min on the VM) and passes the
  smoke test, but PyInstaller bundles torch: the `.app` grows from 0.73 GB
  to 1.4 GB for a feature the `.app` does not offer.
- Then check it like any build: `verify_mac_bundle.sh` and
  `smoke_test_app.sh "dist/Whisper Transcriber Suite.app" python tiny`.

Verified 2026-09-27 on the macOS 10.15.7 VM from a fresh clone: the script
above verbatim (with the `BUNDLE` line appended to the spec; `hdiutil` in
place of create-dmg, which the VM lacks) built the `.app` + dmg in ~5 min
(~3 min once `bin/` has the tools);
`verify_mac_bundle.sh` OK; smoke test passed (WAV + MP4 transcription, GUI
launch, real YouTube download + merge). `compileall-whisper-mac.sh` and
`whisper_project_onefile.spec` were checked the same way (bundle check; the
script's dmg was mounted and smoke-tested). CI:
`macos-compileall-script-test.yml` (manual) runs the script and the
repo-root spec on Apple silicon, starting from Homebrew's ffmpeg in `bin/`
(the spec replaces it); green in run 36289429714.

## Next macOS release — the short checklist

What v1.9.0 and v1.9.3 did, in order; repeat it for the next version.

1. Bump the version (`core/__init__.py`, `pyproject.toml`, both `.iss`, README badge, CHANGELOG) and push.
2. **arm64 (Apple silicon):** `gh workflow run macos-app.yml --ref master`, wait until both jobs are green,
   then `gh run download <run-id> -n macos-dmg-arm64`. In the job log, note `[mac-spec] highest bundled minos`
   (14.0 for v1.9.0) for the release notes. The job has already smoke-tested the app on real Apple silicon.
3. **x64 (Intel):** build on the oldest macOS you can (the 10.15 VM gave a 10.15+ app; the CI Intel build
   needs macOS 14 because pip picks newer wheels there): from a fresh clone run
   `WTS_MACOS_MIN=10.15 bash platform/macos/build_mac.sh` in a logged-in desktop session (it runs
   `verify_mac_bundle.sh`, `smoke_test_app.sh` and, after the dmg, `test_dmg.sh`; all must pass). If no old Mac is available, the CI x64 dmg is acceptable. It needs macOS 14.
4. Create the release with the dmgs (no `.sha256` files) and
   its release notes (written in the release body; they are no longer kept as files in the repository). **New tag every time, even for a mac-only fix** — see
   AGENTS.md "Guardrails": never `delete-asset` + `upload` mac dmgs onto
   an already-published tag to avoid a new release page. Cut vX.Y.(Z+1) instead, even same-day, even if
   only macOS changed. If the Windows assets aren't uploaded yet, use
   `--latest=false` (README's "Download for Windows" points at `releases/latest`). Mark it Latest with
   `gh release edit vX.Y.Z --latest` once they are. If the version's release already exists (Windows
   files first), `gh release upload` the four mac files into it — without `--clobber`, never over a
   file that is already there.
5. Test the Terminal one-liner from the release notes against the published release. It downloads with
   `curl`, so there's no quarantine flag and no Gatekeeper dialog. Verified for v1.9.0 and v1.9.3 x64 on 10.15. The one-liner picks x64 on
   Apple-silicon Macs below the arm64 dmg's floor (macOS 14), where it runs through Rosetta.
6. Before the build, check the dependency pins are still right: `av<19` (PyAV 19 broke faster-whisper
   1.2.1, row 7 below) and `onnxruntime==1.19.2` in `constraints-macos.txt`. When a report says "the build
   failed" without a log, dispatch `macos-app.yml` first: it rebuilds and smoke-tests on real Macs of both
   archs in ~10 min and catches dependency drift that reading the scripts cannot.
7. Never commit from a VM/sandbox clone without first setting the repo identity
   (`Milomilo777 <117558067+Milomilo777@users.noreply.github.com>`). Don't commit machine user names,
   home paths (`/Users/<name>`), or screenshots that show them.

## Why earlier Mac builds "didn't work for users"

Each of these was reproduced on a real Mac. Any one of them is enough to ship a broken app.

| # | Symptom on the user's Mac | Root cause | Fix (where) |
|---|---|---|---|
| 1 | Transcription / any media step fails; bundled `ffmpeg` dies with `dyld: Library not loaded` | CI copied **Homebrew's** `ffmpeg`/`ffprobe` into `bin/`. They link **18 dylibs** under `/opt/homebrew` (libav*, x264, x265, dav1d, openssl, …). The spec bundled `bin/` as DATA, so none of those dylibs entered the .app. Homebrew bottles are also built for the runner's OS (`minos 15.0`), and there is no Intel-macOS ffmpeg bottle any more. | Static builds only: evermeet.cx (x86_64, minos 10.13) / martin-riedl.de (arm64, minos 12.0), fetched and `otool`-verified by `fetch_mac_binaries.sh`. |
| 2 | Downloads never work in the .app | CI never bundled yt-dlp. When bundled, PyInstaller **destroyed** it: `yt-dlp_macos` is itself a PyInstaller onefile whose payload is appended to the Mach-O; PyInstaller 6 re-classifies Mach-O "data" as binaries and rewrites them, dropping the payload (37 MB → 73 KB, `Could not load PyInstaller's embedded PKG archive`). | Spec copies yt-dlp **byte-for-byte after BUNDLE**, re-signs ad-hoc, and runs `--version` (fails the build if broken). |
| 3 | App refuses to open / crashes on "older" Macs even though CI said OK | Every wheel carries its own minimum macOS. `MACOSX_DEPLOYMENT_TARGET=12.0` in CI does **nothing** for prebuilt wheels. Unpinned, pip picks onnxruntime 1.23.2 on Intel (**macOS 13+**) and ≥1.24 on Apple silicon (**macOS 14+**), numpy's Accelerate wheels (14+), etc. Meanwhile the Info.plist hard-coded `LSMinimumSystemVersion 11.0` — a promise the bundle could not keep (and on 10.15 LaunchServices refused it: `error -10825`). | `constraints-macos.txt` pins onnxruntime 1.19.2 (macosx_11_0), numpy 1.26.4 and PyInstaller; `fetch_mac_binaries.sh` pins ffmpeg, yt-dlp and Deno by SHA-256. The spec **computes** `LSMinimumSystemVersion` from the highest `minos` in the bundle (`WTS_MACOS_MIN` overrides only after a real test on that OS). `verify_mac_bundle.sh` prints it. |
| 4 | Info.plist says 1.6.0 | Hard-coded version in the spec. | Read from `core.__version__`. |
| 5 | `invalid choice: 'from multiprocessing.resource_tracker import main;main(6)'` in logs | `gui.py` never calls `multiprocessing.freeze_support()`, so in a frozen app multiprocessing's helper re-launch re-enters the argparse CLI. | Runtime hook `rthook_mp_helpers.py` diverts it (packaging-level; the proper fix is in `gui.py`, see open issues). |
| 6 | Model download slower than needed | `hf_xet` not collected (dynamic import in huggingface_hub). | `hiddenimports += ['hf_xet']`. |
| 8 | Live tab: the app dies the moment recording starts (no dialog, no log line) | macOS 10.14+ (TCC) terminates a process that opens the microphone without `NSMicrophoneUsageDescription` in Info.plist. Neither the spec's `info_plist` nor `install.command`'s launcher plist had it (found 2026-10-01 by reading the plist; the VM has no audio device, so the kill itself was not reproduced). | Key set in `whisper_project_mac.spec` and `install.command`; `verify_mac_bundle.sh` and `test_dmg.sh` fail without it. Still to do on a real Mac with a microphone: open Live, expect the permission dialog, record. |
| 9 | "The bundled yt-dlp failed to run"; after another yt-dlp was swapped in, Download failed with `ImportError: You are using an unsupported version of Python. Only Python versions 3.10 and above are supported by yt-dlp`, traceback through `/Library/Developer/CommandLineTools/…/Python3.framework/Versions/3.9` (reported on v1.9.3, 2026-10-03, Intel Mac) | Two separate things. **(a) Quarantine:** every file of a browser-downloaded dmg carries `com.apple.quarantine`. Run directly (e.g. from Terminal) before the app was approved, the bundled yt-dlp is held by Gatekeeper ("can't be opened because Apple cannot check it") and SIGKILLed when the dialog is dismissed — reproduced on the 10.15 VM with the released v1.9.3 x64 dmg (5 min hang, exit 137). Approving the app with Open Anyway also flipped the nested tools' flag (`0083`→`00c3`), and then the app's Download tab worked, so the app path was fine on 10.15; the strip below removes the dependency on that. **(b) The replacement** was yt-dlp's plain `yt-dlp` release file — a Python zipapp (`#!/usr/bin/env python3`), not `yt-dlp_macos`. In Terminal `python3` was a 3.10+; an app opened from Finder has `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, so it ran on the Command Line Tools' Python 3.9. The app's own Python (3.12.10, in `Contents/Frameworks/Python.framework`) is not involved — building with 3.11 would change nothing. | `core.paths.clear_bundled_quarantine()`, called by `gui.py main()`, strips the flag from `Contents/MacOS/bin/*` at every start; `test_dmg.sh` tags the copied app's tools and checks that a start clears them. The spec treats a non-Mach-O `bin/yt-dlp`/`deno` as broken (re-fetches `yt-dlp_macos`), refuses to bundle one, and runs `--version` with a Finder-like env; `verify_mac_bundle.sh` checks both. Never replace the bundled yt-dlp with the `yt-dlp` script. |
| 10 | Every yt-dlp call (format lookup, download) waits ~25 s, 66 s cold; looks hung from Terminal | The onefile `yt-dlp_macos` unpacks itself into a new temp dir on every run, and dyld validates those fresh libraries each time (row 9's notes). First try at the onedir build, with its folder under `Contents/Frameworks/bin`, broke the build: `codesign` took `_internal/websockets-*.dist-info` for a nested bundle ("bundle format unrecognized, invalid, or unsuitable"). | Onedir `yt-dlp_macos.zip` (checked against SHA2-256SUMS) in `Contents/Resources/yt-dlp_dist`, linked from `Frameworks/bin/yt-dlp_dist` and `Frameworks/bin/yt-dlp` (→ its executable), and mirrored into `Contents/MacOS/bin` so `clear_bundled_quarantine()` walks its files. 2nd start ~0.5 s; `verify_mac_bundle.sh` fails above 15 s; `test_dmg.sh` checks a nested file loses its quarantine flag. (`fetch_mac_binaries.sh`, spec, `core/paths.py`) |
| 7 | Every transcription fails: `open() got an unexpected keyword argument 'metadata_errors'` (build itself succeeds; `build_mac.sh` fails at the smoke test) | **Dependency drift, not a repo change.** PyAV 19.0.0 (2026-09-29) removed `av.open(metadata_errors=...)`; faster-whisper 1.2.1 still passes it and only pins `av>=11`, so every fresh pip install from that day picked av 19. Seen on both archs in CI run 36736478555 (2026-09-30). | `av>=11,<19` in `requirements.txt`, `pyproject.toml` and `constraints-macos.txt` (c7238fe). Lift the cap only when faster-whisper's `audio.py` no longer uses the argument, then re-run `macos-app.yml`. |

The old CI "smoke test" (`transcribe --help`) could not catch any of these: it
never ran ffmpeg, yt-dlp or a real transcription, and it ran on the build
machine where Homebrew's dylibs exist. `smoke_test_app.sh` now does a real
transcription of synthesized speech from a WAV and an MP4 with an **empty
PATH**, launches the GUI through LaunchServices, and checks the bundled yt-dlp.

## Minimum macOS — what actually decides it

The .app's real floor is `max(minos)` over every Mach-O inside it
(`verify_mac_bundle.sh` → "highest minos"). As of v1.9.0 (v1.9.3 in the notes below the table):

| Build | Where built | Highest minos found | Tested on |
|---|---|---|---|
| x64 (release) | macOS 10.15.7 VM, python.org 3.12.10 | 12.0 (`protobuf google/_upb/_message.abi3.so`), 11.0 (onnxruntime); everything else ≤ 10.15 | **10.15.7**, full user flow (Stage 7 of the report); both >10.15 files exercised → `WTS_MACOS_MIN=10.15` |
| arm64 (release) | GitHub `macos-15` runner | **14.0** — PyAV 18.1.0's bundled ffmpeg libs (`libavcodec.62…`, `libSvtAv1Enc…`) and `tkinterdnd2/tkdnd/osx-arm64/libtkdnd2.10.2.dylib` | smoke test on real Apple silicon (WAV + MP4 transcription, GUI launch) |
| x64 via CI (not released) | GitHub `macos-15-intel` runner | **14.0** — numpy 2.5.3's `macosx_14_0_x86_64` (Accelerate) wheel | smoke test on real Intel hardware |

**v1.9.3:** x64 highest minos 12.0 (protobuf `_message.abi3.so` and the bundled
`deno` 2.9.7, which runs on 10.15 — real YouTube download through it verified);
LSMinimumSystemVersion 10.15. arm64 unchanged at 14.0 (same PyAV libs + tkdnd).
The mac spec now caps the computed value at the build Mac's own macOS for a
native build (pip only installs wheels for that macOS; the smoke test then runs
the app there), so a 10.15 build no longer needs `WTS_MACOS_MIN` to open on 10.15.

Every Apple-silicon Mac can run macOS 14, so 14.0 is acceptable for arm64 (the
release one-liner sends Apple-silicon Macs still on 11–13 to the x64 dmg). To lower a build's floor, pin the
packages the spec names in `[mac-spec] highest bundled minos` in `constraints-macos.txt` (e.g. `av` to a release whose
arm64 wheel is tagged `macosx_11_0`, numpy to a non-Accelerate wheel) and re-check the printed value. The Intel
release is built on the old macOS VM instead, where pip can only pick ≤10.15-compatible wheels.

dyld on 10.15 does not enforce a dylib's `minos`; what matters is whether a
newer API is actually called. That is why an override is only allowed after a
real run on that OS.

## Building on an old macOS (10.15) — extra gotchas

- **python.org 3.12.10** is the last 3.12 with a binary installer (later 3.12.x are source-only). Its Tk 8.6 works; Apple's `/usr/bin/python3` (Tk 8.5) does not.
- **No onnxruntime wheel for cp312 installs on macOS < 11.** Workaround used on the build host only: download the official `onnxruntime-1.19.2-cp312-cp312-macosx_11_0_universal2.whl`, copy it as `…macosx_10_15_universal2.whl`, and `PIP_FIND_LINKS=<that dir>`. Verified: imports, CoreML/CPU providers, Silero VAD and transcription all work on 10.15.
- **`--prefer-binary` is mandatory**: otherwise pip takes `av-18.1.0.tar.gz` (sdist) over `av-13.1.0-…macosx_10_13_x86_64.whl` and dies with `pkg-config is required for building PyAV`.
- **pywhispercpp ≥ 1.4 has no Intel wheel** and its whisper.cpp source fails on CLT 12 (`gguf.cpp: use of undeclared identifier 'errno'`). It is optional → excluded from the .app; `install.command` installs it best-effort.
- **Homebrew is not usable** on 10.15 (no bottles → compiles everything). Nothing in the pipeline needs it: `builddmg.command` falls back to `hdiutil`.

## Source install (`install.command`) on Intel Macs

Fixed in v1.9.0 — it used to abort on every Intel Mac:
1. `--prefer-binary` (PyAV sdist, see above);
2. optional `pywhispercpp` / `stable-ts` installed best-effort after the required deps;
3. **stable-ts is skipped on x86_64** (opt in with `WTS_INSTALL_STABLE_TS=1`): it pulls torch 2.2.2 (last Intel-mac torch). torch and ctranslate2 each ship `libiomp5.dylib`, and ctranslate2 imports torch whenever it is installed, so **every** transcription aborted with
   `OMP: Error #15: Initializing libiomp5.dylib, but found libiomp5.dylib already initialized` (exit 134).

## Gatekeeper — what a user actually sees (unsigned, ad-hoc signed)

Observed on 10.15.7 with a `.dmg` carrying a Safari quarantine flag:

1. Double-click in /Applications →
   **"Whisper Transcriber Suite" can't be opened because Apple cannot check it for malicious software.** (buttons: Show in Finder / OK).
2. **Right-click → Open** → same text but with an **Open** button → app starts; macOS remembers the choice (quarantine flag `0183…` → `01c3…`). `spctl -a -vv` still says `rejected` (expected for ad-hoc).
3. Not needed on 10.15, but documented for newer macOS: on **macOS 15+ the right-click route is gone** — use System Settings → Privacy & Security → **Open Anyway**, or `xattr -dr com.apple.quarantine "/Applications/Whisper Transcriber Suite.app"`.
4. Files fetched with `curl`/`git` are not quarantined — a Terminal one-liner install avoids the dialog entirely (see the release notes).

Apple Developer ID signing / notarization is **not pursued** (project decision, 2026-10-04); don't propose it.
The supported ways around the warning are the `curl` one-liner (no quarantine at all; re-verified 2026-10-04 on
10.15.7, including the nested yt-dlp run from Terminal) and Open Anyway / right-click → Open.

## Testing on a macOS VM (how the 2026-09-23 run was driven)

- VirtualBox VM made with `myspaghetti/macos-virtualbox` (supports ≤ 10.15; newer needs OpenCore). An in-place upgrade attempt to macOS 26 once left the APFS System volume unreadable by Catalina — don't.
- Enable `sshd` in the guest (`sudo launchctl load -w /System/Library/LaunchDaemons/ssh.plist`) + VirtualBox NAT port-forward → drive everything over SSH instead of typing into the VM window.
- Tk and `open` need the logged-in GUI session: run such commands with `sudo launchctl asuser <uid> sudo -u <user> …`.
- For Finder/GUI testing set the VM mouse to `usbtablet` and send absolute clicks through the VirtualBox COM API (`IMouse.PutMouseEventAbsolute`); screenshots via `VBoxManage controlvm <vm> screenshotpng`.
- The VM's clock runs slow under load — elapsed times inside the guest look shorter than real time.

## Hermetic test suite on macOS (2026-09-23, 10.15, python.org 3.12.10)

**2026-09-27 (v1.9.3, same machine):** 206 files, one per process →
**2759 passed, 0 failed, 7 skipped, 0 hung.** The earlier failures/hangs are
fixed; the run found three new test-side issues (fake-CUDA tests hitting the
macOS short-circuit, a non-hermetic end-to-end test) and one real one (the
model-loading dialog was placed as if 1×1 px), all fixed.

Earlier run:

2580 collected → **2565 passed, 5 failed, 7 skipped, 3 hung** (run one file per process; see the report).
Hangs block the whole suite (Tk's Cocoa event loop never returns to Python, so neither
`--timeout-method=thread` nor `signal` can recover), so run files separately on macOS.

## Open issues found (app/test code — not fixed by the packaging work)

**Owner decision (2026-09-23): fix all of these in the next build round.**
**Status 2026-09-24:** 1-8 fixed in code. **2026-09-27:** all eight verified in
the v1.9.3 Mac build (see below).

1. `gui.py` should call `multiprocessing.freeze_support()` first thing in `main()` (the runtime hook is a stop-gap).
2. `tests/core/test_advanced_simplified.py::test_gcloud_autotest_only_runs_when_google_cloud_is_picked` hangs forever in `dlg.update()` on macOS Tk.
3. `tests/core/test_google_cloud_stt.py::test_transcribe_without_load_raises` is not hermetic: `load()` → `core/optional_deps.install` runs a real `pip install` of google-cloud.
4. macOS failures: `test_model_loading_dialog.py::test_dialog_geometry_screen_centres_for_minimised_parent` (`expected screen-centred '+708+468', got '504x144+959+539'`); `test_nvidia_asr.py` ×2 (`cannot import name 'font' from 'tkinter' (unknown location)`); `test_tray.py` ×2 (tray is disabled on macOS by design, tests expect it enabled).
5. The first-download prompt always says "about 3 GB" even when the selected model is Small (~0.5 GB).
6. The headless CLI cannot download a model (no `--model`, default is the 3 GB large-v3; fresh config → `error: model not loaded`).
7. The "Engine: Checking…" label on the Transcribe tab never finished on 10.15.
8. yt-dlp warns `No supported JavaScript runtime could be found` — YouTube extraction may degrade without deno; consider bundling it.
   **Fixed in code 2026-09-24** (`core/js_runtime.py`): one-click Deno install into the user cache, or a
   `bin/deno` bundled next to yt-dlp is used automatically — see "Pending" below.

## v1.9.3 Mac build (2026-09-27) — what was verified, what is still open

Built from master `c42472d` (version 1.9.3): x64 on the macOS 10.15.7 VM with
`WTS_MACOS_MIN=10.15 bash platform/macos/build_mac.sh` from a fresh clone
(~8 min on the VM, PyInstaller ~4 min; 321 MB dmg); arm64 by
`macos-app.yml` (both CI jobs green, smoke test on Apple silicon; its live
YouTube leg is bot-blocked on CI runners as before).

Verified on 10.15.7 (source run, then the installed .app, then the release
one-liner):

- **Hardware (#7):** `python -m core.hardware` → "NVIDIA CUDA is not available
  on macOS"; Advanced → Re-detect hardware lists only the CPU tier, no
  "Install GPU support"; "Copy diagnostics" copies the report.
- **Deno / YouTube (#8):** from source with no Deno the Download tab shows
  **Install YouTube helper**; it installs deno 2.9.7 into
  `~/Library/Caches/WhisperTranscriberSuite/tools/deno/` with no quarantine
  xattr and a real YouTube download works. The .app now bundles `deno`
  next to yt-dlp (`Contents/MacOS/bin`), so the button no longer appears there.
  A `watch?v=X&list=Y` link downloads one video.
- **Log-in cookies:** Safari (9 cookies) and Firefox 156 (8 cookies, Firefox
  open) extract fine; a download with Firefox selected works. No Full Disk
  Access prompt for Safari on 10.15 (newer macOS may ask).
- **CLI:** `transcribe --model tiny <file>` on a fresh profile downloads the
  model and transcribes (source and frozen app); a video with no audio track
  says "has no audio track". "Engine: Checking…" resolves to Ready / "Model
  not downloaded yet" right away (no 15 s fallback needed).
- **Layout (1280×800):** main window fits with all tabs; Settings'
  Save/Cancel is visible (it was under the Dock — fixed); Fine-tune
  opens/closes; Download and Live tabs scroll.
- **stable-ts:** not bundled (torch's libiomp5 vs ctranslate2's on Intel, see
  the source-install section). The frozen app cannot pip-install anything
  (`sys.executable` is the app), so it now skips the 700 MB offer and says the
  feature needs a source install.

Fixed during this round (all on master): model-loading dialog centring,
Advanced dialog under the Dock, frozen-app on-demand installs, status lines
not refreshing after a model download, yt-dlp version/format-probe timeouts
(the onefile `yt-dlp_macos` needs ~26 s just to start on the VM), Deno
bundling, and the spec's own checks (tools auto-fetched, Tk 8.6 required,
minimum macOS capped at the build host).

Still open:

- **Apple silicon on macOS 12/13:** the arm64 dmg needs macOS 14 (PyAV ffmpeg
  libs, tkdnd). The one-liner sends those Macs to the x64 dmg (Rosetta);
  lowering the arm64 floor would mean pinning `av` / `tkinterdnd2` / numpy to
  older-tagged wheels on CI.
- **First YouTube lookup is slow** (~1 min on the VM: yt-dlp version check +
  probe, each unpacking the onefile yt-dlp). Not specific to 10.15: on a
  macOS 13.7 VM `yt-dlp --version` also takes ~29 s with ~1 s of CPU, and
  `sample` puts 3742 of 3752 samples in dyld's `__fcntl`, i.e. the loader
  waiting on code-signature validation of the libraries the onefile build
  extracts to a new temp folder on every run (2026-10-04). **Fixed
  2026-10-04:** the bundle now carries the onedir `yt-dlp_macos.zip`
  (row 10: `Contents/Resources/yt-dlp_dist`, linked from `Frameworks/bin`
  and mirrored into `Contents/MacOS/bin` so the quarantine clear reaches
  its files).
  Measured on 10.15: first run after install ~25 s (dyld validates the new
  files once), then ~0.5 s per start. `verify_mac_bundle.sh` fails if the
  second start takes over 15 s.
- Not tested: a real Apple-silicon Mac by hand (CI smoke only), Chrome/Brave
  cookies (no longer installable on 10.15), a trackpad's scroll feel,
  microphone/Live on the VM.

## Updating yt-dlp inside the Mac app

The app bundles yt-dlp's onedir build, which yt-dlp's own updater refuses, so a YouTube change used
to need a new app release. `core/yt_dlp_update.py` now does what it does on Windows, with one extra
first step (the "Update it" bar, or the automatic mode):

1. Fetch `https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS`; the redirect names
   the release tag, and the line for exactly `yt-dlp_macos` gives the expected SHA-256.
2. Download that tag's `yt-dlp_macos` (universal, about 37 MB) to a temporary name in
   `<user cache>/tools/yt-dlp/`. Only https to `github.com`, `objects.githubusercontent.com` and
   `release-assets.githubusercontent.com` is followed; the size is capped and the total time limited.
3. Compare the SHA-256 and the length. Only then `chmod 0755`, run `--version` and move it into place
   atomically. Any failure deletes the temporary file; the bundled copy is never touched.
4. Later updates are yt-dlp's own `--update-to stable` on that copy. The app runs the newer of the
   two copies (`resolve_yt_dlp_path`).

Minimum macOS: yt-dlp's README lists `yt-dlp_macos` as "Universal MacOS (10.15+) standalone
executable" (the README of 2026-10-09 has no `yt-dlp_macos_legacy` file any more, and the latest
release lists none), so macOS 10.15 is offered the download and anything older keeps the old advice
(`MACOS_MIN`). If a verified download does not start on some macOS anyway, `state.json` records
`bootstrap_refused` for that macOS version and the bar is not offered again until the macOS changes.

Known cost: the single-file build unpacks itself on every run (row 10 above: about 25 s per call
on the VMs), so once the downloaded copy is the newer one every yt-dlp call is slower than with the
bundled folder build. A folder-build variant (the release's `yt-dlp_macos.zip`, checked the same way,
but updated by downloading it again because yt-dlp refuses to update a folder build) would avoid it.

Checks on a real Mac: the bar appears after a failed YouTube download, **Update it** installs the
file (`state.json` has `cached` and `bootstrap`), `tools/yt-dlp/yt-dlp --version` runs from the app
(expected: no Gatekeeper hold, since the file has no quarantine flag when the app wrote it), Work offline refuses,
a second **Update it** runs `--update-to stable`, and a download after it works with the new copy.

## Native integration (app menu, Window and Help menus, Finder, Dock)

On macOS the app behaves like a Mac app: `app/mac_native.py` wires the hooks of Tk's Aqua port. Every
function is a no-op unless `tk windowingsystem` is `aqua`, so Windows and Linux are unchanged (the
tests run each case twice, once pretending to be Aqua and once as `win32` and `x11`). The code is
built only on hooks that `tools/mac_native_probe.py` proved on the real Tk.

**The probe.** `python tools/mac_native_probe.py` (standard library plus tkinter; run it in a desktop
session with the Python and Tk the app is built with) prints the Tk patch level, then `PASS` or `FAIL`
per hook, and exits 0 when every hook the app uses passes. It drives the real native menu bar through
the Objective-C runtime with `ctypes` (menu items are found by title and "clicked" with
`performActionForItemAtIndex:`), and sends the real Apple events with `open -a`. Result on macOS 13.7.8,
python.org Python 3.12.10, Tk 8.6.16:

| Hook | Result | Used for |
|---|---|---|
| `tk::mac::ShowPreferences` | PASS: the app menu item "Settings…" (Command-comma) is enabled and runs it | Settings opens the Advanced settings dialog |
| `tkAboutDialog` | PASS: the app menu's "About" item runs it | the app's own About dialog; Help no longer repeats About |
| `tk::mac::ShowHelp` | PASS: Tk adds "<App> Help" to a `.help` menu and runs it | opens `docs/README.md` on GitHub |
| `tk::mac::OpenDocument` | PASS: a file sent with `open -a` arrives | Finder "Open With", drops on the Dock icon |
| `tk::mac::ReopenApplication` | PASS: runs when the Dock icon is clicked while the window is minimised | shows the window again |
| `.window` menu | PASS: macOS adds Minimize, Zoom, Bring All to Front and the window list | Window menu |
| `.help` menu | PASS: Tk adds its Help item, macOS adds the search field | Help menu |
| `wm attributes -modified`, `-titlepath` | PASS: the window gets the proxy icon and the unsaved dot | transcript viewer |
| `.apple` menu | FAIL: its entries are not merged into the app menu (an extra top-level menu with an empty title appears) | not used |
| Dock menu | FAIL: Tk's application class has no `applicationDockMenu:` and Tk has no Tcl command for Dock entries (a positive and a negative control on the same query behaved) | not used; adding one needs a new native dependency, left for a later card |
| `tk::mac::standardAboutPanel` | exists, not used (it would show only the bundle's name and version, not the About dialog) | |

Findings that shaped the code (all measured with the probe or a throwaway script in the VM):

- Tk fills the Window and Help menus when its window first becomes active, so the menu bar must be
  attached before the window is first shown. The app builds it in `__init__`, which does.
- macOS adds the Help search field only to a menu titled exactly `Help`. A title such as `Help ●` loses
  it, so on macOS the update dot is shown on the "Check for updates" item only, never on the title.
- A Tk menu item with an `accelerator` is a real key equivalent (`File > Close Window` reports `w`).
- Python callbacks cannot run inside a synchronous Objective-C call from `ctypes` (fatal "GIL" error);
  the probe uses plain Tcl procs for that step. The app registers its commands with `createcommand`,
  which Tk runs from the event loop like the existing `::tk::mac::Quit` handler.

`app/mac_native.py` itself was also run in the same VM against a stub app (real menu bar built the
way `_build_menu` builds it, real mouse clicks, `open -a`): the app menu's About and Settings, the
Help item, File > Close Window (the viewer's own close handler ran) and a file with a space in its
path sent with `open -a` all reached their handlers, and the viewer showed its proxy icon. The Command-W
keystroke itself could not be sent through the VM's remote keyboard, so it is on the manual list below.

The macOS app build workflow (`macos-app.yml`) also runs the probe on the Intel and Apple-silicon
runners as an extra, non-blocking step (`continue-on-error`): a runner's Python may not be an app
bundle, so a FAIL line there is information, not a build failure. It has not been run yet: the
workflow runs on manual dispatch and on a push to the `macos-app-build` branch.

**Behaviour.**

- App menu: "About Whisper Transcriber Suite" and "Settings…" (Command-comma). Both do nothing (a beep)
  while a modal window is open or before start-up has finished, as the main window's buttons would.
- Window menu (Minimize Command-M, Zoom, Bring All to Front) and the Help menu with the native search
  field. **File > Close Window** (Command-W) closes the front secondary window by running its own
  close handler, so the transcript viewer still asks about unsaved edits. It never closes the main
  window. "Front" is AppKit's key window (`[NSApp keyWindow]` through `ctypes`), matched to a Tk
  window by title (compared composed and trimmed; the front-most one when titles repeat). A title that
  matches nothing closes only a secondary window Tk reports as focused, never the main window or a
  native panel; Tk's focus decides alone when AppKit cannot be asked. While a modal dialog holds the
  Tk grab only that dialog (or a window opened from it) closes, any other window gets a beep. Measured on macOS 13.7.8 / Tk 8.6.16: after the viewer's Find dialog and an alert
  were closed, `focus_get()` returned `None` while the viewer was still the key window, so a
  focus-based Close Window silently did nothing; `wm stackorder .` stayed correct (lowest first).
- Title bars follow the theme (`app/theme/mac_appearance.py`). Tk 8.6.16's
  `::tk::unsupported::MacWindowStyle appearance <window> aqua|darkaqua|auto` pins one window's
  appearance; the app sets it on the main window and every dialog (on `<Map>`, so a dialog opened
  later gets it) from the theme mode: Light = `aqua`, Dark = `darkaqua`, System = `auto`. Measured in
  the VM on a Light macOS 13.7.8: `darkaqua` gave a dark title bar on the root and a Toplevel,
  `aqua` a light one, `auto` back to the system look. The same `isdark` that "System" asks answers
  for the pinned window (`darkaqua` => 1 whatever the Mac says), so the mode is applied BEFORE the
  theme is resolved, or "System" would read its own earlier pin. Checked on a Dark macOS with
  Light chosen too. Native alerts and file dialogs are not Tk windows and keep the system look.
- Open files from Finder: never PyInstaller `argv_emulation` (it conflicts with Tk). The handler is
  registered before the first event-loop turn; files wait in a queue until the first-run windows and
  any modal window or question are done (the Tk grab, a mapped transient window, the quit question,
  the quick start and model folder windows; the transcript viewer and search window do not count),
  then go through `App.open_paths`: the same path and English-only model question as a drop on the
  window. Unlike a drop, Finder files must be audio or video (`core.watcher.is_media_file`), because
  "Open With" can offer the app for any file; others get the drop's "Ignored ... item(s)" log line. The spec declares `CFBundleDocumentTypes`
  (`platform/macos/pyinstaller/document_types.py`, built from `core/media_types.py`): role Viewer, rank
  Alternate, so Finder lists the app under "Open With" and never makes it the default app. `.ts` gets no
  explicit entry (TypeScript), but `public.movie` may still list the
  app for some `.ts` files (rank Alternate, so only under "Open With"). `verify_mac_bundle.sh` and `test_dmg.sh` check the key in the built app. The
  source install (`install.command`) writes its own small Info.plist and declares no document types, so
  "Open With" is for the packaged app only.
- Dock icon: a click while the window is minimised or hidden in the tray shows it again.
- Wording: "Reveal in Finder" where a file is selected with `open -R` (a finished job's first
  output, a burned video, a converted transcript, the viewer's JSON); where only a folder opens it says
  "Open … Folder in Finder" (model folder, log folder, a row with nothing to select). If `open -R`
  fails the folder is opened instead. There is no Options or Preferences window or menu item in the
  app; the native item is the system's own wording ("Settings…" on macOS 13, "Preferences…" on 10.15).
- Transcript viewer: the transcript file is the window's proxy icon and unsaved edits show the dot in
  the close button.

**Manual checks on a Mac (the automated tests cannot see these).** From a built `.app` on macOS 13 and
10.15:

1. App menu shows "About Whisper Transcriber Suite" and "Settings…" (macOS 13) or "Preferences…"
   (10.15); Command-comma opens Advanced
   settings; About opens the full About dialog; Help has no second About.
2. Window menu lists the open windows; Command-M minimises; Bring All to Front works. Help shows the
   search field and a Help item that opens the documentation page.
3. Open a transcript viewer; Command-W closes it; with an unsaved edit it asks first and Cancel keeps it;
   the dot shows in the close button while edits are unsaved; Command-click the title shows the path.
4. Finder: right-click an `.mp3` > Open With lists the app (not as default); choose it with the app
   closed (it starts and fills the file picker) and open; drag three files onto the Dock icon (they are
   queued once the first-run windows are closed); on a fresh install nothing opens before the quick
   start and model folder windows are dismissed; a non-audio, non-video file chosen with Other... is
   reported in the log and not picked.
5. Minimise the window, click the Dock icon: it returns.
6. Last Result card, queue and Help menu say "Reveal in Finder"; the button selects the output file.

### Appearance, system font and notifications

Same rules as above: Aqua only, Windows and Linux unchanged, built only on what the probe proved.
`python tools/mac_native_probe.py --flip-appearance` adds the appearance checks. The flip changes the
real Light/Dark setting, so it runs only with that flag; it restores the original value in a `finally`
step and prints both values (`appearance_original`, `appearance_restore`). Raw key lines, macOS 13.7.8,
python.org Python 3.12.10, Tk 8.6.16 (original setting Light, final setting Light):

```
INFO tk_patchlevel: 8.6.16
PASS appearance_isdark: isdark=0; NSApp effectiveAppearance='NSAppearanceNameAqua' (agrees)
PASS appearance_events: set dark=True: events=['<<DarkAqua>>'], isdark at event=[True], isdark now=1; set dark=False: events=['<<LightAqua>>'], isdark at event=[False], isdark now=0
PASS appearance_restore: original dark mode=False, final dark mode=False
INFO font_named: TkDefaultFont: -family .AppleSystemUIFont -size 13 -weight normal ...
PASS system_font_name: a font asked for '.AppleSystemUIFont' really is '.AppleSystemUIFont'; TkDefaultFont is '.AppleSystemUIFont'
INFO font_candidate: 'Segoe UI Variable Text': in `font families`=False; a font asked for it draws as '.AppleSystemUIFont'
INFO font_script: persian U+0645: system font -> '.SF Arabic'
INFO font_script: han U+6F22: system font -> '.PingFang SC'
INFO font_script: hangul U+D55C: system font -> '.Apple SD Gothic NeoI'
INFO font_script: thai U+0E01: system font -> '.ThonburiUI'
PASS app_active: NSApp isActive=1 isHidden=0; wm state='normal'; focus -displayof='.'
```

- **System theme.** `tk::unsupported::MacWindowStyle isdark .` answers the current appearance and Tk
  sends `<<LightAqua>>` / `<<DarkAqua>>` to the main window on a flip. `<<TkSystemAppearanceChanged>>`
  never fired in the probe and is not used. `MacBackend` in `app/theme/system_appearance.py` binds the
  two events (no timer, no thread) and re-reads `isdark`; a failed restyle is retried a few times like
  on Windows. In the real app the System mode followed a live flip, with a dialog open and with the
  window minimised or hidden; an explicit Light or Dark choice ignored the flip, and the saved choice
  was never rewritten. macOS draws the title bar and the window controls from the system setting,
  so an explicit Light choice under a Dark system keeps a dark title bar (as before this change).
- **System font.** sv_ttk names Windows families. Tk on macOS substitutes the system font for an unknown
  family, but the theme fonts now name `.AppleSystemUIFont` after every theme switch (sizes kept; the
  "Semibold" ones become bold), and the four hard-coded "Segoe UI" fonts go through
  `app/theme/system_fonts.py`. Per-script fonts stay Windows-only: the rows above show macOS draws
  Persian and Arabic, Han, Hangul and Thai in its own per-script fonts. Checked by name in the real
  app: every `SunValley*Font` is `.AppleSystemUIFont`, and a Persian character in the body font is
  drawn by `.SF Arabic`. Not yet checked on macOS 10.15.
- **Notifications.** `app/desktop_alert.py`, called from the same completion hook as the Windows tray
  toast, through the existing "Chime on completion" setting (the macOS menu text is "Chime and notify on
  completion"). It runs `/usr/bin/osascript` on a worker thread (15 s timeout, no shell) with a fixed
  script that reads the text and title from its arguments:
  `osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title (item 2 of argv)' -e 'end run' -- TEXT TITLE`.
  23 awkward strings (quotes, backslashes, new lines, a leading `-`, `--`, `-e`, Persian with a
  zero-width non-joiner, emoji, 3000 characters, an attempted `do shell script`) came back from
  `osascript` byte for byte and none ran as code. It follows the chime's completion events, one banner
  per user job on its last stage: a finished transcription, a finished download (only when no
  transcription follows it) and a finished subtitle burn (a manual burn, or the end of a "Make
  subtitled video" chain, whose transcription stage posts nothing). When the last transcription of a
  queue of two or more finishes, one summary replaces that job's own banner; the count starts over when
  the queue goes idle. A job with no output files, or no recognised speech, says so instead of
  "Done". A chain that ends in an error posts one "Subtitled video not made" banner (its transcription stage posted
  nothing); other failures and cancellations post nothing. Click behaviour: the
  banner belongs to Script Editor (the host of `osascript`), so a click opens Script Editor and cannot
  bring this app forward; the app does not promise otherwise.
- **When the app counts as "in the background".** Tk's focus alone is wrong: measured with the real app,
  with another app in front or after Cmd+H, `focus -displayof` still named a widget while
  `[NSApp isActive]` was 0, and a minimised main window leaves the app active with a focus widget.

  | Situation | `focus -displayof` | `wm state` | `NSApp isActive` | Notification |
  |---|---|---|---|---|
  | window in front | the window | normal | 1 | no |
  | window in front, just clicked a tab | none | normal | 1 | no |
  | main window minimised | the window | iconic | 1 | yes |
  | Cmd+H (hidden) | the window | normal | 0 | yes |
  | another app in front | a widget (or none) | normal | 0 | yes |

  The app therefore does not post when `[NSApp isActive]` (read with `ctypes`, like the probe) is true and the
  main window is mapped and not iconic or withdrawn; Tk's focus is not consulted (a re-test on macOS 13 showed
  a banner over the front window when the person had just clicked a tab and no widget held the focus). If
  NSApp cannot be asked the app counts as being in the background (logged once): a banner too many is harmless,
  a missing one is not. In the VM each row behaved as
  the last column says, and with the chime setting off nothing was posted.

Manual checks on a Mac (macOS 13 done in the VM; 10.15 still to do): flip System Settings >
Appearance with the theme on System; finish a short job with the app in the background, minimised and
hidden (a banner each time) and in front (none); open the Script Editor icon's banner once to see where
a click goes.

## Next steps worth doing

- **universal2**: python.org 3.12 is universal2; fuse per-arch wheels with `delocate-merge`, `fetch_mac_binaries.sh universal2`, `WTS_TARGET_ARCH=universal2 WTS_DMG_SUFFIX=universal`, then `verify_mac_bundle.sh <app> universal2`.
- Developer ID signing / notarization is not pursued (project decision).
