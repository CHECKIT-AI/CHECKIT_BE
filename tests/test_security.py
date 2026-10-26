import time

import pytest

from app.errors import APIError
from app.security import (RateLimiter, hash_password, new_token, sign_csrf,
                          verify_csrf, verify_password)


def test_password_hash_uses_salt_and_rejects_wrong_password():
    first = hash_password("correct password")
    second = hash_password("correct password")
    assert first != second
    assert "correct password" not in first
    assert verify_password("correct password", first)
    assert not verify_password("wrong password", first)
    assert not verify_password("correct password", "not-a-hash")


def test_csrf_binds_browser_and_both_identities():
    context, member, guest = new_token(), new_token(), new_token()
    token = sign_csrf("secret" * 8, context, member, guest)
    assert verify_csrf("secret" * 8, context, member, guest, token)
    assert not verify_csrf("secret" * 8, new_token(), member, guest, token)
    assert not verify_csrf("secret" * 8, context, new_token(), guest, token)
    assert not verify_csrf("secret" * 8, context, member, new_token(), token)
    assert not verify_csrf("different-key", context, member, guest, token)
    assert not verify_csrf("secret" * 8, context, member, guest, token + "tampered")


def test_csrf_expiry_and_malformed_tokens():
    context = new_token()
    expired = sign_csrf("key", context, "", "", now=int(time.time()) - 601)
    future = sign_csrf("key", context, "", "", now=int(time.time()) + 60)
    for token in (expired, future, "", "not.a.token", "x" * 1000):
        assert not verify_csrf("key", context, "", "", token)


def test_rate_limit_rejects_excess_attempts():
    limiter = RateLimiter()
    limiter.check("account", limit=2)
    limiter.check("account", limit=2)
    with pytest.raises(APIError) as error:
        limiter.check("account", limit=2)
    assert error.value.status == 429
