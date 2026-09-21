"""Engine picker registry + cheap availability probes.

Single source of truth shared by the Transcribe-tab engine picker and the
Advanced dialog's backend combobox, so the two never drift. Also resolves the
*effective default* engine: cloud STT only when the user has configured their
own service-account JSON, otherwise fully offline on faster-whisper. No build
ships a credential any more — see :func:`default_engine` and ``SECURITY.md``.

Pure: no Tkinter, no network. The import-based runtime probes are cheap when a
dependency is missing (ImportError fires immediately) but can be slow when a
heavy native lib IS installed, so GUI callers should compute cloud-engine
statuses lazily (on selection / dialog open) rather than eagerly at every
startup — see the ``deep`` flag on :func:`engine_status`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .._gc_import_guard import gc_disabled_import

# (friendly label, transcribe_backend value) — also the display order. Offline
# engines stay first; the two cloud options spell out their auth model so a
# non-technical user can tell them apart (a pasted key vs a downloaded file).
ENGINE_CHOICES: list[tuple[str, str]] = [
    ("Faster-Whisper — offline, default", "faster_whisper"),
    ("whisper.cpp — offline, low-end CPUs", "whisper_cpp"),
    ("Gemini cloud — simple API key", "cloud_stt"),
    (
        "Google Cloud Speech-to-Text — service account (60 min/mo free)",
        "google_cloud_stt",
    ),
    (
        "NVIDIA Parakeet TDT v3 — local, multilingual (transformers)",
        "nvidia_asr",
    ),
]
LABEL_TO_VALUE: dict[str, str] = {label: value for label, value in ENGINE_CHOICES}
VALUE_TO_LABEL: dict[str, str] = {value: label for label, value in ENGINE_CHOICES}
KNOWN_ENGINES: frozenset[str] = frozenset(value for _label, value in ENGINE_CHOICES)

# Where get_backend() lands when a stored value is unknown/empty.
FALLBACK_ENGINE = "faster_whisper"


def normalise_engine(value: Any) -> str:
    """Map any stored/raw backend value to a known engine, else the fallback."""
    name = str(value or "").strip().lower()
    return name if name in KNOWN_ENGINES else FALLBACK_ENGINE


# --------------------------------------------------------------- credentials


def bundled_gcloud_key_path() -> str:
    """Path to a build-bundled Google Cloud key, or ``""`` — no google libs."""
    try:
        from .google_cloud_stt import bundled_credentials_path

        return bundled_credentials_path()
    except Exception:  # noqa: BLE001
        return ""


def gcloud_key_path(cfg: Mapping[str, Any]) -> str:
    """The credentials path Google Cloud STT would actually use.

    The user-selected JSON if it is set and present on disk, else the
    build-bundled key, else ``""``. Pure filesystem checks — no google libs.
    """
    explicit = str(cfg.get("gcloud_stt_credentials_json") or "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    return bundled_gcloud_key_path()


def has_gcloud_key(cfg: Mapping[str, Any]) -> bool:
    """True iff Google Cloud STT has a usable service-account key available."""
    return bool(gcloud_key_path(cfg))


def default_engine(cfg: Mapping[str, Any] | None = None) -> str:
    """The engine to use when the user has not chosen one.

    Cloud STT is the default ONLY when the user has configured their own
    service-account JSON. A key merely sitting next to the app is explicitly
    NOT enough: builds used to bundle a maintainer-owned key, and honouring it
    here meant a fresh install silently transcribed through one shared cloud
    account nobody opted into. That bundling is removed and revoked (see
    ``SECURITY.md``); this function stays deliberately blind to it so
    re-introducing a key file can never flip anyone's default again.

    Everything else stays offline on faster-whisper.
    """
    explicit = str((cfg or {}).get("gcloud_stt_credentials_json") or "").strip()
    if explicit and os.path.isfile(explicit):
        return "google_cloud_stt"
    return FALLBACK_ENGINE


# --------------------------------------------------------------- availability


@dataclass(frozen=True)
class EngineStatus:
    """Whether one engine can transcribe right now.

    ``ready``   — usable immediately with the current config/install.
    ``detail``  — short human note: the blocking reason when not ready, or an
                  informational hint (e.g. a pending download) when ready.
    ``blocked`` — when not ready, True iff the engine stays unusable until
                  the USER does something (paste an API key, install a
                  package with no on-demand installer). False means the gap
                  resolves automatically on first use (model download,
                  on-demand pip install), so it is a setup wait, not a dead
                  end. The pickers mark only blocked engines as unavailable;
                  both classes still show their reason inline.
    """

    value: str
    ready: bool
    detail: str = ""
    blocked: bool = False


def _faster_whisper_model_present(cfg: Mapping[str, Any]) -> bool:
    """Mirror App._model_bytes_present without importing the heavy backend."""
    try:
        from pathlib import Path

        from core.hub import default_hub_folder, model_folder_for

        mp = str(cfg.get("model_path") or "").strip()
        if mp and Path(mp).exists():
            return True
        model_info = cfg.get("model") or {}
        name = ""
        if isinstance(model_info, dict):
            name = str(model_info.get("name") or "").strip()
        if not name:
            name = str(cfg.get("whisper_model") or "").strip()
        if not name:
            name = "faster-whisper-large-v3"
        hub = str(cfg.get("hub_folder") or "").strip() or str(default_hub_folder())
        return model_folder_for(hub, name).exists()
    except Exception:  # noqa: BLE001
        return False


def _faster_whisper_status(cfg: Mapping[str, Any]) -> EngineStatus:
    """Cheap status: model presence only — no heavy import (startup-safe)."""
    present = _faster_whisper_model_present(cfg)
    detail = "" if present else "model downloads on first run (~3 GB)"
    return EngineStatus("faster_whisper", True, detail)


def _faster_whisper_status_deep(cfg: Mapping[str, Any]) -> EngineStatus:
    """Honest readiness: the model must already be on disk AND the
    ``faster_whisper`` package must import cleanly.

    Unlike the cheap probe (which always reports ``ready=True`` because the
    model can download on first run), the deep probe is meant to answer
    "can I transcribe right now, with no extra wait/setup" — so a
    not-yet-downloaded model is reported as NOT ready.
    """
    try:
        import faster_whisper  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return EngineStatus(
            "faster_whisper",
            False,
            f"faster-whisper not installed ({e})",
            blocked=True,
        )
    if not _faster_whisper_model_present(cfg):
        return EngineStatus("faster_whisper", False, "Model not downloaded yet")
    return EngineStatus("faster_whisper", True, "")


def _whisper_cpp_status(cfg: Mapping[str, Any]) -> EngineStatus:
    try:
        from . import whisper_cpp

        if whisper_cpp.is_available():
            return EngineStatus("whisper_cpp", True, "")
        return EngineStatus(
            "whisper_cpp", False, whisper_cpp.availability_reason(), blocked=True
        )
    except Exception as e:  # noqa: BLE001
        return EngineStatus("whisper_cpp", False, str(e) or "unavailable", blocked=True)


def _cloud_stt_status(cfg: Mapping[str, Any]) -> EngineStatus:
    if str(cfg.get("cloud_stt_api_key") or "").strip():
        return EngineStatus("cloud_stt", True, "")
    return EngineStatus(
        "cloud_stt",
        False,
        "paste a Gemini API key in Advanced settings",
        blocked=True,
    )


def _import_transformers() -> None:
    """Isolated so tests can monkeypatch the real-import step directly
    instead of fighting sys.modules / import machinery.

    ``transformers``/``torch`` is a heavy C-extension package -- see
    core/_gc_import_guard.py for why the import runs under a shared,
    process-wide GC-disable guard.
    """
    with gc_disabled_import():
        import transformers  # type: ignore  # noqa: F401


def _nvidia_asr_status(cfg: Mapping[str, Any]) -> EngineStatus:
    # Local transformers backend: ready once the transformers package is
    # importable (it pulls torch). Both install on first use, so a fresh
    # checkout reports "installs on first use" rather than a hard failure.
    # The model itself downloads on first run (like faster-whisper).
    #
    # find_spec only proves the package's files are ON DISK — it does NOT
    # catch a tokenizers/transformers version clash (find_spec succeeds,
    # then "import transformers" itself raises from transformers' own
    # internal dependency_versions_check). So once find_spec says present,
    # actually try the import too — same honest-probe pattern as
    # _faster_whisper_status_deep, and it is what lets this clash show up
    # in the status line BEFORE the user starts a transcription.
    import importlib.util

    try:
        have = importlib.util.find_spec("transformers") is not None
    except Exception:  # noqa: BLE001 — find_spec can raise on broken installs
        have = False
    if not have:
        return EngineStatus(
            "nvidia_asr",
            False,
            "transformers + torch install on first use",
        )
    try:
        _import_transformers()
    except Exception as e:  # noqa: BLE001
        from .nvidia_asr import friendly_load_error

        # find_spec said the package is present, so the on-demand installer
        # short-circuits and would skip it — a broken install needs the user
        # (or a repair reinstall), not just a retry.
        return EngineStatus(
            "nvidia_asr", False, friendly_load_error(e), blocked=True
        )
    return EngineStatus("nvidia_asr", True, "")


def _google_cloud_stt_status(cfg: Mapping[str, Any]) -> EngineStatus:
    have_key = has_gcloud_key(cfg)
    try:
        from . import google_cloud_stt as gcs

        runtime = gcs.runtime_available()
    except Exception:  # noqa: BLE001
        runtime = False
    if not runtime:
        return EngineStatus(
            "google_cloud_stt",
            False,
            "Google Cloud client not installed (installs on first use)",
        )
    if not have_key:
        return EngineStatus(
            "google_cloud_stt",
            False,
            "add a service-account JSON in Advanced settings",
            blocked=True,
        )
    return EngineStatus("google_cloud_stt", True, "")


_PROBES: dict[str, Callable[[Mapping[str, Any]], EngineStatus]] = {
    "faster_whisper": _faster_whisper_status_deep,
    "whisper_cpp": _whisper_cpp_status,
    "cloud_stt": _cloud_stt_status,
    "google_cloud_stt": _google_cloud_stt_status,
    "nvidia_asr": _nvidia_asr_status,
}


def engine_status(value: Any, cfg: Mapping[str, Any], *, deep: bool = True) -> EngineStatus:
    """Readiness of one engine.

    ``deep=True`` runs the honest import-based probes (used by the Advanced
    dialog + tests). ``deep=False`` is the cheap path for the always-on
    Transcribe-tab status line: it does NO heavy import at startup — cloud
    readiness keys off the credential, offline whisper.cpp is assumed
    present (a run surfaces any gap), faster-whisper keeps its
    filesystem check.
    """
    engine = normalise_engine(value)
    if not deep:
        if engine == "google_cloud_stt":
            if has_gcloud_key(cfg):
                return EngineStatus(engine, True, "")
            return EngineStatus(
                engine,
                False,
                "add a service-account JSON in Advanced settings",
                blocked=True,
            )
        if engine == "cloud_stt":
            return _cloud_stt_status(cfg)
        if engine == "faster_whisper":
            return _faster_whisper_status(cfg)
        return EngineStatus(engine, True, "")
    probe = _PROBES.get(engine)
    return probe(cfg) if probe else EngineStatus(engine, True, "")


def engine_statuses(cfg: Mapping[str, Any]) -> dict[str, EngineStatus]:
    """Deep status of every engine, keyed by backend value (for tests/audits)."""
    return {value: _PROBES[value](cfg) for _label, value in ENGINE_CHOICES}


# ------------------------------------------------------- picker presentation
#
# Shared by the Transcribe tab's Engine dropdown and the Advanced dialog's
# Engine combobox so the two render readiness identically and can never drift
# (the same reason ENGINE_CHOICES lives here). A ``ttk.Combobox`` cannot grey
# out one entry while leaving the others live, so an entry that cannot run
# until the user acts is marked in its label text instead, and every caller
# maps the (possibly marked) label back to the engine value through
# :func:`engine_value_for_label`.

#: Suffix a picker entry gets while that engine is blocked. Chosen over a
#: leading marker so labels still alphabetise/read naturally.
UNAVAILABLE_MARK = "  ⚠ unavailable"


@dataclass(frozen=True)
class EngineOption:
    """One engine as the pickers need it: stable label + live readiness."""

    value: str
    label: str
    ready: bool
    blocked: bool
    reason: str

    @property
    def display_label(self) -> str:
        """The combobox label — plain, or marked while blocked."""
        return f"{self.label}{UNAVAILABLE_MARK}" if self.blocked else self.label


def engine_options(
    cfg: Mapping[str, Any],
    *,
    deep: bool = False,
    statuses: Mapping[str, EngineStatus] | None = None,
) -> list[EngineOption]:
    """Every engine + readiness, in ENGINE_CHOICES display order.

    ``deep=False`` (the default) runs only the cheap probes, so it is safe
    to call on the Tk main thread. ``statuses`` lets a caller overlay
    already-computed results (e.g. cached deep probes) instead of paying for
    them again.
    """
    override = statuses or {}
    options: list[EngineOption] = []
    for label, value in ENGINE_CHOICES:
        st = override.get(value) or engine_status(value, cfg, deep=deep)
        options.append(
            EngineOption(
                value=value,
                label=label,
                ready=st.ready,
                blocked=st.blocked,
                reason="" if st.ready else (st.detail or "unavailable"),
            )
        )
    return options


def engine_value_for_label(label: Any) -> str | None:
    """Map a picker label — plain OR :data:`UNAVAILABLE_MARK`-suffixed — to
    its engine value.

    Returns ``None`` for anything unknown so callers can fall back
    explicitly (e.g. to ``FALLBACK_ENGINE``) instead of silently guessing.
    """
    text = str(label or "").strip()
    if text.endswith(UNAVAILABLE_MARK):
        text = text[: -len(UNAVAILABLE_MARK)].rstrip()
    return LABEL_TO_VALUE.get(text)


def format_engine_status(
    st: EngineStatus, *, action_hint: str = "(set up in Advanced settings…)"
) -> str:
    """One-line human status text for an :class:`EngineStatus`.

    Shared by the Transcribe tab's status label and the Advanced dialog's
    warning row so the two surfaces word the same state the same way. Only
    a *blocked* engine gets the "go set it up" pointer; an engine that
    resolves itself on first use (model download, on-demand install) says
    what is pending without sending the user on a chase.
    """
    if st.ready:
        return "✓ Ready" + (f" — {st.detail}" if st.detail else "")
    if st.blocked:
        hint = f"  {action_hint}" if action_hint else ""
        return f"⚠ {st.detail or 'unavailable'}{hint}"
    return f"⚠ {st.detail or 'not ready yet'}"


def engine_status_summary(
    cfg: Mapping[str, Any],
    *,
    deep: bool = False,
    statuses: Mapping[str, EngineStatus] | None = None,
) -> str:
    """Multi-line hover text: what each engine's readiness is right now."""
    lines = ["Engine readiness on this machine:"]
    for opt in engine_options(cfg, deep=deep, statuses=statuses):
        if opt.ready:
            lines.append(f"• {opt.label}: ready")
        else:
            lines.append(f"• {opt.label}: {opt.reason}")
    return "\n".join(lines)
