"""Fail the Windows build when the embed tree cannot start on a clean Windows 10 PC.

build_embed_installer.bat runs this on embed_build\\ (the tree the installer and the Portable ZIP
are made from). It reads the import table of every .dll / .pyd / .exe in the tree, with a small
reader for the PE file format (standard library only, so the build needs no extra package), and
reports:

  * an imported DLL that is not in the tree, not an API-set name (api-ms-win-*, ext-ms-win-*)
    and not on the list of DLLs every Windows 10 install has. Such a DLL loads on a developer PC
    that has some other program's copy and fails on a clean one.
  * a Visual C++ runtime DLL (msvcp140*, vcruntime140*, concrt140, vcomp140, ...) that is neither
    in python\\ (the folder of python.exe, searched first for every extension module and for
    the DLLs it pulls in) nor next to the binary that imports it;
  * a __pycache__ folder or a .pyc file under app\\ or core\\ (build-machine bytecode; the app
    runs on a different CPython than the one that wrote it).

Usage (Python 3.10+):  python tools/check_embed_tree.py <embed tree> [--app-dir python]
Exit code 0 when clean, 1 when a problem is printed, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

BINARY_SUFFIXES = (".dll", ".pyd", ".exe")

# DLLs that ship with every Windows 10 installation (client SKUs, 1809 and later). A DLL on this
# list is not expected in the tree. Visual C++ runtime DLLs are deliberately NOT here: they ship
# with the Visual C++ Redistributable, which a clean PC may lack, so the tree must carry them.
WINDOWS_SYSTEM_DLLS = frozenset("""
advapi32 authz avicap32 avrt bcrypt bcryptprimitives cabinet cfgmgr32 clbcatq combase comctl32
comdlg32 credui crypt32 cryptbase cryptsp d2d1 d3d11 d3d12 d3d9 d3dcompiler_47 dbghelp devobj dhcpcsvc
dinput8 dnsapi dsound dwmapi dwrite dxgi dxva2 esent gdi32 gdi32full glu32 hid imagehlp imm32
iphlpapi kernel32 kernelbase lz32 mf mfplat mfreadwrite mmdevapi mpr msacm32 msctf msi msimg32
msvcrt mswsock ncrypt ndfapi netapi32 normaliz nsi ntdll ntdsapi ole32 oleacc oleaut32 opengl32
pdh powrprof propsys psapi rpcrt4 rstrtmgr samcli sechost secur32 setupapi shcore shell32 shlwapi
shfolder sspicli ucrtbase urlmon user32 userenv usp10 uxtheme version wevtapi win32u windowscodecs
winhttp wininet winmm winspool wintrust wldap32 ws2_32 wsock32 wtsapi32 xinput1_4 xinput9_1_0
""".split())

_API_SET = re.compile(r"^(api|ext)-ms-[a-z0-9\-.]+$")
# The Visual C++ runtime family. Each member needs the same version set (see the pin list).
_VC_RUNTIME = re.compile(r"^(msvcp|vcruntime|concrt|vcomp|vccorlib|vcamp|mfc|atl)\d+[a-z0-9_]*$")


class PEError(ValueError):
    """The file is not a PE image this reader understands."""


def _cstring(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    if offset < 0 or end < 0:
        raise PEError("unterminated string in the import table")
    return data[offset:end].decode("ascii", "replace")


def pe_imports(data: bytes) -> list[str]:
    """Lower-case names of the DLLs a PE image imports, load-time and delay-load, in file order.

    Raises PEError for anything that is not a PE32 / PE32+ image or whose tables run past the end.
    """
    try:
        return _pe_imports(data)
    except (struct.error, IndexError) as exc:
        raise PEError(f"truncated or malformed PE file ({exc})") from None


def _pe_imports(data: bytes) -> list[str]:
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PEError("no MZ header")
    (pe_off,) = struct.unpack_from("<I", data, 0x3C)
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise PEError("no PE signature")
    _machine, n_sections, _ts, _sym, _nsym, opt_size, _chars = struct.unpack_from(
        "<HHIIIHH", data, pe_off + 4)
    opt = pe_off + 24
    (magic,) = struct.unpack_from("<H", data, opt)
    if magic == 0x10B:      # PE32
        dirs_off, image_base = opt + 96, struct.unpack_from("<I", data, opt + 28)[0]
    elif magic == 0x20B:    # PE32+
        dirs_off, image_base = opt + 112, struct.unpack_from("<Q", data, opt + 24)[0]
    else:
        raise PEError(f"unknown optional-header magic {magic:#x}")
    (n_dirs,) = struct.unpack_from("<I", data, dirs_off - 4)
    sections_off = opt + opt_size
    sections = []
    for i in range(n_sections):
        _name, vsize, va, rawsize, rawptr = struct.unpack_from("<8sIIII", data, sections_off + 40 * i)
        sections.append((va, max(vsize, rawsize), rawptr))

    def rva_to_off(rva: int) -> int:
        for va, size, rawptr in sections:
            if va <= rva < va + size:
                return rawptr + (rva - va)
        raise PEError(f"RVA {rva:#x} is outside every section")

    def directory(index: int) -> int:
        if index >= n_dirs:
            return 0
        rva, _size = struct.unpack_from("<II", data, dirs_off + 8 * index)
        return rva

    names: list[str] = []
    rva = directory(1)      # import table
    if rva:
        off = rva_to_off(rva)
        while True:
            fields = struct.unpack_from("<IIIII", data, off)
            if not any(fields):
                break
            names.append(_cstring(data, rva_to_off(fields[3])).lower())
            off += 20
    rva = directory(13)     # delay-load import table
    if rva:
        off = rva_to_off(rva)
        while True:
            attrs, name_ref = struct.unpack_from("<II", data, off)
            if not attrs and not name_ref:
                break
            # Bit 0 set: the fields are RVAs. Clear: virtual addresses (images from before VC7).
            name_rva = name_ref if attrs & 1 else name_ref - image_base
            names.append(_cstring(data, rva_to_off(name_rva)).lower())
            off += 32
    return names


def _is_vc_runtime(name: str) -> bool:
    return bool(_VC_RUNTIME.match(name.rsplit(".", 1)[0]))


def check_tree(root: Path, app_dir: str = "python") -> list[str]:
    """Every problem found in the tree at ``root``; an empty list means it is clean."""
    root = Path(root)
    problems: list[str] = []
    if not root.is_dir():
        return [f"{root}: not a folder"]
    binaries = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in BINARY_SUFFIXES)
    in_tree = {p.name.lower() for p in binaries if p.suffix.lower() != ".exe"}
    app_files = {p.name.lower() for p in (root / app_dir).glob("*") if p.is_file()}
    seen: set[tuple[str, str]] = set()
    for path in binaries:
        rel = path.relative_to(root).as_posix()
        try:
            imports = pe_imports(path.read_bytes())
        except PEError as exc:
            problems.append(f"{rel}: cannot read its import table: {exc}")
            continue
        beside = {p.name.lower() for p in path.parent.glob("*") if p.is_file()}
        for dll in imports:
            if (rel, dll) in seen:
                continue
            seen.add((rel, dll))
            stem = dll.rsplit(".", 1)[0]
            if _API_SET.match(stem) or stem in WINDOWS_SYSTEM_DLLS:
                continue
            if _is_vc_runtime(dll):
                if dll not in app_files and dll not in beside:
                    problems.append(
                        f"{rel}: imports {dll}, which is not in {app_dir}/ or next to it "
                        f"(a PC without the Visual C++ Redistributable cannot load it)")
            elif dll not in in_tree:
                problems.append(f"{rel}: imports {dll}, which is not in the tree and is not a "
                                f"known Windows 10 system DLL")
    for sub in ("app", "core"):
        base = root / sub
        if not base.is_dir():
            problems.append(f"{sub}/: missing from the tree")
            continue
        for p in sorted(base.rglob("__pycache__")):
            problems.append(f"{p.relative_to(root).as_posix()}: build-machine bytecode folder must not ship")
        for p in sorted(base.rglob("*.pyc")):
            if p.parent.name != "__pycache__":
                problems.append(f"{p.relative_to(root).as_posix()}: stray .pyc must not ship")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check the Windows embed tree for loadable imports.")
    ap.add_argument("tree", type=Path, help="the embed tree (embed_build)")
    ap.add_argument("--app-dir", default="python",
                    help="folder of python.exe inside the tree (default: %(default)s)")
    args = ap.parse_args(argv)
    if not args.tree.is_dir():
        print(f"[check] ERROR: {args.tree} is not a folder", file=sys.stderr)
        return 2
    problems = check_tree(args.tree, args.app_dir)
    for line in problems:
        print(f"[check] {line}")
    n = sum(1 for p in args.tree.rglob("*") if p.is_file() and p.suffix.lower() in BINARY_SUFFIXES)
    print(f"[check] {n} binaries scanned: {'FAIL, ' + str(len(problems)) + ' problem(s)' if problems else 'ok'}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
