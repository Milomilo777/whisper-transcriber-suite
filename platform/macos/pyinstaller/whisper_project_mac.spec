# whisper_project_mac.spec — macOS .app build for the PyInstaller pipeline.
#
# THIS IS THE THIRD SPEC COPY (see CLAUDE.md "Style & scope"): adding a new
# module means updating whisper_project_onefile.spec AND
# whisper_project_onedir.spec AND this file's hiddenimports / datas so none of
# the pipelines bit-rot. Its hiddenimports + datas are kept in lock-step with
# whisper_project_onedir.spec (the Windows onedir build); the ONLY differences
# are the macOS .app BUNDLE wrapper at the bottom and the icns icon.
#
# Run (ON A MAC — cannot be built on Windows/Linux):
#     pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec
#
# Output: dist/Whisper Transcriber Suite.app  (then wrap into a .dmg via builddmg.command).
#
# Packaging prerequisites on the Mac (see ../pyinstaller/README.md):
#   * put SELF-CONTAINED mac ffmpeg/ffprobe/ffplay + yt-dlp in ./bin — NOT the
#     .exe ones and NOT Homebrew's (dylib-dependent) ffmpeg. Run
#     platform/macos/pyinstaller/fetch_mac_binaries.sh to fetch + verify them.
#     ffplay is what makes the Video Tiling tab work out of the box.
#   * optional: assets/whisper.icns for the Dock icon.
#
# The app's core.paths.resource_base() returns sys._MEIPASS inside the frozen
# .app bundle, which is where COLLECT lays out bin/ + the bundled data files —
# no source changes needed. bundled_binary() drops the .exe suffix off Windows,
# so it resolves bin/ffmpeg / bin/ffplay (no extension) on macOS.
# pyright: reportMissingImports=false

import os

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
)

# Same Silero VAD packaging note as the Windows specs: faster_whisper loads
# silero_vad_v6.onnx by file path at runtime, so PyInstaller's module
# collection alone is not enough.
_fw_datas, _fw_binaries, _fw_hidden = collect_all('faster_whisper')

# pywhispercpp ships its native whisper.cpp extension as a TOP-LEVEL module
# `_pywhispercpp` at site-packages root. collect_dynamic_libs returns [] for
# that layout — use collect_all on both names to gather module + binary +
# datas. All wrapped in try/except so a slim build host without the opt-in
# deps doesn't break the spec.
whisper_cpp_datas = []
whisper_cpp_binaries = []
whisper_cpp_hidden = []
for _name in ('pywhispercpp', '_pywhispercpp'):
    try:
        d, b, h = collect_all(_name)
        whisper_cpp_datas.extend(d)
        whisper_cpp_binaries.extend(b)
        whisper_cpp_hidden.extend(h)
    except Exception:
        pass
try:
    whisper_cpp_binaries.extend(collect_dynamic_libs('pywhispercpp'))
except Exception:
    pass

# stable-ts (alignment) — bring its data files + transitive whisper +
# tiktoken so the bundled app can run alignment when the user enables it.
alignment_datas = []
alignment_binaries = []
alignment_hidden = []
for _name in ('stable_whisper', 'whisper', 'tiktoken'):
    try:
        d, b, h = collect_all(_name)
        alignment_datas.extend(d)
        alignment_binaries.extend(b)
        alignment_hidden.extend(h)
    except Exception:
        pass

# This spec lives in platform/macos/pyinstaller/. PyInstaller resolves a bare
# relative script path (e.g. 'gui.py') against the SPEC's own directory, not the
# CWD — which made the build fail with "gui.py not found". Resolve every
# repo-relative input against the repo root computed from SPECPATH so the build
# works regardless of the working directory.
_REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir, os.pardir, os.pardir))

# Bundle version comes from core.__version__ (the single source of truth) so
# the Info.plist can no longer drift from the app (it was stuck at 1.6.0
# while core.__version__ had moved on to 1.8.0).
import re as _re
with open(os.path.join(_REPO_ROOT, 'core', '__init__.py'), encoding='utf-8') as _f:
    _VERSION = _re.search(r'__version__\s*=\s*"([^"]+)"', _f.read()).group(1)

# bin/ helpers. ffmpeg/ffprobe/ffplay must be SELF-CONTAINED builds (only
# /usr/lib + /System dylibs, e.g. evermeet.cx) — PyInstaller does not bundle
# the dylibs of executables it copies, so Homebrew's ffmpeg (18 dylibs under
# /opt/homebrew) breaks on every Mac without that exact Homebrew install.
# platform/macos/pyinstaller/fetch_mac_binaries.sh fetches + verifies them.
#
# yt-dlp is special: the official yt-dlp_macos is itself a PyInstaller
# onefile executable whose Python payload is appended to the Mach-O file.
# PyInstaller's Mach-O processing of collected binaries rewrites the file and
# drops that payload (bundled copy shrank 37 MB -> 73 KB and died with
# "Could not load PyInstaller's embedded PKG archive"). So yt-dlp is NOT
# collected here; it is copied byte-for-byte into the finished .app after
# BUNDLE (see the end of this file).
_BIN_DIR = os.path.join(_REPO_ROOT, 'bin')
_POST_COPY_BINS = ('yt-dlp',)
bin_datas = []
bin_binaries = []
if os.path.isdir(_BIN_DIR):
    for _entry in sorted(os.listdir(_BIN_DIR)):
        _src = os.path.join(_BIN_DIR, _entry)
        if _entry in _POST_COPY_BINS or _entry.endswith('.exe'):
            continue
        if os.path.isdir(_src):
            bin_datas.append((_src, os.path.join('bin', _entry)))
        elif os.access(_src, os.X_OK):
            bin_binaries.append((_src, 'bin'))
        else:
            bin_datas.append((_src, 'bin'))

# Dock icon — bundle assets/whisper.icns when present (see the README for how
# to generate it from whisper.png). None is fine; PyInstaller uses a default.
_icns = os.path.join(_REPO_ROOT, 'assets', 'whisper.icns')
_icon = _icns if os.path.isfile(_icns) else None

# Optional Google Cloud service-account key (gitignored — only present in a
# trusted local build tree, never in a source/CI checkout). Bundled under
# creds/ so core.backends.google_cloud_stt.bundled_credentials_path() finds
# it at <resource_base>/creds/gcloud_stt.json. Skipped cleanly when absent —
# the cloud backend just falls back to user-supplied credentials.
_creds_key = os.path.join(_REPO_ROOT, 'creds', 'gcloud_stt.json')
creds_datas = [(_creds_key, 'creds')] if os.path.isfile(_creds_key) else []

# google-cloud-speech + google-cloud-storage + grpcio are OPTIONAL — not in
# requirements.txt, not installed by default (see the comment above the
# now-removed pin in requirements.txt and SECURITY.md's "Retired: the
# bundled Google Cloud key"). They install on demand via
# core/optional_deps.py the first time a user picks their own
# service-account JSON, so a normal build environment usually will NOT have
# them. When they ARE present (e.g. a maintainer machine that installed them
# manually), collect_all gathers datas + binaries (the native grpc .so!) +
# every submodule of these namespace-package stacks, which PyInstaller's
# static analysis cannot fully discover on its own. The try/except below
# makes their absence a silent no-op, not a build failure.
_gcloud_datas, _gcloud_binaries, _gcloud_hidden = [], [], []
for _pkg in ('grpc', 'google.cloud.speech_v2', 'google.cloud.storage',
             'google.api_core', 'google.auth', 'google.oauth2',
             'google.protobuf', 'proto'):
    try:
        _d, _b, _h = collect_all(_pkg)
        _gcloud_datas += _d
        _gcloud_binaries += _b
        _gcloud_hidden += _h
    except Exception:
        pass

# numpy + its C-extension stack (ctranslate2, scipy, av, onnxruntime) ship
# native .so/.dylib files that PyInstaller's static analysis can miss,
# especially their dependent dylibs (e.g. numpy's bundled OpenBLAS, scipy's
# .libs). A macOS build that's missing these can launch (the GUI imports lazily)
# but fail later with "Importing the numpy C-extensions failed" on the user's
# machine. collect_all gathers datas + binaries + every submodule for each,
# same pattern as the google/grpc block above.
_npstack_datas, _npstack_binaries, _npstack_hidden = [], [], []
for _pkg in ('numpy', 'ctranslate2', 'scipy', 'av', 'onnxruntime'):
    try:
        _d, _b, _h = collect_all(_pkg)
        _npstack_datas += _d
        _npstack_binaries += _b
        _npstack_hidden += _h
    except Exception:
        pass

a = Analysis(
    [os.path.join(_REPO_ROOT, 'gui.py')],
    pathex=[_REPO_ROOT],
    binaries=[
        *bin_binaries,
        *_fw_binaries,
        *whisper_cpp_binaries,
        *alignment_binaries,
        *_gcloud_binaries,
        *_npstack_binaries,
    ],
    datas=[
        *bin_datas,
        (os.path.join(_REPO_ROOT, 'assets'), 'assets'),
        # Static page served by the optional LAN/web HTTP job server
        # (gui.py serve -> core.server). Ship it so the frozen build can
        # serve the browser UI.
        (os.path.join(_REPO_ROOT, 'core', 'server', 'static'), 'core/server/static'),
        # SMTV transcription writer's bundled Word template (the team's
        # exact table styling). Resolved at runtime via
        # core.paths.resource_base -> core/writers/templates/.
        (os.path.join(_REPO_ROOT, 'core', 'writers', 'templates'), 'core/writers/templates'),
        *_fw_datas,
        *whisper_cpp_datas,
        *alignment_datas,
        *creds_datas,
        *_gcloud_datas,
        *_npstack_datas,
    ],
    hiddenimports=[
        *_fw_hidden,
        *whisper_cpp_hidden,
        *alignment_hidden,
        *_gcloud_hidden,
        *_npstack_hidden,
        'google.cloud.speech_v2',
        'google.cloud.storage',
        'google.oauth2.service_account',
        'grpc',
        'grpc._cython.cygrpc',
        'app',
        'app.app',
        'app.dialogs',
        'app.domain',
        'app.services',
        'app.widgets',
        'app.observability',
        'app.dialogs.advanced',
        'app.dialogs.hub_setup',
        'app.dialogs.model_download',
        'app.dialogs.statistics',
        'app.dialogs.transcript_viewer',
        'app.dialogs.search_dialog',
        'app.domain.languages',
        'app.domain.tasks',
        'app.services.download_service',
        'app.services.format_service',
        'app.services.integrations_service',
        'app.services.live_service',
        'app.services.transcription_service',
        'app.widgets.console',
        'app.widgets.hardware_wizard',
        'app.widgets.platform',
        'app.widgets.live_tab',
        'app.widgets.tabs',
        'app.widgets.tray',
        'core',
        'core.alignment',
        'core.backends',
        'core.backends.base',
        'core.backends.faster_whisper_be',
        'core.backends.whisper_cpp',
        'core.backends.cloud_stt',
        'core.backends.google_cloud_stt',
        'core.backends.nvidia_asr',
        'core.backends.availability',
        'core.chapters',
        'core.llm',
        'core.recorder',
        'core.search',
        'core.denoise',
        'core.live',
        'core.separator',
        'core.tiling',
        'core.voiceprint',
        # Opt-in backends (see the Windows specs' comment).
        'pywhispercpp',
        'pywhispercpp.model',
        '_pywhispercpp',
        'stable_whisper',
        'whisper',
        'tiktoken',
        'core.burn_subs',
        'core.config',
        'core.convert',
        'core.diarization',
        'core.hallucination',
        'core.hardware',
        'core.history',
        'core.hub',
        'core.logging_setup',
        'core.model_manager',
        'core.monitors',
        'core.paths',
        'core.stats',
        'core.task',
        'core.transcriber',
        'core.updates',
        'core.watcher',
        'core.worker',
        'core.integrations.otranscribe',
        'core.integrations.smtv',
        # Optional LAN/web HTTP job server (stdlib only).
        'core.server',
        'core.server.httpd',
        'core.server.jobs',
        'core.writers',
        'core.writers.base',
        'core.writers.ass',
        'core.writers.srt',
        'core.writers.vtt',
        'core.writers.tsv',
        'core.writers.txt',
        'core.writers.json_writer',
        'core.writers.lrc',
        'core.writers.md',
        'core.writers.otr',
        'core.writers.elan',
        'core.writers.inqscribe',
        'core.writers.express_scribe',
        'core.writers.docx_writer',
        'core.writers.pdf_writer',
        'core.writers.smtv_docx_writer',
        'core.writers.bilingual_srt',
        'docx',
        'reportlab',
        'sherpa_onnx',
        # Optional multi-monitor detection for Video Tiling. Lazy-imported in
        # core.monitors; on macOS this is the PREFERRED path (the ctypes Win32
        # fallback is a no-op off Windows), so list it so the frozen .app keeps
        # working multi-monitor detection. Its absence only degrades to a
        # single-monitor fallback.
        'screeninfo',
    ],
    hookspath=[],
    # Diverts multiprocessing's resource-tracker helper re-launch (see file).
    runtime_hooks=[os.path.join(SPECPATH, 'rthook_mp_helpers.py')],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)


# ---- Real minimum macOS of what is being bundled ---------------------------
# Every wheel/binary carries its own minimum-OS (LC_BUILD_VERSION minos /
# LC_VERSION_MIN_MACOSX). MACOSX_DEPLOYMENT_TARGET does NOT lower those for
# prebuilt wheels, so e.g. onnxruntime 1.23.2 (the newest Intel wheel) needs
# macOS 13 no matter what the build sets. Compute the max over everything
# bundled and put THAT in LSMinimumSystemVersion, so the Info.plist never
# promises less than the bundle can deliver.
#
# WTS_MACOS_MIN overrides it — only for a value that was actually VERIFIED by
# running the built app on that macOS version (e.g. onnxruntime 1.19.2 is
# tagged 11.0 but was verified to work on 10.15).
def _macho_minos(path):
    try:
        from macholib.MachO import MachO
        from macholib import mach_o
        best = None
        for header in MachO(path).headers:
            for cmd in header.commands:
                if cmd[0].cmd == mach_o.LC_BUILD_VERSION:
                    v = cmd[1].minos
                elif cmd[0].cmd == mach_o.LC_VERSION_MIN_MACOSX:
                    v = cmd[1].version
                else:
                    continue
                t = ((v >> 16) & 0xFFFF, (v >> 8) & 0xFF)
                best = t if best is None or t > best else best
        return best
    except Exception:
        return None


_minos_files = [src for _dest, src, _kind in a.binaries] + [
    os.path.join(_BIN_DIR, n) for n in _POST_COPY_BINS
    if os.path.isfile(os.path.join(_BIN_DIR, n))
]
_minos_hits = {}
for _p in _minos_files:
    _v = _macho_minos(_p)
    if _v:
        _minos_hits.setdefault(_v, []).append(_p)
_computed_min = max(_minos_hits) if _minos_hits else (10, 13)
_computed_min = max(_computed_min, (10, 13))
_MIN_MACOS = os.environ.get('WTS_MACOS_MIN') or '%d.%d' % _computed_min
print('[mac-spec] highest bundled minos: %d.%d  <- %s' % (
    _computed_min + (', '.join(os.path.basename(p) for p in _minos_hits.get(_computed_min, [])),)))
print('[mac-spec] LSMinimumSystemVersion = %s%s' % (
    _MIN_MACOS, ' (WTS_MACOS_MIN override)' if os.environ.get('WTS_MACOS_MIN') else ''))

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Whisper Transcriber Suite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    # Build for the host arch by default. To ship one app for Intel + Apple
    # Silicon, build under a universal2 Python with universal2/fused wheels and
    # set WTS_TARGET_ARCH=universal2.
    target_arch=os.environ.get('WTS_TARGET_ARCH') or None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Whisper Transcriber Suite',
)
# macOS .app wrapper. CFBundleVersion / CFBundleShortVersionString come from
# core.__version__ (read at the top of this file), so they can't go stale.
# The install.command source/venv path writes its own Info.plist
# separately and is tracked independently.
app = BUNDLE(
    coll,
    name='Whisper Transcriber Suite.app',
    icon=_icon,
    bundle_identifier='com.translation-robot.whisperproject',
    version=_VERSION,
    info_plist={
        'CFBundleName': 'Whisper Transcriber Suite',
        'CFBundleDisplayName': 'Whisper Transcriber Suite',
        'CFBundleIdentifier': 'com.translation-robot.whisperproject',
        'CFBundleVersion': _VERSION,
        'CFBundleShortVersionString': _VERSION,
        'CFBundlePackageType': 'APPL',
        'NSHighResolutionCapable': True,
        # Computed above from the bundled binaries (or a verified
        # WTS_MACOS_MIN override). A value higher than the real minimum
        # blocks launch outright (LaunchServices error -10825); a lower one
        # lets the app start and then crash in dyld.
        'LSMinimumSystemVersion': _MIN_MACOS,
    },
)

# ---- Post-BUNDLE: byte-for-byte copy of self-contained PyInstaller tools -----
# (see the yt-dlp note near the top). Copy the original file, then re-seal the
# ad-hoc signature so the bundle still verifies (`codesign --verify --deep
# --strict`), and smoke-test that the copied tool actually runs.
import shutil as _shutil
import subprocess as _subprocess

_app_path = os.path.join(DISTPATH, 'Whisper Transcriber Suite.app')
_app_bin = os.path.join(_app_path, 'Contents', 'Frameworks', 'bin')
for _name in _POST_COPY_BINS:
    _src = os.path.join(_BIN_DIR, _name)
    if not os.path.isfile(_src):
        print('[mac-spec] WARNING: bin/%s missing — the .app will have no %s' % (_name, _name))
        continue
    os.makedirs(_app_bin, exist_ok=True)
    _dst = os.path.join(_app_bin, _name)
    _shutil.copy2(_src, _dst)
    os.chmod(_dst, 0o755)
    _subprocess.run(['codesign', '--force', '--sign', '-', _dst], check=True)
    _out = _subprocess.run([_dst, '--version'], capture_output=True, text=True, timeout=300)
    if _out.returncode != 0:
        raise SystemExit('[mac-spec] bundled %s does not run: %s' % (_name, _out.stderr.strip()))
    print('[mac-spec] bundled %s %s (%d bytes, copied verbatim)' % (
        _name, _out.stdout.strip(), os.path.getsize(_dst)))
if os.path.isdir(_app_bin):
    # Re-seal the outer bundle signature over the replaced nested code.
    _subprocess.run(['codesign', '--force', '--sign', '-', _app_path], check=True)
    _subprocess.run(['codesign', '--verify', '--deep', '--strict', _app_path], check=True)
