"""Tests for the "Open in Subtitle Edit" button: detection order, command line, hiding."""
from __future__ import annotations

import os
import subprocess
import sys
import types
from typing import Any

import pytest

from core import subtitle_edit as se

WIN = "win32"
EXE = se.EXE_NAME


def _files(*paths: str):
    present = set(paths)
    return lambda p: p in present


def _env(tmp: str = "C:\\PF") -> dict[str, str]:
    return {
        "ProgramFiles": f"{tmp}\\x64",
        "ProgramFiles(x86)": f"{tmp}\\x86",
        "LOCALAPPDATA": f"{tmp}\\Local",
    }


# -- support / hiding ----------------------------------------------------------------


def test_supported_only_on_windows() -> None:
    assert se.is_supported("win32") is True
    assert se.is_supported("darwin") is False
    assert se.is_supported("linux") is False


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_nothing_is_found_off_windows_even_with_a_valid_path(platform: str) -> None:
    found = se.find_subtitle_edit(
        "/opt/SubtitleEdit.exe", platform=platform,
        registry=lambda: ["/opt"], isfile=lambda _p: True,
    )
    assert found is None


# -- detection order -----------------------------------------------------------------


def test_user_path_wins_over_registry_and_program_files() -> None:
    env = _env()
    reg = "C:\\Reg\\SE"
    mine = "D:\\Portable\\SubtitleEdit.exe"
    found = se.find_subtitle_edit(
        mine, platform=WIN, registry=lambda: [reg], env=env,
        isfile=_files(mine, os.path.join(reg, EXE), os.path.join(env["ProgramFiles"], "Subtitle Edit", EXE)),
    )
    assert found == mine


def test_user_folder_is_accepted_as_well_as_the_exe() -> None:
    folder = "D:\\Portable\\SE"
    found = se.find_subtitle_edit(
        folder, platform=WIN, registry=lambda: [], env={},
        isfile=_files(os.path.join(folder, EXE)),
    )
    assert found == os.path.join(folder, EXE)


def test_registry_comes_before_program_files() -> None:
    env = _env()
    reg_exe = os.path.join("C:\\Reg\\SE", EXE)
    pf_exe = os.path.join(env["ProgramFiles"], "Subtitle Edit", EXE)
    found = se.find_subtitle_edit(
        "", platform=WIN, registry=lambda: ["C:\\Reg\\SE"], env=env,
        isfile=_files(reg_exe, pf_exe),
    )
    assert found == reg_exe


def test_program_files_used_when_registry_has_nothing() -> None:
    env = _env()
    pf_exe = os.path.join(env["ProgramFiles(x86)"], "Subtitle Edit", EXE)
    found = se.find_subtitle_edit(
        "", platform=WIN, registry=lambda: [], env=env, isfile=_files(pf_exe),
    )
    assert found == pf_exe


def test_registry_entry_pointing_at_a_missing_exe_falls_through() -> None:
    env = _env()
    pf_exe = os.path.join(env["ProgramFiles"], "Subtitle Edit", EXE)
    found = se.find_subtitle_edit(
        "", platform=WIN, registry=lambda: ["C:\\Gone"], env=env, isfile=_files(pf_exe),
    )
    assert found == pf_exe


def test_a_wrong_user_path_falls_back_to_detection() -> None:
    env = _env()
    pf_exe = os.path.join(env["ProgramFiles"], "Subtitle Edit", EXE)
    found = se.find_subtitle_edit(
        "D:\\nope\\SubtitleEdit.exe", platform=WIN, registry=lambda: [], env=env,
        isfile=_files(pf_exe),
    )
    assert found == pf_exe


def test_user_path_pointing_at_a_non_exe_is_ignored() -> None:
    notes = "D:\\Portable\\readme.txt"
    found = se.find_subtitle_edit(
        notes, platform=WIN, registry=lambda: [], env={}, isfile=_files(notes),
    )
    assert found is None


def test_registry_failure_does_not_hide_program_files() -> None:
    env = _env()
    pf_exe = os.path.join(env["LOCALAPPDATA"], "Programs", "Subtitle Edit", EXE)

    def boom() -> list[str]:
        raise OSError("registry unavailable")

    found = se.find_subtitle_edit(
        "", platform=WIN, registry=boom, env=env, isfile=_files(pf_exe),
    )
    assert found == pf_exe


def test_not_installed_returns_none() -> None:
    assert se.find_subtitle_edit(
        "", platform=WIN, registry=lambda: [], env=_env(), isfile=lambda _p: False,
    ) is None


def test_quoted_user_path_is_unquoted() -> None:
    mine = "D:\\My Tools\\SubtitleEdit.exe"
    found = se.find_subtitle_edit(
        f'"{mine}"', platform=WIN, registry=lambda: [], env={}, isfile=_files(mine),
    )
    assert found == mine


# -- registry reading ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value_name", "raw", "folder"),
    [
        ("InstallLocation", "C:\\Program Files\\Subtitle Edit\\", "C:\\Program Files\\Subtitle Edit\\"),
        ("DisplayIcon", "C:\\Program Files\\Subtitle Edit\\SubtitleEdit.exe,0",
         "C:\\Program Files\\Subtitle Edit"),
        ("UninstallString", '"C:\\Program Files\\Subtitle Edit\\unins000.exe" /SILENT',
         "C:\\Program Files\\Subtitle Edit"),
        ("DisplayIcon", '"D:\\Tools\\SE\\SubtitleEdit.exe"', "D:\\Tools\\SE"),
    ],
)
def test_registry_value_to_folder(value_name: str, raw: str, folder: str) -> None:
    assert os.path.normpath(se._folder_from_registry_value(raw, value_name)) == os.path.normpath(folder)


class _FakeKey:
    def __init__(self, tree: dict[str, Any]) -> None:
        self.tree = tree

    def __enter__(self) -> "_FakeKey":
        return self

    def __exit__(self, *_a: object) -> None:
        return None


def _fake_winreg(uninstall: dict[str, dict[str, str]]) -> types.ModuleType:
    mod = types.ModuleType("winreg")
    mod.HKEY_LOCAL_MACHINE = "HKLM"  # type: ignore[attr-defined]
    mod.HKEY_CURRENT_USER = "HKCU"  # type: ignore[attr-defined]
    mod.KEY_READ = 1  # type: ignore[attr-defined]
    mod.KEY_WOW64_64KEY = 0x100  # type: ignore[attr-defined]
    mod.KEY_WOW64_32KEY = 0x200  # type: ignore[attr-defined]

    def open_key(parent: Any, name: str, _res: int = 0, access: int = 0) -> _FakeKey:
        if isinstance(parent, str):  # a hive: only HKLM 64-bit view holds the entries
            if parent == "HKLM" and access & 0x100:
                return _FakeKey(uninstall)
            raise OSError("no such key")
        if name not in parent.tree:
            raise OSError("no such key")
        return _FakeKey(parent.tree[name])

    def enum_key(key: _FakeKey, index: int) -> str:
        names = list(key.tree)
        if index >= len(names):
            raise OSError("no more")
        return names[index]

    def query(key: _FakeKey, name: str) -> tuple[str, int]:
        if name not in key.tree:
            raise OSError("no value")
        return key.tree[name], 1

    mod.OpenKey = open_key  # type: ignore[attr-defined]
    mod.EnumKey = enum_key  # type: ignore[attr-defined]
    mod.QueryValueEx = query  # type: ignore[attr-defined]
    return mod


def test_registry_install_dirs_reads_matching_entries_only(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_winreg({
        "Other App": {"DisplayName": "Other App", "InstallLocation": "C:\\Other"},
        "Subtitle Edit_is1": {
            "DisplayName": "Subtitle Edit 4.0.8",
            "InstallLocation": "C:\\Program Files\\Subtitle Edit\\",
            "DisplayIcon": "C:\\Program Files\\Subtitle Edit\\SubtitleEdit.exe,0",
        },
        "NoName": {"InstallLocation": "C:\\Nameless"},
    })
    monkeypatch.setitem(sys.modules, "winreg", fake)
    dirs = [os.path.normpath(d) for d in se.registry_install_dirs()]
    assert os.path.normpath("C:\\Program Files\\Subtitle Edit") in dirs
    assert os.path.normpath("C:\\Other") not in dirs
    assert os.path.normpath("C:\\Nameless") not in dirs


def test_registry_install_dirs_is_empty_when_registry_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "winreg", None)  # import raises ImportError
    assert se.registry_install_dirs() == []


def test_real_registry_read_does_not_crash() -> None:
    result = se.registry_install_dirs()
    assert isinstance(result, list)


# -- picking the file ----------------------------------------------------------------


def test_srt_is_preferred_over_other_subtitle_formats() -> None:
    paths = ["a.txt", "a.docx", "a.vtt", "a.ass", "a.srt", "a.json"]
    assert se.pick_subtitle_file(paths) == "a.srt"
    assert se.pick_subtitle_file(["a.ass", "a.vtt"]) == "a.vtt"
    assert se.pick_subtitle_file(["A.SRT"]) == "A.SRT"


def test_no_subtitle_file_gives_none() -> None:
    assert se.pick_subtitle_file(["a.txt", "a.json", "a.docx"]) is None
    assert se.pick_subtitle_file([]) is None


def test_sibling_candidates_follow_the_json_name() -> None:
    cands = se.sibling_subtitle_candidates("C:\\clips\\talk.json")
    assert cands[0] == "C:\\clips\\talk.srt"
    assert set(os.path.splitext(c)[1] for c in cands) == set(se.SUBTITLE_EXTENSIONS)


# -- command line --------------------------------------------------------------------


NASTY = "Talk نمونه – résumé 日本語 (1).srt"


def test_command_is_a_list_so_windows_quotes_each_argument() -> None:
    exe = "C:\\Program Files\\Subtitle Edit\\SubtitleEdit.exe"
    sub = "C:\\My Videos\\" + NASTY
    cmd = se.build_command(exe, sub)
    assert cmd == [exe, sub]
    line = subprocess.list2cmdline(cmd)
    assert line.startswith('"C:\\Program Files\\Subtitle Edit\\SubtitleEdit.exe" ')
    assert line.endswith(f'"{sub}"')


def test_path_with_spaces_and_non_latin_letters_reaches_the_program_intact(tmp_path) -> None:
    """A stand-in "program" (this Python) receives the real subtitle path as its argument."""
    folder = tmp_path / "My Videos نمونه"
    folder.mkdir()
    marker = tmp_path / "marker.txt"
    sub = folder / NASTY
    # Python runs the "subtitle" as a script, so the argument reaching it is observable.
    sub.write_text(
        "import sys\n"
        f"open({str(marker)!r}, 'w', encoding='utf-8').write(__file__)\n",
        encoding="utf-8",
    )
    procs: list[Any] = []

    def popen(cmd: list[str], **kw: Any) -> Any:
        p = subprocess.Popen(cmd, **kw)
        procs.append(p)
        return p

    se.open_in_subtitle_edit(sys.executable, str(sub), popen=popen)
    assert procs[0].wait(timeout=60) == 0
    assert marker.read_text(encoding="utf-8") == str(sub)


def test_open_refuses_a_missing_subtitle_file(tmp_path) -> None:
    called: list[Any] = []
    with pytest.raises(FileNotFoundError):
        se.open_in_subtitle_edit(
            "x.exe", str(tmp_path / "gone.srt"), popen=lambda *a, **k: called.append(a),
        )
    assert called == []


def test_open_does_not_use_a_shell(tmp_path) -> None:
    sub = tmp_path / "a.srt"
    sub.write_text("1\n", encoding="utf-8")
    seen: dict[str, Any] = {}

    def popen(cmd: list[str], **kw: Any) -> None:
        seen["cmd"], seen["kw"] = cmd, kw

    se.open_in_subtitle_edit("C:\\SE\\SubtitleEdit.exe", str(sub), popen=popen)
    assert seen["cmd"] == ["C:\\SE\\SubtitleEdit.exe", str(sub)]
    assert not seen["kw"].get("shell")


# -- config --------------------------------------------------------------------------


def test_config_key_is_local_only_with_an_empty_default() -> None:
    from core.config import DEFAULT_CONFIG, LOCAL_ONLY_KEYS, ONLINE_ALLOWED_KEYS

    assert DEFAULT_CONFIG[se.CONFIG_KEY] == ""
    assert se.CONFIG_KEY in LOCAL_ONLY_KEYS
    assert se.CONFIG_KEY not in ONLINE_ALLOWED_KEYS
