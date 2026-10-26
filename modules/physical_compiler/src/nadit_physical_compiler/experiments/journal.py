"""Single-writer locking, atomic JSON, and interruption-safe append-only records."""

import errno
import json
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_WINDOWS = sys.platform == "win32"
_WINDOWS_RETRY_DELAYS_S = (0.01, 0.02, 0.04, 0.08, 0.16)


def _retry_windows_io[T](
    operation: Callable[[], T], *, deadline: float | None = None
) -> T:
    """Retry possible Windows sharing denials, never suppress a persistent error.

    Access denied (5/EACCES) is ambiguous: it may be a permanent ACL error, so the
    same exception is re-raised after at most six attempts. Sharing/lock violations
    (32/33) use the same bound. Total scheduled sleep is at most 310 ms; operating
    system calls are not preemptible. A caller deadline can shorten this allowance.
    Non-Windows errors and other I/O failures propagate without retry.
    """
    for attempt in range(len(_WINDOWS_RETRY_DELAYS_S) + 1):
        try:
            return operation()
        except OSError as error:
            code = getattr(error, "winerror", None)
            retryable = _WINDOWS and (
                code in (5, 32, 33)
                or (
                    code is None
                    and isinstance(error, PermissionError)
                    and error.errno == errno.EACCES
                )
            )
            if not retryable or attempt == len(_WINDOWS_RETRY_DELAYS_S):
                raise
            delay = _WINDOWS_RETRY_DELAYS_S[attempt]
            if deadline is not None and time.monotonic() + delay >= deadline:
                raise
            time.sleep(delay)
    raise AssertionError("Unreachable Windows I/O retry state")


def read_text(path: Path, *, deadline: float | None = None) -> str:
    """Read UTF-8 with bounded sharing retries; callers parse/validate separately."""
    return _retry_windows_io(
        lambda: path.read_text(encoding="utf-8"), deadline=deadline
    )


def write_json(path: Path, document: Any) -> None:
    """Atomically replace one owned JSON artifact after flushing its contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    _retry_windows_io(lambda: temporary.replace(path))


def read_records(path: Path, *, repair: bool = False) -> list[dict[str, Any]]:
    """Read complete records; repair only a trailing interrupted append."""
    if not path.exists():
        return []
    content = path.read_bytes()
    if content and not content.endswith(b"\n"):
        boundary = content.rfind(b"\n") + 1
        try:
            json.loads(content[boundary:])
        except json.JSONDecodeError:
            content = content[:boundary]
            if repair:
                with path.open("r+b") as stream:
                    stream.truncate(boundary)
        else:
            content += b"\n"
            if repair:
                with path.open("ab") as stream:
                    stream.write(b"\n")
    return [json.loads(line) for line in content.splitlines() if line.strip()]


def append(path: Path, document: dict[str, Any]) -> None:
    """Append one complete record and flush it to disk; caller owns the lock."""
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(document, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def directory_lock(directory: Path) -> Iterator[None]:
    """Hold an OS lock that is automatically released on interruption or death."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".writer.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError(f"Experiment already has a writer: {directory}") from error
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
