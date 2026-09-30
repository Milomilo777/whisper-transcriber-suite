# macOS build notes — what broke, why, and how the pipeline works now

_First written 2026-09-23 after building and testing v1.9.0 on a real Intel Mac
(macOS 10.15 in a VirtualBox VM) and on GitHub's Apple-silicon + Intel runners.
The full run log (every command, every error verbatim, screenshots) is in
[`docs/reports/2026-09-23-macos-vm-build-report.md`](reports/2026-09-23-macos-vm-build-report.md)._

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
bash platform/macos/pyinstaller/fetch_mac_binaries.sh            # self-contained ffmpeg/ffprobe/ffplay + yt-dlp + deno -> bin/
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
   `verify_mac_bundle.sh` and `smoke_test_app.sh`; both must pass). If no old Mac is available, the CI x64 dmg is acceptable. It needs macOS 14.
4. Create the release with the dmgs (no `.sha256` files) and
   `docs/release-notes/RELEASE_NOTES_vX.Y.Z.md`. **New tag every time, even for a mac-only fix** — see
   CLAUDE.md "Never `--clobber` an existing release asset": never `delete-asset` + `upload` mac dmgs onto
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
| 3 | App refuses to open / crashes on "older" Macs even though CI said OK | Every wheel carries its own minimum macOS. `MACOSX_DEPLOYMENT_TARGET=12.0` in CI does **nothing** for prebuilt wheels. Unpinned, pip picks onnxruntime 1.23.2 on Intel (**macOS 13+**) and ≥1.24 on Apple silicon (**macOS 14+**), numpy's Accelerate wheels (14+), etc. Meanwhile the Info.plist hard-coded `LSMinimumSystemVersion 11.0` — a promise the bundle could not keep (and on 10.15 LaunchServices refused it: `error -10825`). | `constraints-macos.txt` pins onnxruntime 1.19.2 (macosx_11_0). The spec **computes** `LSMinimumSystemVersion` from the highest `minos` in the bundle (`WTS_MACOS_MIN` overrides only after a real test on that OS). `verify_mac_bundle.sh` prints it. |
| 4 | Info.plist says 1.6.0 | Hard-coded version in the spec. | Read from `core.__version__`. |
| 5 | `invalid choice: 'from multiprocessing.resource_tracker import main;main(6)'` in logs | `gui.py` never calls `multiprocessing.freeze_support()`, so in a frozen app multiprocessing's helper re-launch re-enters the argparse CLI. | Runtime hook `rthook_mp_helpers.py` diverts it (packaging-level; the proper fix is in `gui.py`, see open issues). |
| 6 | Model download slower than needed | `hf_xet` not collected (dynamic import in huggingface_hub). | `hiddenimports += ['hf_xet']`. |
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

Only a paid Apple Developer ID + notarization removes the warning.

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
- **First YouTube lookup is slow on old Macs** (~1 min on the VM: yt-dlp
  version check + probe, each unpacking the onefile yt-dlp). Bundling the
  onedir `yt-dlp_macos.zip` instead would cut that.
- Not tested: a real Apple-silicon Mac by hand (CI smoke only), Chrome/Brave
  cookies (no longer installable on 10.15), a trackpad's scroll feel,
  microphone/Live on the VM.

## Next steps worth doing

- **universal2**: python.org 3.12 is universal2; fuse per-arch wheels with `delocate-merge`, `fetch_mac_binaries.sh universal2`, `WTS_TARGET_ARCH=universal2 WTS_DMG_SUFFIX=universal`, then `verify_mac_bundle.sh <app> universal2`.
- Developer ID signing + notarization (removes Gatekeeper friction entirely).
