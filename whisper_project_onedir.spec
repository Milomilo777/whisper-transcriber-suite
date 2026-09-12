# whisper_project_onedir.spec — onedir build for the installer pipeline.
#
# Run:
#     pyinstaller --noconfirm --clean --distpath dist_onedir whisper_project_onedir.spec
#
# Output: dist_onedir/WhisperTranscriberSuite/WhisperTranscriberSuite.exe + sibling files.
#
# This spec exists alongside whisper_project.spec (onefile) so the
# installer (Inno Setup) can package the directory layout without the
# bootloader extraction cost of onefile. Method A ships the onefile
# exe; Method B ships an installer built on top of this onedir tree.
#
# The app's core.paths.resource_base() falls through to
# dirname(sys.executable) when sys._MEIPASS is unset, which is exactly
# what onedir frozen layout requires — no source changes needed.
# pyright: reportMissingImports=false

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
)

# Same Silero VAD packaging note as whisper_project.spec: faster_whisper
# loads silero_vad_v6.onnx by file path at runtime, so PyInstaller's
# module collection alone is not enough.
faster_whisper_datas = collect_data_files('faster_whisper')

# pywhispercpp ships its native whisper.cpp .pyd as a TOP-LEVEL module
# `_pywhispercpp` at site-packages root. collect_dynamic_libs returns
# [] for that layout — use collect_all on both names to gather the
# module + binary + datas.
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
# tiktoken so the bundled exe can actually run alignment when the
# user enables it.
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

# NO credentials are bundled. This used to ship a maintainer-owned Google
# Cloud service-account key at creds/gcloud_stt.json inside the package —
# one shared credential handed to everyone who downloaded a build, billed to
# the maintainer's project. The key is revoked and the bundling is removed
# for good; cloud STT now requires the user's OWN service-account JSON.
# See SECURITY.md. Do not re-add a credential entry to `datas`.
creds_datas = []

# google-cloud-speech + google-cloud-storage + grpcio are OPTIONAL — not in
# requirements.txt, not installed by default (see the comment above the
# now-removed pin in requirements.txt and SECURITY.md's "Retired: the
# bundled Google Cloud key"). They install on demand via
# core/optional_deps.py the first time a user picks their own
# service-account JSON, so a normal build environment usually will NOT have
# them. When they ARE present (e.g. a maintainer machine that installed them
# manually), collect_all gathers datas + binaries (the native grpc .pyd!) +
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

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[
        *whisper_cpp_binaries,
        *alignment_binaries,
        *_gcloud_binaries,
    ],
    datas=[
        ('bin', 'bin'),
        ('assets', 'assets'),
        # Static page served by the optional LAN/web HTTP job server
        # (gui.py serve -> core.server). Ship it so the frozen build can
        # serve the browser UI.
        ('core/server/static', 'core/server/static'),
        # SMTV transcription writer's bundled Word template (the team's
        # exact table styling). Resolved at runtime via
        # core.paths.resource_base -> core/writers/templates/.
        ('core/writers/templates', 'core/writers/templates'),
        *faster_whisper_datas,
        *whisper_cpp_datas,
        *alignment_datas,
        *creds_datas,
        *_gcloud_datas,
    ],
    hiddenimports=[
        *whisper_cpp_hidden,
        *alignment_hidden,
        *_gcloud_hidden,
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
        'app.services.voice_clone_service',
        'app.widgets.console',
        'app.widgets.hardware_wizard',
        'app.widgets.platform',
        'app.widgets.live_tab',
        'app.widgets.tabs',
        'app.widgets.tray',
        'app.widgets.voice_clone_tab',
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
        'core.voice_clone',
        'core.voice_clone_worker',
        # Opt-in backends (see onefile spec comment).
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
        'core.writers.docx_writer',
        'core.writers.pdf_writer',
        'core.writers.smtv_docx_writer',
        'core.writers.bilingual_srt',
        'core.writers.elan',
        'core.writers.inqscribe',
        'core.writers.express_scribe',
        'docx',
        'reportlab',
        'sherpa_onnx',
        # Optional multi-monitor detection for Video Tiling. Lazy-imported in
        # core.monitors with a ctypes Win32 fallback, so PyInstaller can't see
        # it via static analysis — list it so the frozen build keeps the
        # screeninfo path. Its absence only disables that one detection path.
        'screeninfo',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WhisperTranscriberSuite',
    console=False,
    icon=None,
    # Flatten the bundle so bin/ and DLLs sit beside the exe rather than
    # under _internal/. core.paths.resource_base() resolves the bundled
    # bin/ from dirname(sys.executable) in onedir mode.
    contents_directory='.',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='WhisperTranscriberSuite',
)
