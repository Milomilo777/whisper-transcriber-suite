# Delegate the maintained ONEDIR build; keep all normal dependency collection.
# pyright: reportUndefinedVariable=false
import json as _store_json
import os as _store_os
from pathlib import Path as _StorePath
import sys as _store_sys

if _store_sys.platform != "win32":
    raise ValueError("The Store payload must be built on Windows")

_store_spec_path = SPECPATH
_store_root = _StorePath(SPECPATH).resolve().parents[2]
_store_marker_value = _store_os.environ.get("WTS_STORE_MARKER_PATH", "")
if not _store_marker_value:
    raise ValueError("WTS_STORE_MARKER_PATH must name the explicit Store build marker")
_store_marker = _StorePath(_store_marker_value).resolve(strict=True)
_store_policy = _store_json.loads(_store_marker.read_text(encoding="utf-8"))
if (not isinstance(_store_policy, dict) or type(_store_policy.get("schema")) is not int
        or _store_policy.get("schema") != 1 or _store_policy.get("variant") != "microsoft-store"
        or _store_policy.get("runtime_guards") is not True
        or _store_policy.get("download_policy") not in {"retain", "omit"}):
    raise ValueError("Invalid Store build marker")
if _store_policy["download_policy"] == "omit":
    raise ValueError("Download-omitting application guards are not wired; only retain builds are available")
_store_hook = _store_root / "platform/windows/store/runtime_hook.py"
if not _store_hook.is_file() or not (_store_root / "core/distribution.py").is_file():
    raise ValueError("Store runtime hook and distribution policy module are required")
_store_notices = [_store_root / "LICENSE", _store_root / "THIRD_PARTY_NOTICES.md"]
for _store_notice in _store_notices:
    if not _store_notice.is_file():
        raise ValueError(f"Required standalone-package notice is missing: {_store_notice.name}")
_store_original_analysis = Analysis
_store_original_exe = EXE


def _store_absolute(value):
    path = _StorePath(value)
    return str(path if path.is_absolute() else _store_root / path)


def Analysis(*args, **kwargs):
    # PyInstaller's internal specpath remains this wrapper directory, so make
    # root-spec relative inputs explicit rather than relying only on cwd.
    args = ([_store_absolute(path) for path in args[0]], *args[1:])
    kwargs["pathex"] = [_store_absolute(path) for path in kwargs.get("pathex", [])] + [str(_store_root)]
    kwargs["datas"] = [(_store_absolute(source), target) for source, target in kwargs.get("datas", [])]
    kwargs["datas"].append((str(_store_marker), "."))
    kwargs["datas"].extend((str(path), ".") for path in _store_notices)
    import importlib.util
    if importlib.util.find_spec("onnxruntime") is not None:
        from PyInstaller.utils.hooks import collect_data_files
        notices = collect_data_files("onnxruntime", includes=["LICENSE", "ThirdPartyNotices.txt"])
        if len(notices) != 2 or {_StorePath(source).name for source, _ in notices} != {"LICENSE", "ThirdPartyNotices.txt"}:
            raise ValueError("Required ONNX Runtime license notices are missing")
        kwargs["datas"].extend(notices)
    kwargs["binaries"] = [(_store_absolute(source), target) for source, target in kwargs.get("binaries", [])]
    kwargs["hookspath"] = [_store_absolute(path) for path in kwargs.get("hookspath", [])]
    kwargs["hiddenimports"] = list(dict.fromkeys([*kwargs.get("hiddenimports", []), "core.distribution"]))
    kwargs["runtime_hooks"] = list(dict.fromkeys([*[_store_absolute(path) for path in kwargs.get("runtime_hooks", [])], str(_store_hook)]))
    result = _store_original_analysis(*args, **kwargs)
    # python-docx loads templates/default.docx at runtime. Its unpacked source
    # template is unused there and contains MSIX-reserved OPC relationship paths.
    # Filter after Analysis because the built-in docx hook adds these data files.
    _unused_docx_source = "docx/templates/default-docx-template/"
    # Diarization loads the extracted ONNX models, not this download cache.
    _unused_diarization_download = "bin/diarization/segmentation.tar.bz2"
    result.datas[:] = [entry for entry in result.datas
                      if not entry[0].replace("\\", "/").casefold().startswith(_unused_docx_source)
                      and entry[0].replace("\\", "/").casefold() != _unused_diarization_download]
    return result


def EXE(*args, **kwargs):
    if kwargs.get("manifest") is not None:
        raise ValueError("Store EXE cannot replace an explicit caller manifest")
    # Compose PyInstaller's default metadata; match the existing runtime DPI request.
    from PyInstaller.utils.win32.winmanifest import create_application_manifest
    import xml.dom.minidom

    with xml.dom.minidom.parseString(create_application_manifest()) as manifest:
        settings, = manifest.getElementsByTagNameNS("urn:schemas-microsoft-com:asm.v3", "windowsSettings")
        for name, year, value in (("dpiAware", "2005", "true/pm"),
                                  ("dpiAwareness", "2016", "PerMonitorV2, PerMonitor")):
            namespace = f"http://schemas.microsoft.com/SMI/{year}/WindowsSettings"
            element = manifest.createElementNS(namespace, name)
            element.setAttribute("xmlns", namespace)
            element.appendChild(manifest.createTextNode(value))
            settings.appendChild(element)
        kwargs["manifest"] = manifest.toxml()
    return _store_original_exe(*args, **kwargs)


_store_cwd = _StorePath.cwd()
try:
    _store_os.chdir(_store_root)
    SPECPATH = str(_store_root)
    _store_base_spec = _store_root / "whisper_project_onedir.spec"
    exec(compile(_store_base_spec.read_text(encoding="utf-8-sig"), str(_store_base_spec), "exec"), globals())
finally:
    _store_os.chdir(_store_cwd)
    SPECPATH = _store_spec_path
    Analysis = _store_original_analysis
    EXE = _store_original_exe
