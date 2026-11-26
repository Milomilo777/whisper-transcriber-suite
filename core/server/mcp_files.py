"""Handle-based local MCP confinement during staging and export."""
from __future__ import annotations

import contextlib
import os
import secrets
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
def _pinned_directory(parent: Path, root: Path) -> Iterator[int | None]:
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
            yield None
        else:
            directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, directory_fd)
            if opened_path(directory_fd) != parent:
                raise ValueError("local directory changed")
            yield directory_fd


@contextlib.contextmanager
def confined_open(parent: Path, root: Path, name: str, mode: str) -> Iterator[Any]:
    """Open media for reading or publish a complete export on normal exit."""
    if mode not in {"rb", "xb"} or Path(name).name != name:
        raise ValueError("invalid confined file operation")
    with _pinned_directory(parent, root) as directory_fd:
        writing = mode == "xb"
        entry = f".wts-export-{secrets.token_hex(16)}.tmp" if writing else name
        if os.name == "nt":
            entry = str(parent / entry)
            stream = open(entry, mode)
        else:
            flags = os.O_RDONLY if mode == "rb" else os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(entry, flags | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            stream = os.fdopen(fd, mode)

        def owns_entry() -> bool:
            current = os.stat(entry, dir_fd=directory_fd, follow_symlinks=False)
            return (identity is not None and stat.S_ISREG(current.st_mode)
                    and os.path.samestat(identity, current))

        identity: os.stat_result | None = None
        try:
            with stream:
                identity = os.fstat(stream.fileno())
                actual = opened_path(stream.fileno())
                if not actual.is_relative_to(root) or not stat.S_ISREG(identity.st_mode):
                    raise ValueError("opened file is outside the local grant or is not regular media")
                yield stream
            if writing:
                if not owns_entry():
                    raise ValueError("staged export changed")
                if os.name == "nt":
                    # Windows rename is exclusive. Keep the ancestry pinned.
                    os.rename(entry, parent / name)
                else:
                    os.link(entry, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                            follow_symlinks=False)
        finally:
            if writing and identity is not None:
                with contextlib.suppress(OSError):
                    if owns_entry():
                        os.unlink(entry, dir_fd=directory_fd)
