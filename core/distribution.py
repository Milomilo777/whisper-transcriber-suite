"""Baked Store policy and per-package writable paths.

The build marker is packaging metadata, not proof that runtime policy was tested.
Environment variables cannot turn the Store restrictions off. Importing this
module has no side effects; the Store runtime hook calls :func:`bootstrap`.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

_MARKER = "STORE_BUILD.json"
_RESTRICTED_FEATURES = frozenset({"self_update", "media_download", "dynamic_runtime"})
_ENVIRONMENT_SUBDIRS = {
    "TEMP": "temp",
    "TMP": "temp",
    "TMPDIR": "temp",
    "HF_HOME": "cache/huggingface",
    "HUGGINGFACE_HUB_CACHE": "cache/huggingface/hub",
    "HF_HUB_CACHE": "cache/huggingface/hub",
    "TORCH_HOME": "cache/torch",
    "XDG_CACHE_HOME": "cache",
}


class StoreBuildError(RuntimeError):
    """The Store build cannot establish its required runtime configuration."""


class StoreFeatureUnavailable(RuntimeError):
    """A feature is excluded from the Microsoft Store distribution."""


def _store_metadata() -> dict[str, object] | None:
    """Read only a frozen build's bundled marker, rejecting invalid metadata."""
    if not getattr(sys, "frozen", False):
        return None
    resource_root = getattr(sys, "_MEIPASS", None)
    if not resource_root:
        return None
    marker = Path(resource_root) / _MARKER
    try:
        raw = marker.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise StoreBuildError("Cannot read Store build metadata.") from exc
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise StoreBuildError("Invalid Store build metadata.") from exc
    if not (
        isinstance(value, dict)
        and type(value.get("schema")) is int
        and value.get("schema") == 1
        and value.get("variant") == "microsoft-store"
        and value.get("runtime_guards") is True
        and value.get("download_policy") in ("retain", "omit")
    ):
        raise StoreBuildError("Unsupported Store build metadata.")
    return value


def is_store_build() -> bool:
    """Whether the frozen build contains valid Microsoft Store metadata."""
    return _store_metadata() is not None


def media_download_enabled() -> bool:
    """Respect the baked download policy; direct builds retain downloading."""
    metadata = _store_metadata()
    return metadata is None or metadata["download_policy"] == "retain"


def require_feature(feature: str) -> None:
    """Refuse excluded features even when called outside their normal UI."""
    if feature not in _RESTRICTED_FEATURES:
        raise ValueError(f"Unknown distribution feature: {feature}")
    metadata = _store_metadata()
    if metadata is not None and not (
        feature == "media_download" and metadata["download_policy"] == "retain"
    ):
        raise StoreFeatureUnavailable(
            f"The Microsoft Store build does not support {feature.replace('_', ' ')}."
        )


def _package_family_name() -> str:
    """Obtain process identity from Windows, never from the environment."""
    if sys.platform != "win32":
        raise StoreBuildError("Store package identity requires Windows.")
    # Adapted from Microsoft (https://learn.microsoft.com/windows/win32/api/appmodel/nf-appmodel-getcurrentpackagefamilyname)
    # — query the buffer size before reading the current process package family.
    get_name = ctypes.WinDLL("kernel32", use_last_error=True).GetCurrentPackageFamilyName
    get_name.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p]
    get_name.restype = ctypes.c_long
    length = ctypes.c_uint32()
    result = get_name(ctypes.byref(length), None)
    if result != 122 or not 1 < length.value <= 256:
        raise StoreBuildError("Store package identity is unavailable.")
    buffer = ctypes.create_unicode_buffer(length.value)
    if get_name(ctypes.byref(length), buffer) != 0:
        raise StoreBuildError("Cannot read Store package identity.")
    return buffer.value


def _local_app_data() -> Path:
    """Resolve Windows LocalAppData without accepting a redirected env value."""
    if sys.platform != "win32":
        raise StoreBuildError("Store data paths require Windows.")
    # Adapted from Microsoft (https://learn.microsoft.com/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath)
    # — the returned known-folder string is freed with CoTaskMemFree.
    class _Guid(ctypes.Structure):
        _fields_ = [
            ("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
            ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8),
        ]

    folder_id = _Guid.from_buffer_copy(
        uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le
    )
    get_folder = ctypes.WinDLL("shell32").SHGetKnownFolderPath
    get_folder.argtypes = [ctypes.POINTER(_Guid), ctypes.c_uint32,
                           ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    get_folder.restype = ctypes.c_long
    result = ctypes.c_wchar_p()
    if get_folder(ctypes.byref(folder_id), 0, None, ctypes.byref(result)) != 0:
        raise StoreBuildError("Cannot resolve Windows LocalAppData.")
    try:
        if not result.value:
            raise StoreBuildError("Windows LocalAppData is unavailable.")
        return Path(result.value)
    finally:
        free = ctypes.WinDLL("ole32").CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        free(ctypes.cast(result, ctypes.c_void_p))


def store_profile_root() -> Path:
    """Return the OS-identified package's LocalState directory."""
    family = _package_family_name()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*_[A-Za-z0-9]+", family):
        raise StoreBuildError("Invalid Store package family name.")
    local = _local_app_data()
    if not local.is_absolute():
        raise StoreBuildError("Windows LocalAppData must be absolute.")
    return local / "Packages" / family / "LocalState"


def bootstrap() -> Path | None:
    """Route Store profile, temp and library caches before application imports.

    Source and direct-download builds retain their existing environment. A Store
    build without OS package identity fails before changing any environment.
    """
    if not is_store_build():
        return None
    root = store_profile_root()
    paths = {name: root / subdir for name, subdir in _ENVIRONMENT_SUBDIRS.items()}
    for path in set(paths.values()):
        path.mkdir(parents=True, exist_ok=True)
    os.environ["WTS_PROFILE_DIR"] = str(root)
    for name, path in paths.items():
        os.environ[name] = str(path)
    # tempfile may have cached the old directory in an earlier runtime hook.
    tempfile.tempdir = str(root / "temp")
    return root
