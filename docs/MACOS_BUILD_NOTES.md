# macOS build notes — what broke, why, and how the pipeline works now

_First written 2026-09-23 after building and testing v1.9.0 on a real Intel Mac
(macOS 10.15 in a VirtualBox VM) and on GitHub's Apple-silicon + Intel runners.
The full run log (every command, every error verbatim, screenshots) is in
[`docs/reports/2026-09-23-macos-vm-build-report.md`](reports/2026-09-23-macos-vm-build-report.md)._

**Read this before touching** `platform/macos/**` or `.github/workflows/macos-app.yml`.

## TL;DR — the pipeline

```bash
bash platform/macos/pyinstaller/fetch_mac_binaries.sh            # self-contained ffmpeg/ffprobe/ffplay + yt-dlp -> bin/
python3 -m venv .buildenv && . .buildenv/bin/activate              # python.org 3.12 (has Tk 8.6)
grep -viE '^\s*(pywhispercpp|stable-ts)' requirements.txt > /tmp/req-slim.txt
pip install --prefer-binary -c platform/macos/pyinstaller/constraints-macos.txt -r /tmp/req-slim.txt pyinstaller
pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec
bash platform/macos/pyinstaller/verify_mac_bundle.sh               # every Mach-O self-contained?
bash platform/macos/pyinstaller/smoke_test_app.sh "dist/Whisper Transcriber Suite.app" python tiny
bash platform/macos/pyinstaller/builddmg.command                   # create-dmg, or hdiutil fallback
```
Release file name: `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` / `-arm64.dmg`.
CI (`macos-app.yml`, manual dispatch) runs exactly these steps on both archs.

## Next macOS release — the short checklist

What v1.9.0 did, in order; repeat it for the next version.

1. Bump the version (`core/__init__.py`, `pyproject.toml`, both `.iss`, README badge, CHANGELOG) and push.
2. **arm64 (Apple silicon):** `gh workflow run macos-app.yml --ref master`, wait until both jobs are green,
   then `gh run download <run-id> -n macos-dmg-arm64`. In the job log, note `[mac-spec] highest bundled minos`
   (14.0 for v1.9.0) for the release notes. The job has already smoke-tested the app on real Apple silicon.
3. **x64 (Intel):** build on the oldest macOS you can (the 10.15 VM gave a 10.15+ app; the CI Intel build
   needs macOS 14 because pip picks newer wheels there): run the TL;DR pipeline above with
   `WTS_MACOS_MIN=10.15` (see the 10.15 onnxruntime note), then `verify_mac_bundle.sh` and
   `smoke_test_app.sh` must both pass. If no old Mac is available, the CI x64 dmg is acceptable. It needs macOS 14.
4. Check `sha256sum -c` for each `.dmg.sha256` and create the release with the dmgs + `.sha256` files and
   `docs/release-notes/RELEASE_NOTES_vX.Y.Z.md`. If the Windows assets aren't uploaded yet, use
   `--latest=false` (README's "Download for Windows" points at `releases/latest`). Mark it Latest with
   `gh release edit vX.Y.Z --latest` once they are.
5. Test the Terminal one-liner from the release notes against the published release. It downloads with
   `curl`, so there's no quarantine flag and no Gatekeeper dialog. Verified for v1.9.0 x64 on 10.15.
6. Never commit from a VM/sandbox clone without first setting the repo identity
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

The old CI "smoke test" (`transcribe --help`) could not catch any of these: it
never ran ffmpeg, yt-dlp or a real transcription, and it ran on the build
machine where Homebrew's dylibs exist. `smoke_test_app.sh` now does a real
transcription of synthesized speech from a WAV and an MP4 with an **empty
PATH**, launches the GUI through LaunchServices, and checks the bundled yt-dlp.

## Minimum macOS — what actually decides it

The .app's real floor is `max(minos)` over every Mach-O inside it
(`verify_mac_bundle.sh` → "highest minos"). As of v1.9.0:

| Build | Where built | Highest minos found | Tested on |
|---|---|---|---|
| x64 (release) | macOS 10.15.7 VM, python.org 3.12.10 | 12.0 (`protobuf google/_upb/_message.abi3.so`), 11.0 (onnxruntime); everything else ≤ 10.15 | **10.15.7**, full user flow (Stage 7 of the report); both >10.15 files exercised → `WTS_MACOS_MIN=10.15` |
| arm64 (release) | GitHub `macos-15` runner | **14.0** — PyAV 18.1.0's bundled ffmpeg libs (`libavcodec.62…`, `libSvtAv1Enc…`) and `tkinterdnd2/tkdnd/osx-arm64/libtkdnd2.10.2.dylib` | smoke test on real Apple silicon (WAV + MP4 transcription, GUI launch) |
| x64 via CI (not released) | GitHub `macos-15-intel` runner | **14.0** — numpy 2.5.3's `macosx_14_0_x86_64` (Accelerate) wheel | smoke test on real Intel hardware |

Every Apple-silicon Mac can run macOS 14, so 14.0 is acceptable for arm64. To lower a build's floor, pin the
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

2580 collected → **2565 passed, 5 failed, 7 skipped, 3 hung** (run one file per process; see the report).
Hangs block the whole suite (Tk's Cocoa event loop never returns to Python, so neither
`--timeout-method=thread` nor `signal` can recover), so run files separately on macOS.

## Open issues found (app/test code — not fixed by the packaging work)

**Owner decision (2026-09-23): fix all of these in the next build round.**

1. `gui.py` should call `multiprocessing.freeze_support()` first thing in `main()` (the runtime hook is a stop-gap).
2. `tests/core/test_advanced_simplified.py::test_gcloud_autotest_only_runs_when_google_cloud_is_picked` hangs forever in `dlg.update()` on macOS Tk.
3. `tests/core/test_google_cloud_stt.py::test_transcribe_without_load_raises` is not hermetic: `load()` → `core/optional_deps.install` runs a real `pip install` of google-cloud.
4. macOS failures: `test_model_loading_dialog.py::test_dialog_geometry_screen_centres_for_minimised_parent` (`expected screen-centred '+708+468', got '504x144+959+539'`); `test_nvidia_asr.py` ×2 (`cannot import name 'font' from 'tkinter' (unknown location)`); `test_tray.py` ×2 (tray is disabled on macOS by design, tests expect it enabled).
5. The first-download prompt always says "about 3 GB" even when the selected model is Small (~0.5 GB).
6. The headless CLI cannot download a model (no `--model`, default is the 3 GB large-v3; fresh config → `error: model not loaded`).
7. The "Engine: Checking…" label on the Transcribe tab never finished on 10.15.
8. yt-dlp warns `No supported JavaScript runtime could be found` — YouTube extraction may degrade without deno; consider bundling it.

## Next steps worth doing

- **universal2**: python.org 3.12 is universal2; fuse per-arch wheels with `delocate-merge`, `fetch_mac_binaries.sh universal2`, `WTS_TARGET_ARCH=universal2 WTS_DMG_SUFFIX=universal`, then `verify_mac_bundle.sh <app> universal2`.
- Developer ID signing + notarization (removes Gatekeeper friction entirely).
