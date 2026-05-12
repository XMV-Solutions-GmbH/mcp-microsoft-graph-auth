# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Cross-platform exclusive file lock for serialising TokenStore writes.

Two paths can both write to `<base_dir>/<profile>/token.*` against the
same profile: the CLI `login` subcommand and an MCP-tool `*_login_begin`
that runs concurrently in the same shell session. Without a lock the
race outcome is "last writer wins" — both writers produce a valid
token JSON so corruption is unlikely, but the loser doesn't learn its
write was discarded, and on Windows / certain filesystems `os.replace`
isn't atomic so a partial-write could still land.

Locking semantics:

- Exclusive (`flock LOCK_EX` / `msvcrt locking LK_LOCK`).
- Acquired on `.set` / `.delete`, NOT on `.get` (read path stays fast;
  a single `read_bytes()` reads the file atomically enough for the
  caller's purposes).
- Held only for the duration of one write.
- Default timeout 10s. On timeout we raise `TokenStoreLockTimeoutError`
  rather than block forever — downstream MCP tools can surface this
  as `{error: {code: "concurrent_login_attempt"}}` to the agent.

POSIX backend uses `fcntl.flock` on a sidecar `<file>.lock` file (so
the actual token file's atime / mtime stay clean for downstream
debugging). Windows backend uses `msvcrt.locking`. Neither approach
needs a third-party dependency — pure stdlib.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

_DEFAULT_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.05


class TokenStoreLockTimeoutError(RuntimeError):
    """Raised when an exclusive lock on a TokenStore file can't be
    acquired within the timeout.

    Surfaces to the downstream MCP tool as a recoverable condition —
    typical handling is to surface the timeout to the agent so it can
    retry, OR (if two flows are racing) to defer to whoever's holding
    the lock and re-read the token.

    Carries the lock file path so logs / error messages can pinpoint
    which profile collided.
    """

    def __init__(self, lock_path: Path, timeout: float) -> None:
        super().__init__(
            f"TOKEN_STORE_LOCK_TIMEOUT: could not acquire exclusive lock "
            f"on {lock_path} within {timeout:g}s. Another process is "
            f"writing this profile's token; retry in a few seconds.",
        )
        self.lock_path = lock_path
        self.timeout = timeout


@contextlib.contextmanager
def exclusive_lock(
    target: Path,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> Iterator[None]:
    """Acquire an exclusive lock for writes to `target`. Block up to
    `timeout` seconds; raise `TokenStoreLockTimeoutError` on timeout.

    Uses a sidecar `<target>.lock` file so the actual token file's
    inode and timestamps stay clean. The lock file is left behind on
    disk after release (cheap to recreate; deleting it would race
    with the next acquirer).
    """
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Open with O_CREAT — the file may not exist yet on first write.
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _acquire_with_timeout(fd, lock_path, timeout)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)


if sys.platform == "win32":  # pragma: no cover — POSIX-only CI
    import msvcrt

    def _acquire_with_timeout(fd: int, lock_path: Path, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TokenStoreLockTimeoutError(lock_path, timeout) from None
                time.sleep(_POLL_INTERVAL_S)

    def _release(fd: int) -> None:
        try:
            # Need to seek back to 0 because LK_NBLCK locked byte 0.
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            # Process is about to exit / fd already released elsewhere
            # — surfacing an error here would just confuse callers.
            pass

else:
    import fcntl

    def _acquire_with_timeout(fd: int, lock_path: Path, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TokenStoreLockTimeoutError(lock_path, timeout) from None
                time.sleep(_POLL_INTERVAL_S)

    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
