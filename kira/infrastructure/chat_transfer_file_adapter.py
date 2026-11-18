"""Local-filesystem adapter for bounded Chat transfer reads and atomic writes."""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

from ..core.interfaces.transfer import ChatTransferFilePort

_SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", re.ASCII)
_READ_CHUNK_SIZE = 64 * 1024
_TEMP_PREFIX = ".kira-transfer-"


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare file identity where the platform exposes a stable inode."""
    left_inode = int(getattr(left, "st_ino", 0) or 0)
    right_inode = int(getattr(right, "st_ino", 0) or 0)
    if left_inode and right_inode:
        return left.st_dev == right.st_dev and left_inode == right_inode
    return True


class LocalChatTransferFileAdapter(ChatTransferFilePort):
    """Filesystem implementation of the Core ChatTransferFilePort.

    Import reads reject symlinks and non-regular files, check the file size
    before reading, and cap the actual bytes read in case the file grows.
    Export writes use a private temporary file in the destination directory,
    flush it to disk, and atomically replace the requested destination.
    """

    def read_bytes(self, source: Path, *, max_bytes: int) -> bytes:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
            raise ValueError("max_bytes must be a non-negative integer")

        path = Path(source)
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError("Import source must be a regular file, not a symlink or special file")
        if initial.st_size > max_bytes:
            raise ValueError(f"Import file exceeds the {max_bytes}-byte limit")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(os.fspath(path), flags)
        try:
            opened = os.fstat(descriptor)
            current = path.lstat()
            if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode):
                raise ValueError("Import source changed or is not a regular file")
            if not _same_file(initial, opened) or not _same_file(opened, current):
                raise ValueError("Import source changed while it was being opened")
            if opened.st_size > max_bytes:
                raise ValueError(f"Import file exceeds the {max_bytes}-byte limit")

            result = bytearray()
            # Read at most max_bytes + 1 so a file that grows after stat() is
            # still rejected without an unbounded allocation.
            while len(result) <= max_bytes:
                remaining = max_bytes + 1 - len(result)
                chunk = os.read(descriptor, min(_READ_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                result.extend(chunk)
            if len(result) > max_bytes:
                raise ValueError(f"Import file exceeds the {max_bytes}-byte limit")
            return bytes(result)
        finally:
            os.close(descriptor)

    def write_bytes_atomically(
        self,
        directory: Path,
        filename: str,
        content: bytes,
    ) -> Path:
        if not isinstance(filename, str) or _SAFE_FILENAME.fullmatch(filename) is None:
            raise ValueError("Filename must be a simple basename without path components")
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")

        root = Path(directory).expanduser().resolve(strict=True)
        if not stat.S_ISDIR(root.stat().st_mode):
            raise ValueError("Export destination must be an existing directory")
        destination = root / filename

        descriptor = -1
        temporary: Path | None = None
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=_TEMP_PREFIX,
                suffix=".tmp",
                dir=os.fspath(root),
            )
            descriptor = fd
            temporary = Path(temporary_name)
            stream = os.fdopen(descriptor, "wb")
            descriptor = -1  # fdopen now owns the descriptor.
            with stream:
                written = stream.write(content)
                if written != len(content):
                    raise OSError("Incomplete write while creating Chat export")
                stream.flush()
                os.fsync(stream.fileno())

            os.replace(os.fspath(temporary), os.fspath(destination))
            temporary = None
            self._sync_directory(root)
            return destination
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        """Persist the directory entry where directory fsync is supported."""
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(os.fspath(directory), flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            # Some supported platforms/filesystems do not allow directory fsync.
            pass
        finally:
            os.close(descriptor)


__all__ = ["LocalChatTransferFileAdapter"]
