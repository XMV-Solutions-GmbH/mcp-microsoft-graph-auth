# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the token-store backends.

All tests run offline. The KeyringTokenStore tests use an in-memory
fake; the file-backed tests use pytest's `tmp_path`.

Note: the env-var-driven auto-pick logic that lived in
sharepoint-mcp's `get_token_store()` is NOT extracted to this
library — it stays in the consumer. We test only the backend
implementations + the `is_real_keyring_backend` helper here.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import keyring
import keyring.backend
import keyring.backends.fail
import keyring.errors
import pytest
from cryptography.fernet import InvalidToken

from mcp_microsoft_graph_auth.token_store import (
    EncryptedFileTokenStore,
    KeyringTokenStore,
    NoUsableTokenStoreError,
    PlainFileTokenStore,
    is_real_keyring_backend,
)

SERVICE_NAME = "test-service"


# ---------------------------------------------------------------------
# KeyringTokenStore — exercised against an in-memory fake backend
# ---------------------------------------------------------------------


class _FakeKeyringBackend:
    """In-memory keyring substitute. Mimics the three module-level functions."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        try:
            del self.store[(service, key)]
        except KeyError as exc:
            raise keyring.errors.PasswordDeleteError(str(exc)) from exc


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeKeyringBackend]:
    fake = _FakeKeyringBackend()
    monkeypatch.setattr(keyring, "get_password", fake.get_password)
    monkeypatch.setattr(keyring, "set_password", fake.set_password)
    monkeypatch.setattr(keyring, "delete_password", fake.delete_password)
    yield fake


def test_keyring_set_get_roundtrip(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore(service_name=SERVICE_NAME)
    store.set("profile-a", b"secret-bytes-1")
    assert store.get("profile-a") == b"secret-bytes-1"


def test_keyring_get_unknown_profile(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore(service_name=SERVICE_NAME)
    assert store.get("never-stored") is None


def test_keyring_delete(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore(service_name=SERVICE_NAME)
    store.set("profile-a", b"x")
    store.delete("profile-a")
    assert store.get("profile-a") is None


def test_keyring_delete_no_op_on_missing(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore(service_name=SERVICE_NAME)
    store.delete("never-stored")  # must not raise


def test_keyring_per_profile_isolation(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore(service_name=SERVICE_NAME)
    store.set("profile-a", b"value-a")
    store.set("profile-b", b"value-b")
    assert store.get("profile-a") == b"value-a"
    assert store.get("profile-b") == b"value-b"


def test_keyring_service_name_isolates_consumers(
    fake_keyring: _FakeKeyringBackend,
) -> None:
    """Two consumers using different service_names see independent storage."""
    del fake_keyring
    store_a = KeyringTokenStore(service_name="service-a")
    store_b = KeyringTokenStore(service_name="service-b")
    store_a.set("default", b"a's secret")
    store_b.set("default", b"b's secret")
    assert store_a.get("default") == b"a's secret"
    assert store_b.get("default") == b"b's secret"


def test_keyring_rejects_empty_service_name() -> None:
    with pytest.raises(ValueError, match="non-empty service_name"):
        KeyringTokenStore(service_name="")


def test_keyring_rejects_blank_service_name() -> None:
    with pytest.raises(ValueError, match="non-empty service_name"):
        KeyringTokenStore(service_name="   ")


# ---------------------------------------------------------------------
# EncryptedFileTokenStore — tmp_path + explicit passphrase
# ---------------------------------------------------------------------


@pytest.fixture
def file_store(tmp_path: Path) -> EncryptedFileTokenStore:
    return EncryptedFileTokenStore(base_dir=tmp_path, passphrase="test-passphrase-correct")


def test_file_set_get_roundtrip(file_store: EncryptedFileTokenStore) -> None:
    file_store.set("profile-a", b"refresh-token-payload")
    assert file_store.get("profile-a") == b"refresh-token-payload"


def test_file_get_unknown_profile(file_store: EncryptedFileTokenStore) -> None:
    assert file_store.get("never-stored") is None


def test_file_delete(file_store: EncryptedFileTokenStore) -> None:
    file_store.set("profile-a", b"x")
    file_store.delete("profile-a")
    assert file_store.get("profile-a") is None


def test_file_delete_no_op_on_missing(file_store: EncryptedFileTokenStore) -> None:
    file_store.delete("never-stored")


def test_file_per_profile_isolation(file_store: EncryptedFileTokenStore) -> None:
    file_store.set("profile-a", b"value-a")
    file_store.set("profile-b", b"value-b")
    assert file_store.get("profile-a") == b"value-a"
    assert file_store.get("profile-b") == b"value-b"


def test_file_wrong_passphrase_rejected(tmp_path: Path) -> None:
    EncryptedFileTokenStore(base_dir=tmp_path, passphrase="right-pass").set("profile-a", b"secret")
    with pytest.raises(InvalidToken):
        EncryptedFileTokenStore(base_dir=tmp_path, passphrase="wrong-pass").get("profile-a")


def test_file_empty_passphrase_rejected_at_construction(tmp_path: Path) -> None:
    """Construction-time validation surfaces the error before any I/O."""
    with pytest.raises(NoUsableTokenStoreError, match="non-empty passphrase"):
        EncryptedFileTokenStore(base_dir=tmp_path, passphrase="")


def test_file_permissions_owner_only(tmp_path: Path) -> None:
    EncryptedFileTokenStore(base_dir=tmp_path, passphrase="p").set("profile-a", b"v")
    enc = tmp_path / "profile-a" / "token.enc"
    salt = tmp_path / "profile-a" / "token.salt"
    assert (enc.stat().st_mode & 0o777) == 0o600
    assert (salt.stat().st_mode & 0o777) == 0o600


def test_file_salt_persists_across_instances(tmp_path: Path) -> None:
    """Subsequent set() calls must reuse the existing salt, not regenerate it."""
    EncryptedFileTokenStore(base_dir=tmp_path, passphrase="p").set("profile-a", b"v1")
    salt1 = (tmp_path / "profile-a" / "token.salt").read_bytes()
    EncryptedFileTokenStore(base_dir=tmp_path, passphrase="p").set("profile-a", b"v2")
    salt2 = (tmp_path / "profile-a" / "token.salt").read_bytes()
    assert salt1 == salt2


def test_file_passphrase_change_requires_resync(tmp_path: Path) -> None:
    """Changing the passphrase doesn't auto-rekey existing entries — get
    raises InvalidToken. Re-setting under the new passphrase resets."""
    EncryptedFileTokenStore(base_dir=tmp_path, passphrase="old").set("p", b"v1")
    new_store = EncryptedFileTokenStore(base_dir=tmp_path, passphrase="new")
    with pytest.raises(InvalidToken):
        new_store.get("p")
    # ... but a fresh set() under the new passphrase wipes the old ciphertext
    # in-place (salt is reused); subsequent get() with the new passphrase works.
    new_store.set("p", b"v2")
    assert new_store.get("p") == b"v2"


# ---------------------------------------------------------------------
# PlainFileTokenStore — tmp_path, no passphrase
# ---------------------------------------------------------------------


@pytest.fixture
def plain_store(tmp_path: Path) -> PlainFileTokenStore:
    return PlainFileTokenStore(base_dir=tmp_path)


def test_plain_set_get_roundtrip(plain_store: PlainFileTokenStore) -> None:
    plain_store.set("profile-a", b'{"access_token": "AT"}')
    assert plain_store.get("profile-a") == b'{"access_token": "AT"}'


def test_plain_get_unknown_profile(plain_store: PlainFileTokenStore) -> None:
    assert plain_store.get("never-stored") is None


def test_plain_delete(plain_store: PlainFileTokenStore) -> None:
    plain_store.set("profile-a", b"x")
    plain_store.delete("profile-a")
    assert plain_store.get("profile-a") is None


def test_plain_delete_no_op_on_missing(plain_store: PlainFileTokenStore) -> None:
    plain_store.delete("never-stored")


def test_plain_per_profile_isolation(plain_store: PlainFileTokenStore) -> None:
    plain_store.set("profile-a", b"value-a")
    plain_store.set("profile-b", b"value-b")
    assert plain_store.get("profile-a") == b"value-a"
    assert plain_store.get("profile-b") == b"value-b"


def test_plain_file_permissions_owner_only(tmp_path: Path) -> None:
    PlainFileTokenStore(base_dir=tmp_path).set("profile-a", b"v")
    f = tmp_path / "profile-a" / "token.json"
    assert (f.stat().st_mode & 0o777) == 0o600


def test_plain_creates_nested_directories(tmp_path: Path) -> None:
    """base_dir doesn't have to exist; profile dir is created on demand."""
    deep = tmp_path / "does" / "not" / "exist" / "yet"
    PlainFileTokenStore(base_dir=deep).set("profile", b"v")
    assert (deep / "profile" / "token.json").exists()


# ---------------------------------------------------------------------
# is_real_keyring_backend — public helper for consumers' auto-pick
# ---------------------------------------------------------------------


def test_is_real_keyring_rejects_fail_backend() -> None:
    assert is_real_keyring_backend(keyring.backends.fail.Keyring()) is False


def test_is_real_keyring_rejects_plaintext_name() -> None:
    class PlaintextKeyring(keyring.backend.KeyringBackend):
        priority = -1.0

        def get_password(self, service: str, username: str) -> str | None:
            return None

        def set_password(self, service: str, username: str, password: str) -> None:
            pass

        def delete_password(self, service: str, username: str) -> None:
            pass

    assert is_real_keyring_backend(PlaintextKeyring()) is False


def test_is_real_keyring_accepts_other_backend() -> None:
    class FakeSecretService(keyring.backend.KeyringBackend):
        priority = 5.0

        def get_password(self, service: str, username: str) -> str | None:
            return None

        def set_password(self, service: str, username: str, password: str) -> None:
            pass

        def delete_password(self, service: str, username: str) -> None:
            pass

    assert is_real_keyring_backend(FakeSecretService()) is True
