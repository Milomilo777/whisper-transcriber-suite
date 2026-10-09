"""tools/check_embed_tree.py: the PE import reader and the embed-tree check the Windows build runs.

The PE files here are built byte by byte, so the tests run on every OS; one test also reads a real
Windows DLL when run on Windows (and compares with pefile when that package is installed).
"""
from __future__ import annotations

import importlib.util
import os
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("check_embed_tree", ROOT / "tools" / "check_embed_tree.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_embed_tree"] = mod
    spec.loader.exec_module(mod)
    return mod


cet = _load()

_SECTION_RVA = 0x1000
_SECTION_RAW = 0x400
_IMAGE_BASE = 0x180000000


def make_pe(imports=(), delay=(), *, pe32plus: bool = True, delay_rva: bool = True) -> bytes:
    """A minimal PE image whose only content is an import table and a delay-load table."""
    imports, delay = list(imports), list(delay)
    imp_size = 20 * (len(imports) + 1) if imports else 0
    del_size = 32 * (len(delay) + 1) if delay else 0
    names = bytearray()
    imp_name_rva, del_name_rva = [], []
    base = _SECTION_RVA + imp_size + del_size
    for dll in imports:
        imp_name_rva.append(base + len(names))
        names += dll.encode("ascii") + b"\0"
    for dll in delay:
        del_name_rva.append(base + len(names))
        names += dll.encode("ascii") + b"\0"
    body = bytearray()
    for rva in imp_name_rva:
        body += struct.pack("<IIIII", 0x2000, 0, 0, rva, 0x3000)
    if imports:
        body += bytes(20)
    for rva in del_name_rva:
        if delay_rva:
            body += struct.pack("<II", 1, rva) + bytes(24)
        else:
            body += struct.pack("<II", 0, _IMAGE_BASE + rva if pe32plus else 0x10000000 + rva) + bytes(24)
    if delay:
        body += bytes(32)
    body += names
    n_dirs = 16
    dirs = bytearray(8 * n_dirs)
    if imports:
        struct.pack_into("<II", dirs, 8 * 1, _SECTION_RVA, imp_size)
    if delay:
        struct.pack_into("<II", dirs, 8 * 13, _SECTION_RVA + imp_size, del_size)
    if pe32plus:   # standard + Windows-specific fields: 112 bytes, then the data directories
        opt = bytearray(112)
        struct.pack_into("<H", opt, 0, 0x20B)
        struct.pack_into("<Q", opt, 24, _IMAGE_BASE)
        struct.pack_into("<I", opt, 108, n_dirs)
    else:          # 96 bytes
        opt = bytearray(96)
        struct.pack_into("<H", opt, 0, 0x10B)
        struct.pack_into("<I", opt, 28, 0x10000000)
        struct.pack_into("<I", opt, 92, n_dirs)
    opt_size = len(opt) + len(dirs)
    coff = struct.pack("<HHIIIHH", 0x8664 if pe32plus else 0x14C, 1, 0, 0, 0, opt_size, 0x2022)
    section = struct.pack("<8sIIIIIIHHI", b".idata", len(body), _SECTION_RVA, len(body), _SECTION_RAW,
                          0, 0, 0, 0, 0x40000040)
    dos = bytearray(0x40)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    image = bytes(dos) + b"PE\0\0" + coff + bytes(opt) + bytes(dirs) + section
    return image.ljust(_SECTION_RAW, b"\0") + bytes(body)


def put(root: Path, rel: str, data: bytes = b"") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ------------------------------------------------------------------ the reader

@pytest.mark.parametrize("pe32plus", [True, False])
def test_reader_lists_load_time_and_delay_load_imports_in_lower_case(pe32plus):
    data = make_pe(["KERNEL32.dll", "MSVCP140.dll"], ["Dbghelp.DLL"], pe32plus=pe32plus)
    assert cet.pe_imports(data) == ["kernel32.dll", "msvcp140.dll", "dbghelp.dll"]


def test_reader_handles_old_style_delay_load_virtual_addresses():
    data = make_pe([], ["old.dll"], pe32plus=False, delay_rva=False)
    assert cet.pe_imports(data) == ["old.dll"]


def test_reader_returns_nothing_for_an_image_without_imports():
    assert cet.pe_imports(make_pe()) == []


@pytest.mark.parametrize("data", [
    b"", b"MZ", b"not a pe file at all" * 20,
    b"MZ" + bytes(0x3A) + struct.pack("<I", 0x40) + b"XX\0\0" + bytes(100),
])
def test_reader_rejects_something_that_is_not_a_pe_file(data):
    with pytest.raises(cet.PEError):
        cet.pe_imports(data)


def test_reader_rejects_a_truncated_image():
    data = make_pe(["kernel32.dll"])
    for cut in (0x30, 0x50, 0x120, _SECTION_RAW - 1, _SECTION_RAW + 5):
        with pytest.raises(cet.PEError):
            cet.pe_imports(data[:cut])


@pytest.mark.skipif(sys.platform != "win32", reason="reads a real Windows DLL")
def test_reader_on_real_windows_binaries():
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    kernel32 = system32 / "kernel32.dll"
    if not kernel32.is_file():
        pytest.skip("no kernel32.dll")
    imports = cet.pe_imports(kernel32.read_bytes())
    assert "ntdll.dll" in imports
    assert any(n.startswith("api-ms-win-") for n in imports)
    pefile = pytest.importorskip("pefile")
    for dll in sorted(system32.glob("*.dll"))[:150]:
        try:
            pe = pefile.PE(str(dll), fast_load=True)
        except pefile.PEFormatError:
            continue
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        expected = [e.dll.decode().lower() for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                    for e in getattr(pe, attr, [])]
        pe.close()
        try:
            got = cet.pe_imports(dll.read_bytes())
        except cet.PEError:
            continue
        assert got == expected, dll.name


# ------------------------------------------------------------------ the tree check

def _tree(tmp_path: Path) -> Path:
    """A clean tree: python.exe + runtime, an extension module that needs msvcp140, app/ and core/."""
    root = tmp_path / "embed_build"
    put(root, "python/python.exe", make_pe(["KERNEL32.dll", "VCRUNTIME140.dll", "api-ms-win-crt-runtime-l1-1-0.dll"]))
    put(root, "python/vcruntime140.dll", make_pe(["KERNEL32.dll"]))
    put(root, "python/msvcp140.dll", make_pe(["KERNEL32.dll", "VCRUNTIME140.dll"]))
    put(root, "Lib/site-packages/pkg/ext.pyd", make_pe(["KERNEL32.dll", "MSVCP140.dll", "helper.dll"]))
    put(root, "Lib/site-packages/pkg/helper.dll", make_pe(["USER32.dll", "ext-ms-win-ntuser-window-l1-1-0.dll"]))
    put(root, "app/__init__.py", b"")
    put(root, "core/__init__.py", b"")
    return root


def test_clean_tree_passes(tmp_path):
    assert cet.check_tree(_tree(tmp_path)) == []


def test_missing_vc_runtime_dll_is_reported_with_the_importer(tmp_path):
    root = _tree(tmp_path)
    (root / "python" / "msvcp140.dll").unlink()  # negative control: the failure the trial build had
    problems = cet.check_tree(root)
    assert len(problems) == 1
    assert "Lib/site-packages/pkg/ext.pyd" in problems[0] and "msvcp140.dll" in problems[0]


def test_vc_runtime_dll_must_be_in_the_python_folder_or_next_to_the_importer(tmp_path):
    root = _tree(tmp_path)
    (root / "python" / "msvcp140.dll").unlink()
    # In the tree, but somewhere neither searched for the importer nor next to it: still a failure.
    put(root, "somewhere/else/msvcp140.dll", make_pe(["KERNEL32.dll"]))
    assert any("msvcp140.dll" in p for p in cet.check_tree(root))
    # Next to the importer is fine (a package that carries its own copy).
    put(root, "Lib/site-packages/pkg/msvcp140.dll", make_pe(["KERNEL32.dll"]))
    assert cet.check_tree(root) == []


def test_every_member_of_the_vc_runtime_family_is_covered(tmp_path):
    root = _tree(tmp_path)
    names = ["msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll", "vcomp140.dll", "vcruntime140_1.dll",
             "msvcp140_atomic_wait.dll", "vccorlib140.dll"]
    put(root, "Lib/site-packages/pkg/more.pyd", make_pe(["KERNEL32.dll"] + [n.upper() for n in names]))
    problems = cet.check_tree(root)
    assert len(problems) == len(names)
    for n in names:
        assert any(n in p for p in problems), n
    for n in names:
        put(root, f"python/{n}", make_pe(["KERNEL32.dll"]))
    assert cet.check_tree(root) == []


def test_unknown_dll_neither_in_the_tree_nor_in_windows_is_reported(tmp_path):
    root = _tree(tmp_path)
    put(root, "Lib/site-packages/pkg/ext2.pyd", make_pe(["KERNEL32.dll", "libomp140.x86_64.dll"]))
    problems = cet.check_tree(root)
    assert len(problems) == 1 and "libomp140.x86_64.dll" in problems[0]
    put(root, "Lib/site-packages/pkg/libomp140.x86_64.dll", make_pe(["KERNEL32.dll"]))
    assert cet.check_tree(root) == []


def test_delay_loaded_imports_are_checked_too(tmp_path):
    root = _tree(tmp_path)
    put(root, "bin/tool.exe", make_pe(["KERNEL32.dll"], ["ghost.dll"]))
    problems = cet.check_tree(root)
    assert len(problems) == 1 and "bin/tool.exe" in problems[0] and "ghost.dll" in problems[0]


def test_a_dll_name_is_not_satisfied_by_an_exe_of_that_name(tmp_path):
    root = _tree(tmp_path)
    put(root, "Lib/site-packages/pkg/ext3.pyd", make_pe(["tool.dll"]))
    put(root, "bin/tool.exe", make_pe(["KERNEL32.dll"]))
    assert any("tool.dll" in p for p in cet.check_tree(root))


def test_unreadable_binary_is_a_problem_not_a_crash(tmp_path):
    root = _tree(tmp_path)
    put(root, "Lib/site-packages/pkg/broken.pyd", b"this is not a PE file")
    problems = cet.check_tree(root)
    assert len(problems) == 1 and "broken.pyd" in problems[0]


@pytest.mark.parametrize("rel", ["app/__pycache__/x.cpython-314.pyc", "core/server/__pycache__/y.cpython-311.pyc",
                                 "core/backends/__pycache__"])
def test_bytecode_folders_in_app_and_core_are_rejected(tmp_path, rel):
    root = _tree(tmp_path)
    if rel.endswith("__pycache__"):
        (root / rel).mkdir(parents=True)
    else:
        put(root, rel, b"\0")
    problems = cet.check_tree(root)
    assert len(problems) >= 1 and all("__pycache__" in p for p in problems)


def test_stray_pyc_in_app_is_rejected_but_bytecode_elsewhere_is_fine(tmp_path):
    root = _tree(tmp_path)
    put(root, "python/Lib/__pycache__/os.cpython-311.pyc", b"\0")
    put(root, "Lib/site-packages/pkg/__pycache__/m.cpython-311.pyc", b"\0")
    assert cet.check_tree(root) == []
    put(root, "core/old.pyc", b"\0")
    problems = cet.check_tree(root)
    assert len(problems) == 1 and "core/old.pyc" in problems[0]


def test_missing_app_or_core_folder_is_reported(tmp_path):
    root = _tree(tmp_path)
    (root / "app" / "__init__.py").unlink()
    (root / "app").rmdir()
    assert any(p.startswith("app/") for p in cet.check_tree(root))


def test_main_exit_codes(tmp_path, capsys):
    root = _tree(tmp_path)
    assert cet.main([str(root)]) == 0
    assert "ok" in capsys.readouterr().out
    (root / "python" / "msvcp140.dll").unlink()
    assert cet.main([str(root)]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert cet.main([str(tmp_path / "nope")]) == 2


def test_the_inno_setup_uninstaller_in_the_install_dir_passes(tmp_path):
    """CI runs the check on the installed copy, where Inno Setup puts unins000.exe; it imports
    windowscodecs.dll (in Windows 10) next to the usual system DLLs."""
    root = _tree(tmp_path)
    put(root, "unins000.exe", make_pe(["KERNEL32.dll", "USER32.dll", "windowscodecs.dll", "SHFOLDER.dll"]))
    assert cet.check_tree(root) == []


def test_system_dll_list_never_contains_the_visual_cpp_runtime():
    """The runtime ships with the redistributable, not with Windows 10: it must stay out."""
    for name in cet.WINDOWS_SYSTEM_DLLS:
        assert not cet._VC_RUNTIME.match(name), name
        assert name == name.lower() and not name.endswith(".dll")
