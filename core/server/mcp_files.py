"""Handle-based local MCP confinement during staging and export."""
from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path
from typing import Any, Iterator


def opened_path(fd: int) -> Path:
    """Ask the OS for an opened object's actual path; fail closed elsewhere."""
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes
        function = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
        function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        function.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        size = function(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
        if not size or size >= len(buffer):
            raise OSError("cannot verify opened local path")
        name = buffer.value
        if name.startswith("\\\\?\\UNC\\"):
            name = "\\\\" + name[8:]
        elif name.startswith("\\\\?\\"):
            name = name[4:]
        return Path(name)
    if Path("/proc/self/fd").is_dir():
        return Path(os.readlink(f"/proc/self/fd/{fd}"))
    import fcntl
    # macOS F_GETPATH; no file contents are read to establish confinement.
    return Path(os.fsdecode(fcntl.fcntl(fd, 50, bytes(1024)).split(b"\0", 1)[0]))


@contextlib.contextmanager
def confined_open(parent: Path, root: Path, name: str, mode: str) -> Iterator[Any]:
    """Pin the parent, then open relative to it or lock its Windows ancestry."""
    if mode not in {"rb", "xb"} or Path(name).name != name:
        raise ValueError("invalid confined file operation")
    if root.resolve(strict=True) != root or not parent.is_relative_to(root):
        raise ValueError("local grant changed")
    with contextlib.ExitStack() as stack:
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            # No FILE_SHARE_DELETE: ancestors cannot be renamed/replaced until close.
            for directory in reversed([parent, *parent.parents]):
                handle = create(str(directory), 0x80, 3, None, 3, 0x02000000, None)
                if handle == wintypes.HANDLE(-1).value:
                    raise OSError("cannot pin local media directory")
                try:
                    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
                except BaseException:
                    close(handle)
                    raise
                stack.callback(os.close, fd)
                if opened_path(fd) != directory:
                    raise ValueError("local directory changed")
            stream = stack.enter_context((parent / name).open(mode))
        else:
            directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, directory_fd)
            if opened_path(directory_fd) != parent:
                raise ValueError("local directory changed")
            flags = os.O_RDONLY if mode == "rb" else os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(name, flags | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            stream = stack.enter_context(os.fdopen(fd, mode))
        actual = opened_path(stream.fileno())
        if not actual.is_relative_to(root) or not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("opened file is outside the local grant or is not regular media")
        yield stream
