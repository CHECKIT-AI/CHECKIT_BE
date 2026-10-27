from contextlib import contextmanager
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.config import Settings
from app.errors import APIError
from app.main import create_app
from app.oauth_providers import SocialIdentity
from app.oauth_state import OAuthStateStore
from app.security import new_token, token_hash


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def execute(self, sql, parameters=None):
        self.calls.append((sql, parameters))
        assert self.rows, "Unexpected SQL"
        return Result(self.rows.pop(0))

    @contextmanager
    def transaction(self):
        yield


class Pool:
    def __init__(self, conn=None, fail_commit=False):
        self.conn, self.fail_commit = conn, fail_commit

    def open(self):
        pass

    def close(self):
        pass

    @contextmanager
    def connection(self):
        assert self.conn is not None, "DB must not be called"
        yield self.conn
        if self.fail_commit:
            raise psycopg.OperationalError("private-secret")


def configured(**changes):
    data = dict(csrf_secret="test-secret-" * 4, allowed_origins=["http://testserver"],
                kakao_rest_api_key="private-kakao", kakao_client_secret="private-secret",
                google_client_id="test-google-client", google_client_secret="private-secret")
    data.update(changes)
    return Settings(_env_file=None, **data)


def start(client, provider="google", **payload):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(f"/api/auth/oauth/{provider}/start", json=payload,
                           headers={"Origin": "http://testserver", "X-CSRF-Token": csrf})
    assert response.status_code == 200
    return parse_qs(urlsplit(response.json()["authorization_url"]).query)


def test_google_authorization_uses_state_nonce_pkce():
    with TestClient(create_app(configured(), Pool())) as client:
        parameters = start(client)
        assert parameters["redirect_uri"] == ["http://localhost:8000/api/auth/oauth/google/callback"]
        assert parameters["scope"] == ["openid email profile"]
        assert parameters["code_challenge_method"] == ["S256"]
        assert len(parameters["code_challenge"][0]) == 43
        assert len(parameters["state"][0]) == 43
        assert len(parameters["nonce"][0]) == 43
        assert "private-secret" not in str(parameters)
        assert client.cookies.get("checkit_oauth")


@pytest.mark.parametrize("path", ["https://evil.example", "//evil.example", "/%2fevil.example", "/\\evil.example", "/\r\nLocation:evil"])
def test_external_or_encoded_return_path_rejected(path):
    with TestClient(create_app(configured(), Pool())) as client:
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        response = client.post("/api/auth/oauth/google/start", json={"return_path": path},
                               headers={"Origin": "http://testserver", "X-CSRF-Token": csrf})
        assert response.status_code == 422


def test_state_provider_browser_identity_and_replay():
    store = OAuthStateStore()
    browser, member, guest = new_token(), new_token(), new_token()
    state, context = store.create("google", browser, member, guest, "/", None)
    for provider, b, m, g in [("kakao", browser, member, guest), ("google", new_token(), member, guest),
                              ("google", browser, new_token(), guest), ("google", browser, member, "")]:
        with pytest.raises(APIError):
            store.consume(state, provider, b, m, g)
    assert store.consume(state, "google", browser, member, guest) == context
    with pytest.raises(APIError):
        store.consume(state, "google", browser, member, guest)


def test_expired_state_and_store_capacity():
    store = OAuthStateStore(ttl=-1)
    browser = new_token()
    state, _ = store.create("google", browser, "", "", "/", None)
    with pytest.raises(APIError):
        store.consume(state, "google", browser, "", "")
    store = OAuthStateStore(capacity=1)
    store.create("google", browser, "", "", "/", None)
    with pytest.raises(APIError) as error:
        store.create("google", browser, "", "", "/", None)
    assert error.value.status == 429


def test_provider_denial_is_sanitized_and_state_consumed():
    with TestClient(create_app(configured(), Pool())) as client:
        state = start(client, "kakao")["state"][0]
        url = f"/api/auth/oauth/kakao/callback?state={state}&error=access_denied&error_description=private-secret"
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 303
        assert "OAUTH_DENIED" in response.headers["location"]
        assert "private-secret" not in str(response.headers)
        assert "checkit_session" not in client.cookies
        assert "INVALID_OAUTH_STATE" in client.get(url, follow_redirects=False).headers["location"]


def test_other_browser_cannot_finish_flow():
    app = create_app(configured(), Pool())
    with TestClient(app) as first, TestClient(app) as other:
        state = start(first)["state"][0]
        response = other.get(f"/api/auth/oauth/google/callback?state={state}&code=private-code", follow_redirects=False)
        assert "INVALID_OAUTH_STATE" in response.headers["location"]
        assert "private-code" not in str(response.headers)


class FakeProvider:
    def __init__(self, identity):
        self.identity = identity
        self.calls = 0

    def exchange(self, settings, provider, code, context):
        self.calls += 1
        return self.identity


@pytest.mark.parametrize("provider", ["google", "kakao"])
def test_first_login_creates_independent_identity_and_hashed_session(provider):
    owner_id = uuid4()
    conn = Connection([None, None, {"id": owner_id}, None, None])
    app = create_app(configured(), Pool(conn))
    app.state.oauth_client = FakeProvider(SocialIdentity("subject", "same@example.com" if provider == "google" else None))
    with TestClient(app) as client:
        state = start(client, provider)["state"][0]
        url = f"/api/auth/oauth/{provider}/callback?state={state}&code=private-code"
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 303
        assert "oauth_status=success" in response.headers["location"]
        raw = client.cookies.get("checkit_session")
        assert raw and raw not in response.headers["location"]
        assert conn.calls[-1][1][1] == token_hash(raw)
        assert conn.calls[1][1] == (provider.upper(), "subject")
        assert "provider_subject=%s" in conn.calls[1][0]
        assert "WHERE email" not in conn.calls[1][0]
        assert "checkit_oauth" not in client.cookies
        assert "INVALID_OAUTH_STATE" in client.get(url, follow_redirects=False).headers["location"]
        assert app.state.oauth_client.calls == 1


def test_failed_database_commit_never_sets_session_cookie():
    conn = Connection([None, {"id": uuid4(), "status": "ACTIVE"}, None])
    app = create_app(configured(), Pool(conn, fail_commit=True))
    app.state.oauth_client = FakeProvider(SocialIdentity("subject"))
    with TestClient(app) as client:
        state = start(client)["state"][0]
        response = client.get(f"/api/auth/oauth/google/callback?state={state}&code=code", follow_redirects=False)
        assert "DATABASE_UNAVAILABLE" in response.headers["location"]
        assert "private-secret" not in str(response.headers)
        assert "checkit_session" not in client.cookies


def test_dev_test_page_and_missing_config():
    with TestClient(create_app(configured(google_client_secret=""), Pool())) as client:
        assert client.get("/api/auth/oauth/test").status_code == 200
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        response = client.post("/api/auth/oauth/google/start", json={},
                               headers={"Origin": "http://testserver", "X-CSRF-Token": csrf})
        assert response.status_code == 503


def test_callback_query_is_removed_from_access_log_scope():
    import asyncio
    from app.oauth import OAuthCallbackRedactionMiddleware
    seen = {}

    async def app(scope, receive, send):
        seen.update(scope)

    scope = {"type": "http", "path": "/api/auth/oauth/google/callback", "query_string": b"code=private-code&state=x"}
    asyncio.run(OAuthCallbackRedactionMiddleware(app)(scope, None, None))
    assert scope["query_string"] == b""
    assert seen["oauth_callback_query"] == b"code=private-code&state=x"
