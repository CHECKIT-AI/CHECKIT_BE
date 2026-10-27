import json
from types import SimpleNamespace
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt
import pytest

from app.errors import APIError
from app.oauth_providers import verify_google_identity


@pytest.fixture(scope="module")
def signing_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return crypt.RSASigner.from_string(private, key_id="test-key"), public


def signed_token(monkeypatch, signing_keys, **changes):
    signer, public = signing_keys

    class Transport:
        session = SimpleNamespace(close=lambda: None)

        def __call__(self, url, **kwargs):
            assert kwargs["timeout"] == 10
            return SimpleNamespace(status=200, data=json.dumps({"test-key": public.decode()}).encode())

    monkeypatch.setattr("app.oauth_providers.GoogleRequest", Transport)
    now = int(time.time())
    payload = dict(iss="https://accounts.google.com", aud="client", iat=now, exp=now + 300,
                   sub="google-subject", nonce="nonce", email="user@example.com", email_verified=True)
    payload.update(changes)
    return jwt.encode(signer, payload).decode()


def test_google_signature_and_claims_verified(monkeypatch, signing_keys):
    raw = signed_token(monkeypatch, signing_keys)
    identity = verify_google_identity(raw, "client", "nonce")
    assert identity.subject == "google-subject"
    assert identity.email == "user@example.com"


@pytest.mark.parametrize("changes", [
    {"iss": "https://evil.example"}, {"aud": "other-client"}, {"exp": 1},
    {"nonce": "other-nonce"}, {"azp": "other-client"}, {"sub": ""},
])
def test_google_invalid_claims_rejected(monkeypatch, signing_keys, changes):
    raw = signed_token(monkeypatch, signing_keys, **changes)
    with pytest.raises(APIError):
        verify_google_identity(raw, "client", "nonce")


def test_google_tampered_signature_rejected(monkeypatch, signing_keys):
    raw = signed_token(monkeypatch, signing_keys)
    header, payload, signature = raw.split(".")
    tampered = header + "." + payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(APIError):
        verify_google_identity(tampered, "client", "nonce")
