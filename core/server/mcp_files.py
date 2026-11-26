"""Handle-based local MCP confinement during staging and export."""
from __future__ import annotations

import contextlib
import errno
import os
import secrets
import shutil
import stat
import sys
from pathlib import Path
from typing import Any, IO, Iterator


_LINK_UNAVAILABLE = {
    errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS, errno.EMLINK,
}


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


def _owns_entry(
    entry: str, directory_fd: int | None, identity: os.stat_result, *, match_mtime: bool = False,
) -> bool:
    current = os.stat(entry, dir_fd=directory_fd, follow_symlinks=False)
    return (stat.S_ISREG(current.st_mode) and os.path.samestat(identity, current)
            and (not match_mtime or identity.st_mtime == current.st_mtime))


def _unlink_owned_posix(entry: str, directory_fd: int, fd: int) -> None:
    with contextlib.suppress(OSError):
        identity = os.fstat(fd)
        fat_empty = (sys.platform == "darwin" and identity.st_size == 0
                     and identity.st_ino == 999_999_999)
        if fat_empty:
            # macOS FAT reports the same inode for empty files. Verify that a
            # timestamp changed through our descriptor is visible at the name.
            if not _owns_entry(entry, directory_fd, identity, match_mtime=True):
                return
            # FAT stores modification times at two-second precision.
            marker = 946_684_800 + 2 * secrets.randbelow(31_536_000)
            if marker == identity.st_mtime:
                marker += 2
            os.utime(fd, (identity.st_atime, marker))
            identity = os.fstat(fd)
            if identity.st_mtime != marker:
                return
        if _owns_entry(entry, directory_fd, identity, match_mtime=fat_empty):
            os.unlink(entry, dir_fd=directory_fd)


def _publish_posix(staged: IO[bytes], entry: str, name: str, directory_fd: int) -> None:
    try:
        os.link(entry, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                follow_symlinks=False)
        return
    except OSError as error:
        if error.errno not in _LINK_UNAVAILABLE:
            raise

    expected_size = os.fstat(staged.fileno()).st_size
    staged.seek(0)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW")
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        try:
            with os.fdopen(fd, "wb", closefd=False) as output:
                shutil.copyfileobj(staged, output)
                output.flush()
                os.fsync(fd)
                identity = os.fstat(fd)
                if identity.st_size != expected_size:
                    raise OSError("export copy size does not match staging")
            if not _owns_entry(name, directory_fd, identity):
                raise OSError("export destination changed during copy")
        except BaseException:
            _unlink_owned_posix(name, directory_fd, fd)
            raise
    finally:
        os.close(fd)


@contextlib.contextmanager
def confined_open(parent: Path, root: Path, name: str, mode: str) -> Iterator[Any]:
    """Open media for reading or publish a complete export on normal exit."""
    if mode not in {"rb", "xb"} or Path(name).name != name:
        raise ValueError("invalid confined file operation")
    with _pinned_directory(parent, root) as directory_fd, contextlib.ExitStack() as file_handles:
        writing = mode == "xb"
        entry = f".wts-export-{secrets.token_hex(16)}.tmp" if writing else name
        fd: int | None = None
        if os.name == "nt":
            entry = str(parent / entry)
            stream = open(entry, mode)
        else:
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL if writing else os.O_RDONLY
            fd = os.open(entry, flags | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            file_handles.callback(os.close, fd)
            stream = os.fdopen(fd, "x+b" if writing else mode, closefd=False)

        identity: os.stat_result | None = None
        try:
            with stream:
                identity = os.fstat(stream.fileno())
                actual = opened_path(stream.fileno())
                if not actual.is_relative_to(root) or not stat.S_ISREG(identity.st_mode):
                    raise ValueError("opened file is outside the local grant or is not regular media")
                yield stream
                if writing and directory_fd is not None:
                    stream.flush()
                    # FAT can assign a different inode on the first write.
                    if not _owns_entry(entry, directory_fd, os.fstat(stream.fileno())):
                        raise ValueError("staged export changed")
                    _publish_posix(stream, entry, name, directory_fd)
            if writing and directory_fd is None:
                if not _owns_entry(entry, directory_fd, identity):
                    raise ValueError("staged export changed")
                # Windows rename is exclusive. Keep the ancestry pinned.
                os.rename(entry, parent / name)
        finally:
            if writing and directory_fd is not None and fd is not None:
                _unlink_owned_posix(entry, directory_fd, fd)
            elif writing and identity is not None:
                with contextlib.suppress(OSError):
                    if _owns_entry(entry, directory_fd, identity):
                        os.unlink(entry, dir_fd=directory_fd)
