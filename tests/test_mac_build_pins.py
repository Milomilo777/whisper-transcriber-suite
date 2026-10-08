"""The macOS build inputs are pinned like the Windows ones.

platform/macos/pyinstaller/fetch_mac_binaries.sh downloads every tool and model
at a fixed version and checks its SHA-256; yt-dlp, Deno and the diarization
models are the same versions and files as platform/windows/build-deps.json.
constraints-macos.txt pins numpy and PyInstaller. The spec bundles and mirrors
bin/diarization.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FETCH = ROOT / "platform" / "macos" / "pyinstaller" / "fetch_mac_binaries.sh"
CONSTRAINTS = ROOT / "platform" / "macos" / "pyinstaller" / "constraints-macos.txt"
SPEC = ROOT / "platform" / "macos" / "pyinstaller" / "whisper_project_mac.spec"


def _vars(text: str) -> dict[str, str]:
    return dict(re.findall(r'(?m)^([A-Z0-9_]+)="([^"]*)"$', text))


def _windows_pin(name: str) -> dict:
    deps = json.loads((ROOT / "platform" / "windows" / "build-deps.json").read_text(encoding="utf-8"))
    return next(d for d in deps["deps"] if d["name"] == name)


def _code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_no_download_follows_latest():
    code = _code(FETCH.read_text(encoding="utf-8"))
    assert "latest" not in code
    assert "getrelease" not in code


def test_every_pinned_url_has_a_sha256():
    v = _vars(FETCH.read_text(encoding="utf-8"))
    urls = [k for k in v if k.endswith("_URL")]
    assert len(urls) >= 6
    for key in urls:
        assert v[key].startswith("https://"), key
        assert re.fullmatch(r"[0-9a-f]{64}", v[key[: -len("_URL")] + "_SHA256"]), key
    for key in ("YTDLP_MACOS_ZIP_SHA256", "DENO_X86_64_SHA256", "DENO_AARCH64_SHA256"):
        assert re.fullmatch(r"[0-9a-f]{64}", v[key]), key


def test_every_download_is_checked():
    code = _code(FETCH.read_text(encoding="utf-8"))
    # Only the checked helper calls curl.
    assert code.count("curl ") == 1
    assert 'fetch_checked() {' in code and '[ "$got" = "$2" ]' in code
    # Written to a temp file and moved only after the hash check.
    helper = code[code.index("fetch_checked() {"):]
    helper = helper[: helper.index("\n}\n")]
    assert helper.index('[ "$got" = "$2" ]') < helper.index('mv -f "$part" "$3"')
    assert '-o "$part"' in helper


def test_ytdlp_and_deno_match_the_windows_pins():
    v = _vars(FETCH.read_text(encoding="utf-8"))
    assert v["YTDLP_VERSION"] == _windows_pin("yt-dlp")["version"]
    assert v["DENO_VERSION"] == _windows_pin("deno")["version"]


def test_diarization_models_match_the_windows_pins():
    text = FETCH.read_text(encoding="utf-8")
    v = _vars(text)
    for key, name, target in (
        ("DIAR_SEGMENTATION", "diarization-segmentation", "segmentation.onnx"),
        ("DIAR_EMBEDDING", "diarization-embedding", "embedding.onnx"),
    ):
        pin = _windows_pin(name)
        assert v[key + "_URL"] == pin["url"]
        assert v[key + "_SHA256"] == pin["sha256"]
        assert pin["files"][0]["to"] == "bin/diarization/" + target
        assert f'"$BIN/diarization/{target}"' in text


def test_ffplay_is_no_longer_fetched_or_required():
    code = _code(FETCH.read_text(encoding="utf-8"))
    assert "for t in ffmpeg ffprobe; do" in code
    assert 'rm -f "$BIN/ffplay"' in code
    spec = _code(SPEC.read_text(encoding="utf-8"))
    assert "ffplay" not in spec


def test_spec_requires_and_mirrors_the_diarization_folder():
    spec = _code(SPEC.read_text(encoding="utf-8"))
    assert "for _n in ('segmentation.onnx', 'embedding.onnx'):" in spec
    # Every folder in Frameworks/bin gets its Contents/MacOS/bin link, not only yt-dlp's.
    assert "_is_dir = os.path.isdir(_target)" in spec


def test_spec_ships_the_licence_and_the_notices():
    spec = _code(SPEC.read_text(encoding="utf-8"))
    assert "(os.path.join(_REPO_ROOT, 'LICENSE'), '.')" in spec
    assert "(os.path.join(_REPO_ROOT, 'THIRD_PARTY_NOTICES.md'), '.')" in spec


def test_constraints_pin_numpy_and_pyinstaller():
    pins = dict(
        re.findall(r"(?m)^([A-Za-z0-9_.-]+)==(\S+)$", CONSTRAINTS.read_text(encoding="utf-8"))
    )
    assert pins.get("numpy") == "1.26.4"
    assert re.fullmatch(r"\d+\.\d+\.\d+", pins.get("pyinstaller", ""))
    assert pins.get("onnxruntime") == "1.19.2"
