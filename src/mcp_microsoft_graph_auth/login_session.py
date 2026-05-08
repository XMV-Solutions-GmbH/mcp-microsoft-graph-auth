# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Login-session data + registry for MCP-tool-driven Device Code flows.

When an MCP server exposes Device Code login as MCP tools (e.g.
`<prefix>_login_begin` returns immediately with a `user_code`,
`<prefix>_login_status` reports progress, the actual Microsoft
Identity polling runs in the background), the server needs:

1. A **value type** that captures one in-flight login flow.
2. A **registry** that maps `profile -> LoginSession`, with
   thread-safe mutations.
3. A **public-view helper** that produces a tool-output-friendly
   dict — critically, *excluding the secret `device_code`* (which
   the server uses internally to poll Microsoft Identity but must
   never be returned to the agent / surfaced in tool responses).

That's what this module provides. **What it does NOT provide:**
the asyncio task orchestration, the progress-callback machinery,
or the actual polling loop. Those live in the consumer because
each MCP server's event-loop integration differs (FastMCP, stdio
vs SSE transport, lifecycle hooks). The consumer wraps
`request_device_code()` + `poll_for_token()` from `device_code.py`
in its own `asyncio.create_task(...)`, attaches the `Task` to the
`LoginSession.task` field, and updates `status` + `signed_in_user_upn`
+ `error` as the poll progresses.

**Critical limitation**: sessions live in process memory only. A
server restart drops all in-flight sessions. Persisting them is
non-trivial (an `asyncio.Task` cannot be serialised; on restart
the new task would have to resume polling against the original
device_code, which is also moot since Microsoft device codes
expire ~15 min from issuance) and is deferred. Document this in
the consumer's README.

## Idempotency rules a consumer typically implements

The consumer's `_login_begin` MCP tool is the place to enforce
these — this registry is just a dict:

| Scenario | Behavior |
|---|---|
| pending session for X exists, no force | Return existing session unchanged |
| pending session for X exists, force=True | Cancel existing task, drop, start fresh |
| terminal session for X (success/expired/...) | Drop, start fresh |
| concurrent calls from two clients | First-write-wins on the dict |

The registry's atomic `put_if_absent()` helper is the primitive
for the first/last rows.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

LoginStatus = Literal["pending", "success", "expired", "failed", "cancelled"]


@dataclass
class LoginSession:
    """One in-flight (or recently-terminated) Device Code login flow.

    Mutable: the consumer's poll task updates `status` /
    `signed_in_user_upn` / `error` as the flow progresses.

    `device_code` is the secret token used to poll Microsoft Identity.
    It is **server-side only**: never include it in MCP tool output.
    Use `public_view()` (or build a dict by hand that excludes it) to
    return the user-facing fields to the agent.

    `task` is intentionally typed as `Any` because consumers vary —
    `asyncio.Task[None]` is the typical choice but other event-loop
    integrations may store something else. The lib only cares that
    callers can call `.cancel()` on it via duck-typing if/when they
    implement the consumer-side `force=True` semantic.
    """

    session_id: str
    profile: str
    device_code: str  # SECRET — never returned in tool output
    user_code: str
    verification_url: str
    verification_url_complete: str | None
    expires_at: datetime
    interval_s: int
    status: LoginStatus = "pending"
    signed_in_user_upn: str | None = None
    error: dict[str, Any] | None = None
    task: Any | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def new(
        cls,
        *,
        profile: str,
        device_code: str,
        user_code: str,
        verification_url: str,
        verification_url_complete: str | None,
        expires_at: datetime,
        interval_s: int,
    ) -> LoginSession:
        """Construct a new pending session with a fresh uuid4 session_id."""
        return cls(
            session_id=str(uuid.uuid4()),
            profile=profile,
            device_code=device_code,
            user_code=user_code,
            verification_url=verification_url,
            verification_url_complete=verification_url_complete,
            expires_at=expires_at,
            interval_s=interval_s,
        )

    def time_remaining_s(self, *, now: datetime | None = None) -> int:
        """Seconds until `expires_at`. Clamped to 0 below."""
        ref = now if now is not None else datetime.now(UTC)
        delta = (self.expires_at - ref).total_seconds()
        return max(0, int(delta))


class LoginSessionRegistry:
    """In-process registry of `LoginSession` keyed by profile.

    Thread-safe mutations via a `threading.RLock` — the lock guards
    every dict access so callers from threads + asyncio coroutines
    can both use the same registry instance safely. Reads are also
    locked for atomicity (a `get()` followed by a `put()` would
    otherwise race with a concurrent `put_if_absent()`).

    NOT persisted to disk. NOT shared across processes.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, LoginSession] = {}
        self._lock = threading.RLock()

    def get(self, profile: str) -> LoginSession | None:
        """Return the session for `profile`, or None if none exists."""
        with self._lock:
            return self._sessions.get(profile)

    def put(self, session: LoginSession) -> None:
        """Insert or replace the session for `session.profile`.

        Use `put_if_absent` if you need first-write-wins semantics.
        """
        with self._lock:
            self._sessions[session.profile] = session

    def put_if_absent(self, session: LoginSession) -> LoginSession:
        """Insert iff no session exists yet for `session.profile`.

        Returns the session that ended up in the dict — either the
        newly-inserted one (when no prior existed) or the existing
        one (when there was a race). Useful for the idempotency
        rule "concurrent calls from two clients: first-write-wins".
        """
        with self._lock:
            existing = self._sessions.get(session.profile)
            if existing is not None:
                return existing
            self._sessions[session.profile] = session
            return session

    def remove(self, profile: str) -> LoginSession | None:
        """Remove and return the session for `profile`, or None."""
        with self._lock:
            return self._sessions.pop(profile, None)

    def all_pending(self) -> list[LoginSession]:
        """Snapshot of all sessions currently in `pending` status.

        Useful for a server-shutdown hook that cancels in-flight
        polling tasks before exiting.
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.status == "pending"]

    def all_sessions(self) -> list[LoginSession]:
        """Snapshot of every session, regardless of status."""
        with self._lock:
            return list(self._sessions.values())

    def clear(self) -> None:
        """Drop every session. Test-only escape hatch."""
        with self._lock:
            self._sessions.clear()


def public_view(session: LoginSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Return a tool-output-friendly dict for a `LoginSession`.

    **Critically: omits `device_code` and the opaque `task` handle.**
    These are server-side state; surfacing them to the agent (and
    through it to the user / logs) would be a security leak.

    The shape mirrors what the integrated-login RFC's
    `<prefix>_login_status` tool returns when the status is
    `pending`. Consumers can build a richer view (e.g., adding
    `signed_in_user_upn` derivation logic) by extending this dict.
    """
    return {
        "session_id": session.session_id,
        "profile": session.profile,
        "user_code": session.user_code,
        "verification_url": session.verification_url,
        "verification_url_complete": session.verification_url_complete,
        "expires_at": session.expires_at.isoformat(),
        "interval_s": session.interval_s,
        "status": session.status,
        "time_remaining_s": session.time_remaining_s(now=now),
        "signed_in_user_upn": session.signed_in_user_upn,
        "error": session.error,
    }
