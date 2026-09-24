"""On-demand optional dependencies.

Heavy optional features — stable-ts word-alignment refinement and the
openai-whisper backend — pull in PyTorch (~700 MB), so they are NOT
bundled in the slim distribution. They are pip-installed on first use
into a user-writable directory that is added to ``sys.path``, mirroring
the on-demand Whisper-model download. This keeps the base install small
(~800 MB instead of ~1.5 GB) while every feature stays available.

The extras dir lives under the user's cache (writable without admin), so
this works for both the Program-Files install and the Portable build.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

from . import _proc
from .config import user_cache_dir

# Hard cap on a single on-demand pip install. A stalled PyPI / proxy
# black-hole would otherwise leave the reader loop (and the modal that
# waits on it) blocked forever with no way to abort.
DEFAULT_INSTALL_TIMEOUT_S = 1800.0

# Serialises on-demand installs: two transcribes that both need the
# same feature can fire near-simultaneously, and two `pip install
# --target` runs into the same dir race and can leave a half-written
# package tree. The lock makes the second caller wait, then short-
# circuit on the now-present package.
_install_lock = threading.Lock()

# feature key -> (import name to probe, [pip packages to install])
FEATURES: dict[str, tuple[str, list[str]]] = {
    "alignment": ("stable_whisper", ["stable-ts"]),      # pulls torch
    "whisper_backend": ("whisper", ["openai-whisper"]),  # pulls torch
    # REAL Google Cloud Speech-to-Text v2 backend. Pulls the google-cloud
    # client stack (grpc/protobuf/google-auth) — large enough to keep out
    # of the slim embed tree, so it installs on first use. The probe
    # import is the speech client package; google-cloud-storage is bundled
    # in the same install so the cheaper GCS batch mode works without a
    # second on-demand install.
    "google_cloud_stt": (
        "google.cloud.speech_v2",
        ["google-cloud-speech", "google-cloud-storage"],
    ),
    # Local NVIDIA Parakeet / FastConformer ASR backend via Hugging Face
    # transformers. Pulls torch + librosa (the ParakeetFeatureExtractor needs
    # librosa for its mel front-end). Hundreds of MB to GBs; like the other
    # torch-based features it is NOT bundled and installs on first use. The
    # probe import is the top-level transformers package.
    #
    # transformers is capped (not just floored) because its tokenizers
    # requirement must stay inside the tokenizers version pinned in
    # requirements.txt — that copy is bundled at BUILD time and always
    # shadows whatever this on-demand install puts in the pylibs dir (see
    # the requirements.txt comment above the tokenizers pin for why). An
    # unpinned "latest transformers" here would silently drift past that
    # bundled tokenizers' ceiling and break every fresh install. Verified
    # working pair as of 2026-08-12: transformers 5.15.0 + tokenizers
    # 0.22.0-0.23.0. Re-verify and bump both together before raising this.
    "nvidia_asr": ("transformers", ["transformers>=4.40,<=5.15.0", "torch", "librosa"]),
    # Clone Your Voice / Text to Voice (zero-shot voice cloning TTS).
    # OmniVoice (k2-fsa) pulls torch + its own weights (~2GB, downloaded
    # separately by the package itself on first model load, not by pip).
    # Apache-2.0 on both code and weights — chosen over other candidates
    # specifically for that clean license; see docs/SESSION_HANDOFF_NEXT.md
    # (2026-09-12 entry) for the full evaluation.
    "voice_clone": ("omnivoice", ["omnivoice", "torch", "soundfile"]),
    # NVIDIA cuBLAS for CUDA 12 -- the only CUDA runtime library CTranslate2
    # 4.6.3+ needs on top of the graphics driver (which does not ship it).
    # ~550 MB, so it is offered by the Hardware wizard's "Install GPU
    # support" button only when an NVIDIA GPU is present and this library is
    # the one thing missing (core.hardware.cuda_status). core.hardware finds
    # it under <extras>/nvidia/cublas/{bin,lib} and preloads it for
    # CTranslate2. 12.8+ is the first cuBLAS with native RTX 50-series
    # (Blackwell, sm_120) kernels (GitHub issue #7).
    "cuda_runtime": ("nvidia.cublas", ["nvidia-cublas-cu12>=12.8"]),
}


def _rm(path: str) -> None:
    """Best-effort remove a file or directory tree. Never raises."""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.lexists(path):
            os.unlink(path)
    except OSError:
        pass


def extras_dir() -> str:
    """User-writable dir where on-demand packages are installed."""
    return os.path.join(str(user_cache_dir()), "pylibs")


def activate() -> None:
    """Put the extras dir on sys.path so on-demand packages import.

    Idempotent; call once at startup and after a successful install.

    The extras dir is APPENDED, not prepended: any library that DOES ship
    bundled in the slim tree (python-docx, reportlab — google-cloud-speech
    used to be one of these before 2026-08-15, see the comment above the
    now-removed pin in requirements.txt) must win over a stale on-demand
    copy in the user pylibs cache. A previous prepend let a pylibs grpcio
    built for a different Python shadow a healthy bundled one and crash the
    import. Bundled wins when something is bundled; on-demand fills in
    whatever the slim tree doesn't ship (torch, google-cloud-speech, etc.).
    """
    d = extras_dir()
    if os.path.isdir(d) and d not in sys.path:
        sys.path.append(d)


def packages_for(feature: str) -> list[str]:
    return list(FEATURES.get(feature, ("", []))[1])


def is_available(feature: str) -> bool:
    """True iff the feature's top-level import resolves (bundled OR
    previously installed on-demand). Never raises."""
    activate()
    module = FEATURES.get(feature, ("", []))[0]
    if not module:
        return False
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:  # noqa: BLE001 — find_spec can raise on broken installs
        return False


def install(
    feature: str,
    log_cb: Callable[[str], None] | None = None,
    cancel_event: "threading.Event | None" = None,
    timeout: float = DEFAULT_INSTALL_TIMEOUT_S,
    force: bool = False,
) -> bool:
    """pip-install the feature's packages into the user extras dir.

    Streams pip output to ``log_cb``. Returns True only when the install
    completes AND the feature actually imports.

    Robustness (audit findings [10]/[11]):

    * pip installs into a TEMP staging dir on the same volume and is merged
      into the extras dir only on a clean exit, so a failed / cancelled /
      timed-out install never leaves a half-written package tree that
      ``is_available()`` (a cheap ``find_spec``) would report as present —
      which previously short-circuited the next install and then crashed
      the worker on the real import.
    * ``cancel_event`` and ``timeout`` bound the run: a stalled pip is
      terminated (and its staging tree removed) instead of blocking the
      waiting modal forever.
    """
    pkgs = packages_for(feature)
    if not pkgs:
        return False
    with _install_lock:
        # A concurrent caller may have installed it while we waited on
        # the lock — don't run a second redundant (and racing) pip.
        # When `force` is set, skip this short-circuit: a present-but-broken
        # cache (find_spec succeeds but the real import fails — e.g. a
        # grpcio .pyd built for another Python version) must be repaired,
        # not reported as already installed.
        if not force and is_available(feature):
            return True
        final_target = extras_dir()
        os.makedirs(final_target, exist_ok=True)
        parent = os.path.dirname(final_target) or None
        staging = tempfile.mkdtemp(prefix="pylibs-stage-", dir=parent)
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--target", staging, "--upgrade",
            *(["--force-reinstall", "--no-cache-dir"] if force else []),
            *pkgs,
        ]
        try:
            # Spawn with new_session_kwargs() (start_new_session=True on
            # POSIX so pip leads its own process group; CREATE_NO_WINDOW on
            # Windows) so the WHOLE pip tree — pip shells out to a build
            # backend / downloaders — can be reaped on cancel/timeout
            # instead of orphaning grandchildren that hold the staging dir
            # open and defeat the rmtree below.
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_proc.new_session_kwargs(),
            )
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(staging, ignore_errors=True)
            if log_cb:
                log_cb(f"Could not start pip: {e}")
            return False

        # Stream pip output on a daemon thread so the main thread can poll
        # for cancellation / timeout (a blocking readline can't be
        # interrupted, so we don't read inline).
        def _pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if line and log_cb:
                    log_cb(line)

        reader = threading.Thread(target=_pump, name=f"pip-{feature}", daemon=True)
        reader.start()

        deadline = (time.time() + timeout) if timeout else None
        aborted = False
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancel_event is not None and cancel_event.is_set():
                if log_cb:
                    log_cb("Install cancelled.")
                aborted = True
                break
            if deadline is not None and time.time() > deadline:
                if log_cb:
                    log_cb(f"Install timed out after {int(timeout)}s.")
                aborted = True
                break

        if aborted:
            # Reap the entire pip tree (build backend / downloader
            # grandchildren), not just the immediate pip process —
            # otherwise an orphan keeps the --target staging files open
            # and the rmtree below silently fails on Windows, leaking a
            # partial pylibs-stage-* dir.
            _proc.kill_process_tree(proc, force=False)
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                _proc.kill_process_tree(proc, force=True)
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    pass
            reader.join(timeout=2)
            shutil.rmtree(staging, ignore_errors=True)
            return False

        reader.join(timeout=5)
        if proc.returncode != 0:
            # Non-zero exit — discard the staging tree only; never touch
            # extras_dir (a sibling feature may already live there).
            shutil.rmtree(staging, ignore_errors=True)
            return False

        # Merge the freshly-installed tree into the extras dir top-level
        # entry by entry. A bare ``copytree(staging, final_target,
        # dirs_exist_ok=True)`` is NOT atomic: if it fails partway (disk
        # full, a locked .pyd already imported in the GUI, antivirus
        # lock) it leaves the top-level package dir + __init__.py written
        # but submodules missing. is_available()'s find_spec then sees
        # the half-tree, returns True, the next install() short-circuits,
        # and the real import crashes — exactly what staging was meant to
        # prevent. Instead: copy each top-level entry into a temp name on
        # the same volume and os.replace() it into place atomically; on
        # ANY failure, remove from final_target every top-level entry
        # that staging contributes, so no partial package is left behind.
        staged_names = os.listdir(staging)
        # Snapshot the top-level names already present BEFORE this merge so
        # rollback can tell apart entries THIS install creates from dirs a
        # sibling feature already installed. 'alignment' and
        # 'whisper_backend' both pull torch/numpy; if a later install's
        # torch/ merge fails (e.g. a locked .pyd), the rollback must NOT
        # delete the torch/numpy the already-installed feature still needs.
        pre_existing = set(os.listdir(final_target))
        merged_ok = True
        merge_err: Exception | None = None
        # Backups of live dst entries displaced this iteration, keyed by the
        # final dst path: name -> bak path. Each entry's replace is made
        # atomic w.r.t. an EXISTING dst by moving the live dst aside to a
        # .bak first, so a mid-loop os.replace failure (locked .pyd / AV /
        # disk-full) can be undone and never leaves a pre-existing shared
        # dir (e.g. torch/) destroyed with no restore path.
        backups: dict[str, str] = {}
        for name in staged_names:
            src = os.path.join(staging, name)
            dst = os.path.join(final_target, name)
            tmp = os.path.join(final_target, f".{name}.merge-{os.getpid()}")
            bak = os.path.join(final_target, f".{name}.bak-{os.getpid()}")
            try:
                if os.path.exists(tmp):
                    _rm(tmp)
                if os.path.lexists(bak):
                    _rm(bak)
                if os.path.isdir(src):
                    shutil.copytree(src, tmp)
                else:
                    shutil.copy2(src, tmp)
                # os.replace is atomic on the same volume for files and for
                # replacing a non-existent / file target. For an existing
                # destination DIRECTORY it would fail outright, and a plain
                # _rm(dst) before the replace is NON-atomic: if the replace
                # then fails (locked .pyd, AV, disk-full) the live dst — which
                # may be a torch/ a sibling feature still needs — is already
                # gone with no way back. Instead move the live dst aside to a
                # .bak FIRST, then replace; restore the .bak on any failure.
                displaced = False
                if os.path.lexists(dst):
                    os.replace(dst, bak)
                    backups[dst] = bak
                    displaced = True
                try:
                    os.replace(tmp, dst)
                except Exception:
                    # Replace failed — put the original dst back so the
                    # pre-existing entry is never left missing, then re-raise
                    # into the outer handler to roll the whole merge back.
                    if displaced:
                        os.replace(bak, dst)
                        backups.pop(dst, None)
                    raise
                # Success for this entry: the staged copy is in place and the
                # displaced original is now superseded — drop its backup.
                if displaced:
                    _rm(bak)
                    backups.pop(dst, None)
            except Exception as e:  # noqa: BLE001
                merged_ok = False
                merge_err = e
                _rm(tmp)
                break

        if not merged_ok:
            # Restore every still-displaced original (entries replaced earlier
            # in this loop before the failing one) so no pre-existing shared
            # dir is left missing after a partial merge.
            for d, b in backups.items():
                _rm(d)
                try:
                    os.replace(b, d)
                except OSError:
                    pass
            backups.clear()
            if log_cb:
                log_cb(f"Could not finalise install: {merge_err}")
            # Roll back: delete only the top-level entries THIS install
            # newly created, so is_available() cannot observe a partial
            # tree — but leave pre-existing shared dirs (e.g. torch/numpy a
            # sibling feature already installed) untouched, or rolling back
            # one feature's failed merge would silently break another.
            for name in staged_names:
                if name in pre_existing:
                    continue
                _rm(os.path.join(final_target, name))
            shutil.rmtree(staging, ignore_errors=True)
            return False
        shutil.rmtree(staging, ignore_errors=True)

        activate()
        # Verify the feature actually imports now (not just that a partial
        # top-level dir exists) before reporting success.
        importlib.invalidate_caches()
        return is_available(feature)
