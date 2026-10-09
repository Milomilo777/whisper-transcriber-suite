"""requirements.txt (what the installers ship), pyproject.toml (what `pip install .` pulls) and
platform/macos/pyinstaller/constraints-macos.txt (what the Mac build pins) must agree, and carry
the floors that close published security advisories. Reads the files only; no network."""
from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
MAC_CONSTRAINTS = ROOT / "platform" / "macos" / "pyinstaller" / "constraints-macos.txt"


def _requirements(path: Path) -> dict[str, Requirement]:
    out: dict[str, Requirement] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        req = Requirement(line)
        out[canonicalize_name(req.name)] = req
    return out


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _pyproject_runtime() -> dict[str, Requirement]:
    reqs = (Requirement(r) for r in _pyproject()["project"]["dependencies"])
    return {canonicalize_name(r.name): r for r in reqs}


def _floor(req: Requirement) -> Version:
    lows = [Version(s.version) for s in req.specifier if s.operator in (">=", "==", "~=")]
    assert lows, f"{req.name} has no lower bound"
    return max(lows)


def test_pillow_floor_excludes_the_versions_with_published_advisories():
    # smtv_tab.py decodes image bytes fetched from a remote site; osv.dev lists 35 advisories
    # against the old 10.0 floor, the newest of them fixed in 12.3.0.
    for reqs in (_requirements(ROOT / "requirements.txt"), _pyproject_runtime()):
        assert _floor(reqs["pillow"]) >= Version("12.3.0")


def test_numpy_is_declared_because_the_app_imports_it_directly():
    for name, reqs in (("requirements.txt", _requirements(ROOT / "requirements.txt")),
                       ("pyproject.toml", _pyproject_runtime())):
        assert "numpy" in reqs, f"{name} does not declare numpy"
        spec = reqs["numpy"].specifier
        assert spec.contains("1.26.4"), "the macOS build pins numpy 1.26.4"
        assert spec.contains("2.4.6"), "the Windows build installs numpy 2.x"
        assert not spec.contains("3.0.0"), "keep a major-version ceiling"


def test_pyproject_runtime_dependencies_match_requirements_txt():
    req = _requirements(ROOT / "requirements.txt")
    proj = _pyproject_runtime()
    assert sorted(proj) == sorted(req)
    for name in req:
        assert str(proj[name].specifier) == str(req[name].specifier), name


def test_macos_pins_satisfy_the_shared_requirements():
    req = _requirements(ROOT / "requirements.txt")
    for name, pin in _requirements(MAC_CONSTRAINTS).items():
        if name in req and str(pin.specifier).startswith("=="):
            version = str(pin.specifier)[2:]
            assert req[name].specifier.contains(version), f"{name}=={version} breaks requirements.txt"


def test_pywhispercpp_stays_installable_as_an_extra_for_the_mac_which_skips_it():
    # build_mac.sh / install.command filter pywhispercpp out of requirements.txt (no Intel wheel),
    # so pyproject must not force it onto macOS but still offer it as an extra.
    marker = _pyproject_runtime()["pywhispercpp"].marker
    assert marker is not None
    assert not marker.evaluate({"sys_platform": "darwin"})
    assert marker.evaluate({"sys_platform": "win32"}) and marker.evaluate({"sys_platform": "linux"})
    extras = _pyproject()["project"]["optional-dependencies"]
    assert any(canonicalize_name(Requirement(r).name) == "pywhispercpp" for r in extras["backend_cpp"])

