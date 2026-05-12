# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for `_filelock.exclusive_lock` — the cross-platform lock
that serialises concurrent TokenStore writes (issue #15)."""

from __future__ import annotations

import multiprocessing as mp
import time
from pathlib import Path

import pytest

from mcp_microsoft_graph_auth._filelock import (
    TokenStoreLockTimeoutError,
    exclusive_lock,
)
from mcp_microsoft_graph_auth.token_store import (
    EncryptedFileTokenStore,
    PlainFileTokenStore,
)

# ---------------------------------------------------------------------
# exclusive_lock — happy path + timeout
# ---------------------------------------------------------------------


def test_exclusive_lock_acquires_and_releases_on_clean_path(tmp_path: Path) -> None:
    """One acquirer, no contention: enter / exit normally, lock-file
    left on disk for next acquirer to find."""
    target = tmp_path / "token.json"
    with exclusive_lock(target):
        pass
    # Sidecar lock file remains so the next acquirer can flock it.
    assert (tmp_path / "token.json.lock").exists()


def test_exclusive_lock_two_sequential_acquires_succeed(tmp_path: Path) -> None:
    target = tmp_path / "token.json"
    with exclusive_lock(target):
        pass
    with exclusive_lock(target):
        pass


def test_exclusive_lock_two_concurrent_threads_serialise(tmp_path: Path) -> None:
    """Two threads acquiring the same lock must not overlap.

    Uses real time to verify serialisation rather than mock — the lock
    is OS-level and the only way to be sure it works is to actually
    hold it. Threshold (50ms) is wide enough to be reliable on slow CI."""
    import threading

    target = tmp_path / "token.json"
    timeline: list[tuple[str, float]] = []
    lock = threading.Lock()

    def worker(name: str, hold_s: float) -> None:
        with exclusive_lock(target):
            with lock:
                timeline.append((f"{name}-enter", time.monotonic()))
            time.sleep(hold_s)
            with lock:
                timeline.append((f"{name}-exit", time.monotonic()))

    t1 = threading.Thread(target=worker, args=("A", 0.2))
    t2 = threading.Thread(target=worker, args=("B", 0.05))
    t1.start()
    time.sleep(0.01)  # let A get in first
    t2.start()
    t1.join()
    t2.join()

    # Convert to dict for predictable lookup.
    events = dict(timeline)
    # B must enter only AFTER A exits — no overlap.
    assert events["B-enter"] >= events["A-exit"] - 0.001, (
        f"B entered before A released the lock: timeline={timeline}"
    )


def _hold_lock_in_subprocess(path: str, hold_s: float, ready_file: str) -> None:
    """Subprocess helper: acquire the lock, signal readiness, hold."""
    p = Path(path)
    with exclusive_lock(p):
        Path(ready_file).write_text("ready")
        time.sleep(hold_s)


def test_exclusive_lock_times_out_when_held_elsewhere(tmp_path: Path) -> None:
    """A second acquirer that can't get the lock within `timeout`
    raises `TokenStoreLockTimeoutError`, not a hang or silent overwrite."""
    target = tmp_path / "token.json"
    ready = tmp_path / "ready"
    proc = mp.Process(
        target=_hold_lock_in_subprocess,
        args=(str(target), 2.0, str(ready)),
    )
    proc.start()
    try:
        # Wait for the subprocess to actually hold the lock.
        deadline = time.monotonic() + 5.0
        while not ready.exists():
            if time.monotonic() >= deadline:
                pytest.fail("subprocess never acquired the lock")
            time.sleep(0.05)

        # Now try to acquire from the main process with a short timeout.
        with pytest.raises(TokenStoreLockTimeoutError) as exc_info:
            with exclusive_lock(target, timeout=0.3):
                pytest.fail("should not have acquired — subprocess holds it")
        assert exc_info.value.lock_path == target.with_name("token.json.lock")
        assert exc_info.value.timeout == 0.3
    finally:
        proc.join(timeout=5.0)
        if proc.is_alive():
            proc.terminate()
            proc.join()


# ---------------------------------------------------------------------
# TokenStore.set / .delete — covered by exclusive_lock
# ---------------------------------------------------------------------


def test_plain_file_store_set_holds_lock(tmp_path: Path) -> None:
    """After a clean `.set`, the sidecar `.lock` file exists — the
    lock was acquired and released around the write."""
    store = PlainFileTokenStore(base_dir=tmp_path)
    store.set("default", b'{"a":1}')
    profile_dir = tmp_path / "default"
    assert (profile_dir / "token.json").exists()
    assert (profile_dir / "token.json.lock").exists()


def test_plain_file_store_delete_holds_lock(tmp_path: Path) -> None:
    store = PlainFileTokenStore(base_dir=tmp_path)
    store.set("default", b'{"a":1}')
    store.delete("default")
    profile_dir = tmp_path / "default"
    assert not (profile_dir / "token.json").exists()
    # Lock file remains (cheap; deleting it would race the next acquirer).
    assert (profile_dir / "token.json.lock").exists()


def test_plain_file_store_get_does_not_create_lock(tmp_path: Path) -> None:
    """Per issue #15, `.get` is lockless — single atomic read of the
    file, no need to coordinate."""
    store = PlainFileTokenStore(base_dir=tmp_path)
    # No write happened yet → no lock file should appear from a read.
    assert store.get("default") is None
    profile_dir = tmp_path / "default"
    assert not (profile_dir / "token.json.lock").exists()


def test_encrypted_file_store_set_holds_lock(tmp_path: Path) -> None:
    store = EncryptedFileTokenStore(base_dir=tmp_path, passphrase="hunter2")
    store.set("default", b'{"a":1}')
    profile_dir = tmp_path / "default"
    assert (profile_dir / "token.enc").exists()
    assert (profile_dir / "token.salt").exists()
    assert (profile_dir / "token.enc.lock").exists()


def test_encrypted_file_store_delete_holds_lock(tmp_path: Path) -> None:
    store = EncryptedFileTokenStore(base_dir=tmp_path, passphrase="hunter2")
    store.set("default", b'{"a":1}')
    store.delete("default")
    profile_dir = tmp_path / "default"
    assert not (profile_dir / "token.enc").exists()
    assert (profile_dir / "token.enc.lock").exists()


def test_plain_file_store_concurrent_writers_serialise(tmp_path: Path) -> None:
    """The motivating bug: two writers against the same profile.
    Each write must complete in full; no half-written JSON survives."""
    import threading

    store = PlainFileTokenStore(base_dir=tmp_path)
    payload_a = b'{"writer":"A","content":"' + b"a" * 1000 + b'"}'
    payload_b = b'{"writer":"B","content":"' + b"b" * 1000 + b'"}'
    barrier = threading.Barrier(2)

    def writer(payload: bytes) -> None:
        barrier.wait()
        store.set("default", payload)

    t1 = threading.Thread(target=writer, args=(payload_a,))
    t2 = threading.Thread(target=writer, args=(payload_b,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Whichever wrote last wins, but the file must be one of the two
    # complete payloads (not a corrupt interleave).
    final = (tmp_path / "default" / "token.json").read_bytes()
    assert final in (payload_a, payload_b), (
        "concurrent writes produced corrupt content — lock didn't serialise them"
    )


def test_token_store_lock_timeout_carries_actionable_metadata(tmp_path: Path) -> None:
    """The exception message must name the path + timeout so log
    consumers and downstream MCP error handlers can construct a clear
    message for the agent."""
    lock_path = tmp_path / "x.lock"
    exc = TokenStoreLockTimeoutError(lock_path, 1.5)
    assert "TOKEN_STORE_LOCK_TIMEOUT" in str(exc)
    assert str(lock_path) in str(exc)
    assert "1.5" in str(exc)
    assert exc.lock_path == lock_path
    assert exc.timeout == 1.5
