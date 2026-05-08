# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Token persistence backends.

Three implementations behind a `TokenStore` Protocol:

- `KeyringTokenStore`: uses python-keyring, which delegates to the
  active OS keyring (Secret Service / Keychain / Credential Locker).
- `PlainFileTokenStore`: JSON at `<base_dir>/<profile>/token.json`
  with mode 0600. Same security model as `gh auth`, `aws configure`,
  `npm login`, `~/.ssh/id_rsa`: trust the local user account.
- `EncryptedFileTokenStore`: cryptography.fernet ciphertext on disk
  with a Scrypt-derived key from a caller-supplied passphrase.

**Prefix-agnostic API.** Unlike sharepoint-mcp's predecessor of
this module, the constructors take **explicit** `service_name` /
`base_dir` / `passphrase` arguments — no env-var reading. Each
consumer (sharepoint-mcp, outlook-mcp) reads its own env-var
conventions (`SP_TOKEN_STORE`, `OUTLOOK_TOKEN_STORE`, etc.) and
instantiates the right backend.

The auto-selection logic from sharepoint-mcp's `get_token_store()`
also stays in the consumer for the same reason — picking a backend
is a server-policy decision. We expose `is_real_keyring_backend()`
as a public helper so consumers don't have to re-implement the
detection of a real OS keyring vs. python-keyring's `fail.Keyring`
placeholder.

Rationale for the three-backend design: see the spike doc in
sharepoint-mcp at `docs/spikes/2026-05-06-keyring-vs-encrypted-file.md`.
"""

from __future__ import annotations

import secrets
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Protocol

import keyring
import keyring.backend
import keyring.backends.fail
import keyring.errors
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Scrypt parameters chosen for ~50ms KDF on a typical laptop —
# memory-hard enough to defeat GPU brute force on a leaked file
# while keeping CLI startup snappy.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16


class NoUsableTokenStoreError(RuntimeError):
    """Raised when an EncryptedFileTokenStore is constructed with an empty
    passphrase, or when a consumer's auto-pick logic runs out of options.

    The consumer's auto-pick may also raise this when an explicit env-var
    override (e.g. `SP_TOKEN_STORE=encrypted-file`) is set without the
    passphrase — that error path lives in the consumer.
    """


class TokenStore(Protocol):
    """Persistence interface for OAuth tokens, namespaced by profile.

    Implementations must be safe to instantiate multiple times against
    the same underlying storage; cross-process concurrent writes are
    NOT guaranteed safe in v0.x — file-based backends rely on OS atomic
    rename, but no inter-process lock is acquired around read-modify-
    write sequences. (Adding that is the integrated-login flow's
    `concurrent_login_attempt` story; see `login_session` module.)
    """

    def get(self, profile: str) -> bytes | None:
        """Return stored bytes for `profile`, or None if not stored."""
        ...

    def set(self, profile: str, value: bytes) -> None:
        """Store `value` under `profile`. Overwrites if it exists."""
        ...

    def delete(self, profile: str) -> None:
        """Remove stored value for `profile`. No-op if not present."""
        ...


class KeyringTokenStore:
    """python-keyring-backed token store.

    Stores tokens as the password value under a `(service_name, profile)`
    key pair in the active OS keyring. Requires a real backend; calls
    raise `keyring.errors.NoKeyringError` on `fail.Keyring`.

    `service_name` is the keyring service identifier under which entries
    are filed — typically the consumer's package name (e.g.
    `"sharepoint-mcp"`, `"outlook-mcp"`). Distinct service names keep
    profiles from colliding across consumers on the same OS user.
    """

    def __init__(self, *, service_name: str) -> None:
        if not service_name or not service_name.strip():
            raise ValueError("KeyringTokenStore requires a non-empty service_name")
        self._service = service_name

    def get(self, profile: str) -> bytes | None:
        value = keyring.get_password(self._service, profile)
        return value.encode() if value is not None else None

    def set(self, profile: str, value: bytes) -> None:
        keyring.set_password(self._service, profile, value.decode())

    def delete(self, profile: str) -> None:
        try:
            keyring.delete_password(self._service, profile)
        except keyring.errors.PasswordDeleteError:
            # Already absent — match Protocol's "no-op if not present" contract.
            pass


class PlainFileTokenStore:
    """Plain JSON file token store, mode 0600.

    Universal fallback used when no OS keyring is available and the
    user hasn't opted into encrypted-file mode. Same security model
    as `gh auth login`, `aws configure`, `npm login`,
    `~/.ssh/id_rsa`: trust the local user account.

    Layout per profile:

        <base_dir>/<profile>/token.json   JSON of the CachedToken dict

    File mode is 0o600 (owner-only) on POSIX. Directory is created
    on demand. `base_dir` is required — typically
    `~/.cache/<your-app>` (consumer's choice).
    """

    def __init__(self, *, base_dir: Path) -> None:
        self._base_dir = base_dir

    def _profile_dir(self, profile: str) -> Path:
        d = self._base_dir / profile
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get(self, profile: str) -> bytes | None:
        token_file = self._profile_dir(profile) / "token.json"
        if not token_file.exists():
            return None
        return token_file.read_bytes()

    def set(self, profile: str, value: bytes) -> None:
        token_file = self._profile_dir(profile) / "token.json"
        token_file.write_bytes(value)
        token_file.chmod(0o600)

    def delete(self, profile: str) -> None:
        try:
            (self._profile_dir(profile) / "token.json").unlink()
        except FileNotFoundError:
            pass


class EncryptedFileTokenStore:
    """Fernet-encrypted-file token store.

    Layout per profile under `base_dir`:

        <base_dir>/<profile>/token.enc    Fernet ciphertext
        <base_dir>/<profile>/token.salt   16 random bytes (Scrypt salt)

    Both files are mode 0o600 (owner-only) on POSIX.

    `passphrase` is held in this object's memory for its lifetime.
    Callers that want stricter handling (re-read from env per call,
    wipe after use, etc.) can subclass and override `_passphrase()`.

    A wrong passphrase produces `cryptography.fernet.InvalidToken`
    on `get()`.
    """

    def __init__(self, *, base_dir: Path, passphrase: str) -> None:
        if not passphrase:
            raise NoUsableTokenStoreError(
                "EncryptedFileTokenStore requires a non-empty passphrase",
            )
        self._base_dir = base_dir
        self._passphrase_value = passphrase

    def _passphrase(self) -> bytes:
        return self._passphrase_value.encode()

    def _profile_dir(self, profile: str) -> Path:
        d = self._base_dir / profile
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _derive_key(self, salt: bytes) -> bytes:
        kdf = Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
        return urlsafe_b64encode(kdf.derive(self._passphrase()))

    def get(self, profile: str) -> bytes | None:
        d = self._profile_dir(profile)
        token_file = d / "token.enc"
        salt_file = d / "token.salt"
        if not token_file.exists() or not salt_file.exists():
            return None
        salt = salt_file.read_bytes()
        ciphertext = token_file.read_bytes()
        return Fernet(self._derive_key(salt)).decrypt(ciphertext)

    def set(self, profile: str, value: bytes) -> None:
        d = self._profile_dir(profile)
        salt_file = d / "token.salt"
        if salt_file.exists():
            salt = salt_file.read_bytes()
        else:
            salt = secrets.token_bytes(_SALT_BYTES)
            salt_file.write_bytes(salt)
            salt_file.chmod(0o600)
        ciphertext = Fernet(self._derive_key(salt)).encrypt(value)
        token_file = d / "token.enc"
        token_file.write_bytes(ciphertext)
        token_file.chmod(0o600)

    def delete(self, profile: str) -> None:
        d = self._profile_dir(profile)
        for name in ("token.enc", "token.salt"):
            try:
                (d / name).unlink()
            except FileNotFoundError:
                pass


def is_real_keyring_backend(backend: keyring.backend.KeyringBackend) -> bool:
    """Return True if `backend` is a real OS keychain integration.

    Excludes `fail.Keyring` (placeholder when no backend is available)
    and any backend whose class name suggests plaintext storage
    (`keyrings.alt.file.PlaintextKeyring` and friends).

    Consumers' auto-pick logic uses this to decide whether to default
    to `KeyringTokenStore` or fall through to a file-based backend.
    Use it like:

        if is_real_keyring_backend(keyring.get_keyring()):
            store = KeyringTokenStore(service_name="my-mcp-server")
        else:
            store = PlainFileTokenStore(base_dir=...)
    """
    if isinstance(backend, keyring.backends.fail.Keyring):
        return False
    if "Plaintext" in type(backend).__name__:
        return False
    return True
