"""Password storage: PBKDF2 hashes, constant-time checks, legacy upgrade path."""
import hashlib

from app.db import hash_password, verify_password, password_needs_upgrade


def test_hash_format_and_salt():
    a, b = hash_password("s3cret-pass"), hash_password("s3cret-pass")
    assert a.startswith("pbkdf2_sha256$")
    algo, iterations, salt, digest = a.split("$")
    assert int(iterations) >= 100_000
    assert len(salt) == 32 and len(digest) == 64
    assert a != b, "same password must get a different salt each time"


def test_verify_correct_and_wrong_password():
    stored = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("s3cret-pasS", stored)
    assert not verify_password("", stored)


def test_plain_text_never_stored():
    assert "s3cret-pass" not in hash_password("s3cret-pass")


def test_legacy_sha256_hashes_still_verify_and_need_upgrade():
    salt = "abc123"
    legacy = f"{salt}:" + hashlib.sha256(f"{salt}:old-password".encode()).hexdigest()
    assert verify_password("old-password", legacy)
    assert not verify_password("wrong", legacy)
    assert password_needs_upgrade(legacy)
    assert not password_needs_upgrade(hash_password("x" * 10))


def test_malformed_hash_is_rejected_not_crashing():
    for junk in ("", "nonsense", "pbkdf2_sha256$x$y", "a:b:c"):
        assert verify_password("anything", junk) is False
