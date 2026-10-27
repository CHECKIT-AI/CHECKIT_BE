import os
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from pydantic import SecretStr
import pytest

from app.oauth_providers import SocialIdentity
from test_auth_database import db_case  # shared force-rollback fixture

pytestmark = pytest.mark.skipif(os.environ.get("CHECKIT_RUN_DB_TESTS") != "1",
                                reason="실제 DB 검증은 명시적으로 활성화할 때만 실행")


def test_social_signup_reuse_and_provider_separation(db_case):
    conn, client, users, sessions, raw_guest, contracts, password = db_case
    settings = client.app.state.settings
    settings.google_client_id = SecretStr("test-client")
    settings.google_client_secret = SecretStr("test-secret")
    settings.kakao_rest_api_key = SecretStr("test-client")
    settings.kakao_client_secret = SecretStr("test-secret")
    subject = "oauth-test-" + uuid4().hex

    class MockProvider:
        def exchange(self, settings, provider, code, context):
            return SocialIdentity(subject, users[0][1])

    client.app.state.oauth_client = MockProvider()
    ids = {}
    for provider in ("google", "kakao", "google"):
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        start = client.post(f"/api/auth/oauth/{provider}/start", json={"return_path": "/"},
                            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf})
        assert start.status_code == 200
        state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
        callback = client.get(f"/api/auth/oauth/{provider}/callback?state={state}&code=test-code", follow_redirects=False)
        assert "oauth_status=success" in callback.headers["location"]
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        user = me.json()["user"]
        assert user["provider"] == provider.upper()
        assert user["id"] != str(users[0][0])
        if provider in ids:
            assert user["id"] == ids[provider]
        ids[provider] = user["id"]
    assert ids["kakao"] != ids["google"]
    assert conn.execute("SELECT count(*) AS n FROM checkit.auth_identities WHERE provider_subject=%s",
                        (subject,)).fetchone()["n"] == 2
