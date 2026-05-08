# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for LoginSession + LoginSessionRegistry + public_view.

Edge cases deliberately covered:
- public_view never leaks device_code (security-critical)
- put_if_absent is atomic under concurrent threads
- time_remaining_s clamps to 0 for past expirations
- registry's lock is reentrant (caller can call from inside another call)
- all_pending vs all_sessions filter correctly
- remove returns None for missing profiles (Protocol compliance)
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp_microsoft_graph_auth.login_session import (
    LoginSession,
    LoginSessionRegistry,
    public_view,
)


def _make_session(profile: str = "default", *, expires_in_s: int = 900) -> LoginSession:
    return LoginSession.new(
        profile=profile,
        device_code="DC-secret",
        user_code="ABC123",
        verification_url="https://microsoft.com/devicelogin",
        verification_url_complete=None,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_s),
        interval_s=5,
    )


# ---------------------------------------------------------------------
# LoginSession dataclass + factory
# ---------------------------------------------------------------------


def test_new_assigns_uuid4_session_id() -> None:
    s1 = _make_session()
    s2 = _make_session()
    assert s1.session_id != s2.session_id
    assert len(s1.session_id) == 36  # uuid4 string form


def test_new_starts_in_pending_status() -> None:
    assert _make_session().status == "pending"


def test_new_has_started_at_in_recent_past() -> None:
    s = _make_session()
    delta = (datetime.now(UTC) - s.started_at).total_seconds()
    assert 0 <= delta < 1.0


def test_time_remaining_s_for_unexpired_session() -> None:
    s = _make_session(expires_in_s=600)
    remaining = s.time_remaining_s()
    assert 595 <= remaining <= 600


def test_time_remaining_s_clamps_to_zero_for_expired() -> None:
    s = LoginSession.new(
        profile="default",
        device_code="X",
        user_code="X",
        verification_url="x",
        verification_url_complete=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=120),
        interval_s=5,
    )
    assert s.time_remaining_s() == 0


def test_time_remaining_s_with_explicit_now() -> None:
    """Reproducible time-remaining for tests that need determinism."""
    expires = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
    now = datetime(2026, 5, 8, 11, 50, 0, tzinfo=UTC)
    s = LoginSession.new(
        profile="default",
        device_code="X",
        user_code="X",
        verification_url="x",
        verification_url_complete=None,
        expires_at=expires,
        interval_s=5,
    )
    assert s.time_remaining_s(now=now) == 600


def test_status_is_mutable() -> None:
    """Consumer's poll task drives the state machine — fields must be writable."""
    s = _make_session()
    s.status = "success"
    s.signed_in_user_upn = "alice@x.com"
    assert s.status == "success"
    assert s.signed_in_user_upn == "alice@x.com"


# ---------------------------------------------------------------------
# LoginSessionRegistry — basic CRUD
# ---------------------------------------------------------------------


def test_get_returns_None_for_missing() -> None:
    r = LoginSessionRegistry()
    assert r.get("never-stored") is None


def test_put_then_get_roundtrip() -> None:
    r = LoginSessionRegistry()
    s = _make_session("profile-a")
    r.put(s)
    fetched = r.get("profile-a")
    assert fetched is s  # identity, not just equality


def test_put_replaces_existing() -> None:
    """put() is overwrite-on-collide; use put_if_absent for first-wins."""
    r = LoginSessionRegistry()
    s1 = _make_session("profile-a")
    s2 = _make_session("profile-a")
    r.put(s1)
    r.put(s2)
    assert r.get("profile-a") is s2


def test_remove_returns_session_when_present() -> None:
    r = LoginSessionRegistry()
    s = _make_session("profile-a")
    r.put(s)
    removed = r.remove("profile-a")
    assert removed is s
    assert r.get("profile-a") is None


def test_remove_returns_None_when_missing() -> None:
    r = LoginSessionRegistry()
    assert r.remove("never-stored") is None


def test_clear_drops_everything() -> None:
    r = LoginSessionRegistry()
    r.put(_make_session("a"))
    r.put(_make_session("b"))
    r.clear()
    assert r.get("a") is None
    assert r.get("b") is None
    assert r.all_sessions() == []


# ---------------------------------------------------------------------
# put_if_absent — first-write-wins
# ---------------------------------------------------------------------


def test_put_if_absent_inserts_when_empty() -> None:
    r = LoginSessionRegistry()
    s = _make_session("profile-a")
    out = r.put_if_absent(s)
    assert out is s
    assert r.get("profile-a") is s


def test_put_if_absent_returns_existing_when_present() -> None:
    """First-write-wins: a second put_if_absent returns the original."""
    r = LoginSessionRegistry()
    s1 = _make_session("profile-a")
    s2 = _make_session("profile-a")
    out1 = r.put_if_absent(s1)
    out2 = r.put_if_absent(s2)
    assert out1 is s1
    assert out2 is s1  # NOT s2 — first wins
    assert r.get("profile-a") is s1


def test_put_if_absent_is_atomic_across_threads() -> None:
    """Two threads racing to insert the same profile: exactly one wins,
    both observe the same winning session afterwards."""
    r = LoginSessionRegistry()
    sessions = [_make_session("contended") for _ in range(20)]
    results: list[LoginSession] = []
    barrier = threading.Barrier(20)

    def attempt(s: LoginSession) -> None:
        barrier.wait()  # release all threads at once
        results.append(r.put_if_absent(s))

    threads = [threading.Thread(target=attempt, args=(s,)) for s in sessions]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 20 callers should observe exactly one winner
    winners = {s.session_id for s in results}
    assert len(winners) == 1
    # And the dict-stored session matches that winner
    stored = r.get("contended")
    assert stored is not None
    assert stored.session_id in winners


# ---------------------------------------------------------------------
# all_pending / all_sessions filters
# ---------------------------------------------------------------------


def test_all_pending_excludes_terminal_states() -> None:
    r = LoginSessionRegistry()
    pending_a = _make_session("a")
    pending_b = _make_session("b")
    success = _make_session("c")
    success.status = "success"
    failed = _make_session("d")
    failed.status = "failed"
    cancelled = _make_session("e")
    cancelled.status = "cancelled"
    expired = _make_session("f")
    expired.status = "expired"
    for s in (pending_a, pending_b, success, failed, cancelled, expired):
        r.put(s)
    pending_profiles = {s.profile for s in r.all_pending()}
    assert pending_profiles == {"a", "b"}


def test_all_sessions_includes_every_status() -> None:
    r = LoginSessionRegistry()
    s = _make_session("a")
    s.status = "expired"
    r.put(s)
    assert {x.profile for x in r.all_sessions()} == {"a"}


def test_all_sessions_returns_a_snapshot() -> None:
    """Mutating the returned list must not affect the registry."""
    r = LoginSessionRegistry()
    r.put(_make_session("a"))
    snap = r.all_sessions()
    snap.clear()
    assert r.get("a") is not None


# ---------------------------------------------------------------------
# Lock reentrancy — caller may hold the lock when invoking another method
# ---------------------------------------------------------------------


def test_registry_lock_is_reentrant() -> None:
    """A consumer's cancel-then-put_if_absent for force=True semantics
    needs to nest two registry calls. RLock makes that safe."""
    r = LoginSessionRegistry()

    s_old = _make_session("a")
    r.put(s_old)

    # Simulate "with the lock held, do another put" (the simple way to
    # nest is via the registry's own methods; here we directly use _lock
    # as a smoke test of reentrancy)
    with r._lock:
        existing = r.get("a")
        assert existing is s_old
        r.remove("a")
        s_new = _make_session("a")
        r.put(s_new)

    assert r.get("a") is s_new


# ---------------------------------------------------------------------
# public_view — security-critical: NEVER leak device_code
# ---------------------------------------------------------------------


def test_public_view_does_not_leak_device_code() -> None:
    """The single most important invariant of this module."""
    s = _make_session()
    view = public_view(s)
    assert "device_code" not in view
    assert "DC-secret" not in str(view)


def test_public_view_does_not_leak_task_handle() -> None:
    """task is an internal asyncio handle; not appropriate for tool output."""
    s = _make_session()

    class _FakeTask:
        def __repr__(self) -> str:
            return "<a task internal repr should not leak>"

    s.task = _FakeTask()
    view = public_view(s)
    assert "task" not in view


def test_public_view_includes_user_facing_fields() -> None:
    s = _make_session()
    view = public_view(s)
    assert view["session_id"] == s.session_id
    assert view["profile"] == s.profile
    assert view["user_code"] == "ABC123"
    assert view["verification_url"] == "https://microsoft.com/devicelogin"
    assert view["status"] == "pending"
    assert view["interval_s"] == 5
    assert view["time_remaining_s"] > 0
    assert view["signed_in_user_upn"] is None
    assert view["error"] is None


def test_public_view_serialises_expires_at_as_iso() -> None:
    s = _make_session()
    view = public_view(s)
    assert view["expires_at"].endswith("+00:00") or view["expires_at"].endswith("Z")


def test_public_view_with_explicit_now_for_deterministic_remaining() -> None:
    expires = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
    now = datetime(2026, 5, 8, 11, 55, 0, tzinfo=UTC)
    s = LoginSession.new(
        profile="default",
        device_code="X",
        user_code="ABC",
        verification_url="x",
        verification_url_complete=None,
        expires_at=expires,
        interval_s=5,
    )
    view = public_view(s, now=now)
    assert view["time_remaining_s"] == 300


def test_public_view_for_terminal_success_includes_upn() -> None:
    """Once the consumer's poll task fills in upn, the view exposes it."""
    s = _make_session()
    s.status = "success"
    s.signed_in_user_upn = "alice@example.com"
    view = public_view(s)
    assert view["status"] == "success"
    assert view["signed_in_user_upn"] == "alice@example.com"


def test_public_view_for_failed_session_includes_error_dict() -> None:
    s = _make_session()
    s.status = "failed"
    s.error = {"code": "access_denied", "message": "user refused"}
    view = public_view(s)
    assert view["status"] == "failed"
    assert view["error"] == {"code": "access_denied", "message": "user refused"}


def test_public_view_with_uri_complete_populated() -> None:
    s = LoginSession.new(
        profile="default",
        device_code="X",
        user_code="ABC",
        verification_url="https://login/devicelogin",
        verification_url_complete="https://login/devicelogin?code=ABC",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        interval_s=5,
    )
    view = public_view(s)
    assert view["verification_url_complete"] == "https://login/devicelogin?code=ABC"


# ---------------------------------------------------------------------
# Stress test: many profiles, many gets, no exceptions
# ---------------------------------------------------------------------


def test_concurrent_get_after_concurrent_put_no_data_loss() -> None:
    r = LoginSessionRegistry()
    profiles = [f"profile-{i}" for i in range(50)]
    results: dict[str, Any] = {}
    barrier = threading.Barrier(len(profiles))

    def writer(p: str) -> None:
        barrier.wait()
        r.put(_make_session(p))

    def reader(p: str) -> None:
        results[p] = r.get(p)

    write_threads = [threading.Thread(target=writer, args=(p,)) for p in profiles]
    for t in write_threads:
        t.start()
    for t in write_threads:
        t.join()

    read_threads = [threading.Thread(target=reader, args=(p,)) for p in profiles]
    for t in read_threads:
        t.start()
    for t in read_threads:
        t.join()

    for p in profiles:
        assert results[p] is not None
        assert results[p].profile == p
