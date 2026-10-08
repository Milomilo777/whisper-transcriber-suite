"""Code-health invariants (added by the macOS QA session).

Tool-free, deterministic checks that catch real regression classes:
- core/ must stay Tk-free (it runs inside the headless worker subprocess).
- the shipped version stays consistent across its canonical Python sources.
- the two Windows PyInstaller specs keep identical app.*/core.* hidden-import sets
  (the project's documented bit-rot trap).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def test_core_stays_tk_free():
    """Importing the engine-layer core modules must NOT pull in tkinter — core
    runs in the headless worker subprocess where tkinter may be absent/unusable.
    Done in a fresh subprocess so the test runner's own tkinter import can't mask
    a real violation."""
    code = (
        "import sys\n"
        "import core, core.config, core.paths, core.hardware, core.convert, "
        "core.task, core.writers, core.history, core.hub, core._proc, core._checkpoint\n"
        "tk = sorted(m for m in sys.modules if m == 'tkinter' or m.startswith('tkinter.'))\n"
        "assert not tk, 'core transitively imported tkinter: %r' % tk\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, "core is not Tk-free:\n" + r.stdout + "\n" + r.stderr


def test_shipped_version_is_consistent():
    """pyproject.toml version must equal core.__version__ (the runtime source of
    truth). The project's 'version trap' is exactly these two drifting apart."""
    import core

    pyproject = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', pyproject)
    assert m, "no version found in pyproject.toml"
    assert m.group(1) == core.__version__, (
        f"version drift: pyproject={m.group(1)} core.__version__={core.__version__}"
    )


def _spec_module_tokens(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"""["']((?:app|core)\.[\w.]+)["']""", text))


def test_pyinstaller_specs_hiddenimports_in_sync():
    """The onefile and onedir Windows specs must carry identical app.*/core.*
    hidden-import sets so the unshipped pipelines don't bit-rot."""
    onefile = _REPO / "whisper_project_onefile.spec"
    onedir = _REPO / "whisper_project_onedir.spec"
    if not (onefile.exists() and onedir.exists()):
        pytest.skip("PyInstaller spec files not present in this checkout")
    a, b = _spec_module_tokens(onefile), _spec_module_tokens(onedir)
    assert a == b, (
        "spec hidden-import drift:\n"
        f"  only in onefile: {sorted(a - b)}\n"
        f"  only in onedir:  {sorted(b - a)}"
    )


_SPECS = (
    "whisper_project_onefile.spec",
    "whisper_project_onedir.spec",
    "platform/macos/pyinstaller/whisper_project_mac.spec",
)


def _source_modules(root: Path) -> set[str]:
    """Every app.* / core.* module of the source tree, packages included."""
    mods: set[str] = set()
    for top in ("app", "core"):
        for path in (root / top).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            parts = list(path.relative_to(root).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            mods.add(".".join(parts))
    return mods


def _spec_drift(spec_text: str, modules: set[str]) -> tuple[list[str], list[str]]:
    listed = set(re.findall(r"""["']((?:app|core)(?:\.[\w.]+)?)["']""", spec_text))
    return sorted(modules - listed), sorted(listed - modules)


@pytest.mark.parametrize("spec", _SPECS)
def test_spec_lists_every_app_and_core_module(spec):
    """AGENTS.md: a new module goes into the hidden imports of all three specs.
    The expected list is generated from the module tree, so a module added
    without a spec entry (or a deleted one still listed) fails here."""
    path = _REPO / spec
    if not path.exists():
        pytest.skip(f"{spec} not present in this checkout")
    missing, stale = _spec_drift(path.read_text(encoding="utf-8"), _source_modules(_REPO))
    assert not missing, f"{spec} lacks hidden imports: {missing}"
    assert not stale, f"{spec} lists modules that no longer exist: {stale}"


def test_spec_drift_detects_a_missing_module():
    text = "hiddenimports=['app', 'core', 'core.paths']"
    assert _spec_drift(text, {"app", "core", "core.paths", "core.new"}) == (["core.new"], [])
    assert _spec_drift(text, {"app", "core"}) == ([], ["core.paths"])


# Build inputs that decide what goes into a shipped package. A credential file
# (the retired shared Google Cloud key, or any other) must never be named in
# their active lines; comments explaining the ban are fine.
_CREDENTIAL = re.compile(
    r"""(?:^|[\\/'"\s%])creds(?:[\\/'"\s]|$)|gcloud_stt\.json|service[_-]?account[^\n]*\.json""",
    re.I,
)


def _active_lines(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if suffix == ".spec":
            s = s.split("#", 1)[0].strip()
        elif suffix == ".bat":
            if s.upper().startswith(("REM ", "::")) or s.upper() == "REM":
                continue
            # Only lines that copy something into the build tree count; the
            # guard that refuses a stray key file is allowed to name it.
            # (also "for ... do copy ..." loops)
            if not re.search(r"(?i)\b(x?copy|robocopy|move|mklink)\b", s):
                continue
        elif suffix == ".iss":
            if s.startswith(";") or not s.lower().startswith("source:"):
                continue
        if s:
            out.append(s)
    return out


def _credential_lines(path: Path) -> list[str]:
    return [s for s in _active_lines(path) if _CREDENTIAL.search(s)]


def test_no_build_input_bundles_a_credential_file():
    inputs = [*_SPECS, "build_embed_installer.bat", "installer.iss", "installer_embed.iss"]
    hits = {}
    for rel in inputs:
        path = _REPO / rel
        if path.exists():
            found = _credential_lines(path)
            if found:
                hits[rel] = found
    assert not hits, f"build inputs name a credential file: {hits}"


def test_credential_scan_catches_a_bundled_key(tmp_path):
    spec = tmp_path / "x.spec"
    spec.write_text(
        "# creds/gcloud_stt.json is not bundled (comment only)\n"
        "_k = os.path.join(_REPO_ROOT, 'creds', 'gcloud_stt.json')\n",
        encoding="utf-8",
    )
    assert _credential_lines(spec) == ["_k = os.path.join(_REPO_ROOT, 'creds', 'gcloud_stt.json')"]
    bat = tmp_path / "x.bat"
    bat.write_text(
        'REM never copy creds\\gcloud_stt.json\n'
        'if exist "%ROOT%creds\\gcloud_stt.json" echo refused\n'
        'copy "%ROOT%creds\\gcloud_stt.json" "%BUILD%\\creds\\"\n',
        encoding="utf-8",
    )
    assert len(_credential_lines(bat)) == 1
    iss = tmp_path / "x.iss"
    iss.write_text('Source: "creds\\gcloud_stt.json"; DestDir: "{app}\\creds"\n', encoding="utf-8")
    assert len(_credential_lines(iss)) == 1


def test_credential_scan_catches_a_whole_creds_folder(tmp_path):
    spec = tmp_path / "x.spec"
    spec.write_text("datas=[(os.path.join(R, 'creds'), 'creds')]\n", encoding="utf-8")
    assert len(_credential_lines(spec)) == 1
    bat = tmp_path / "x.bat"
    bat.write_text(
        'xcopy /E /I /Y "%ROOT%creds" "%BUILD%\\creds"\n'
        'for %%F in (a.json) do copy /Y "%ROOT%creds\\%%F" "%BUILD%\\"\n'
        'copy /Y "%ROOT%credits.txt" "%BUILD%\\"\n',
        encoding="utf-8",
    )
    assert len(_credential_lines(bat)) == 2
    iss = tmp_path / "x.iss"
    iss.write_text('Source: "creds\\*"; DestDir: "{app}"\n', encoding="utf-8")
    assert len(_credential_lines(iss)) == 1
