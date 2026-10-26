from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.access import Actor, claim_contract, current_actor, member, require_contract
from app.config import Settings
from app.errors import APIError
from app.main import create_app
from app.security import new_token, token_hash


class Result:
    def __init__(self, row=None, rows=None):
        self.row, self.rows = row, rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def execute(self, sql, parameters=None):
        self.calls.append((sql, parameters))
        if not self.responses:
            raise AssertionError("Unexpected database query")
        return Result(self.responses.pop(0))

    @contextmanager
    def transaction(self):
        yield

    def commit(self):
        pass


class Pool:
    def __init__(self, conn):
        self.conn = conn

    def open(self):
        pass

    def close(self):
        pass

    @contextmanager
    def connection(self):
        yield self.conn


def settings(**overrides):
    return Settings(_env_file=None, csrf_secret="a" * 43,
                    allowed_origins=["http://testserver"], **overrides)


def csrf_headers(client):
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def test_signup_requires_csrf_and_does_not_touch_database():
    conn = Connection()
    with TestClient(create_app(settings(), Pool(conn))) as client:
        response = client.post("/api/auth/signup", json={"email": "a@example.com", "password": "private-password"})
        assert response.status_code == 403
        assert not conn.calls


def test_origin_and_cross_browser_csrf_rejected():
    app = create_app(settings(), Pool(Connection()))
    with TestClient(app) as first, TestClient(app) as second:
        headers = csrf_headers(first)
        response = second.post("/api/auth/logout", headers=headers)
        assert response.status_code == 403
        headers["Origin"] = "https://attacker.example"
        response = first.post("/api/auth/logout", headers=headers)
        assert response.status_code == 403


def test_password_and_verification_input_not_echoed():
    with TestClient(create_app(settings(), Pool(Connection()))) as client:
        headers = csrf_headers(client)
        for path, payload in [
            ("login", {"email": "invalid", "password": "private-password", "user_id": "forged"}),
            ("email-verification/confirm", {"token": "private-token"}),
        ]:
            response = client.post("/api/auth/" + path, json=payload, headers=headers)
            assert response.status_code == 422
            assert "private-" not in response.text


def test_guest_cookie_is_http_only_and_db_stores_only_hash():
    visitor_id = uuid4()
    conn = Connection([{"id": visitor_id}])
    with TestClient(create_app(settings(), Pool(conn))) as client:
        headers = csrf_headers(client)
        response = client.post("/api/auth/guest", headers=headers)
        assert response.status_code == 200
        raw = client.cookies.get("checkit_guest")
        assert raw and raw not in response.text
        assert conn.calls[0][1] == (token_hash(raw),)
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=lax" in response.headers["set-cookie"]
        # The pre-guest CSRF token is invalid after identity changes.
        assert client.post("/api/auth/logout", headers=headers).status_code == 403


def test_missing_member_or_expired_session_rejected():
    conn = Connection([None])
    with TestClient(create_app(settings(), Pool(conn))) as client:
        assert client.get("/api/auth/me").status_code == 401
        client.cookies.set("checkit_session", new_token())
        assert client.get("/api/auth/me").status_code == 401
        sql = conn.calls[0][0]
        assert "s.revoked_at IS NULL" in sql
        assert "s.expires_at > clock_timestamp()" in sql
        assert "u.status='ACTIVE'" in sql


def test_logout_revokes_session_and_deletes_cookies():
    conn = Connection([None])
    with TestClient(create_app(settings(), Pool(conn))) as client:
        raw = new_token()
        client.cookies.set("checkit_session", raw, domain="testserver.local", path="/")
        response = client.post("/api/auth/logout", headers=csrf_headers(client))
        assert response.status_code == 204
        assert conn.calls[0][1] == (token_hash(raw),)
        assert "revoked_at=now()" in conn.calls[0][0]
        assert "checkit_session" not in client.cookies


@pytest.mark.parametrize("kind", ["MEMBER", "GUEST"])
def test_wrong_owner_deleted_or_expired_contract_is_hidden(kind):
    owner = Actor(kind, uuid4())
    conn = Connection([None])
    with pytest.raises(APIError) as error:
        require_contract(conn, owner, uuid4())
    assert error.value.status == 404
    sql, params = conn.calls[0]
    assert params[1] == owner.id
    assert "deletion_state='AVAILABLE'" in sql
    if kind == "GUEST":
        assert "guest_session_id=%s AND expires_at > clock_timestamp()" in sql
    else:
        assert "user_id=%s" in sql


def test_claim_idempotent_for_owner_and_hidden_for_another_member():
    owner = Actor("MEMBER", uuid4())
    contract_id = uuid4()
    row = {"user_id": owner.id, "guest_session_id": None, "deletion_state": "AVAILABLE", "expires_at": None}
    assert claim_contract(Connection([row]), owner, None, contract_id)["saved"]
    row["user_id"] = uuid4()
    with pytest.raises(APIError) as error:
        claim_contract(Connection([row]), owner, Actor("GUEST", uuid4()), contract_id)
    assert error.value.status == 404


def test_claim_locks_and_rechecks_expiry_and_requires_completed_result():
    owner, visitor, contract_id = Actor("MEMBER", uuid4()), Actor("GUEST", uuid4()), uuid4()
    row = {"user_id": None, "guest_session_id": visitor.id, "deletion_state": "AVAILABLE", "expires_at": None}
    conn = Connection([row, None])
    with pytest.raises(APIError) as error:
        claim_contract(conn, owner, visitor, contract_id)
    assert error.value.status == 404
    assert "FOR UPDATE" in conn.calls[0][0]
    assert "expires_at > clock_timestamp()" in conn.calls[1][0]
    assert "checkit.analysis_results" in conn.calls[1][0]


def test_missing_smtp_configuration_is_explicit():
    with TestClient(create_app(settings(), Pool(Connection()))) as client:
        response = client.post("/api/auth/signup", json={
            "email": "person@example.com", "password": "private-password"
        }, headers=csrf_headers(client))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "EMAIL_NOT_CONFIGURED"


def test_production_rejects_insecure_settings():
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", cookie_secure=False)


def test_login_rotates_cookie_and_keeps_failed_claim_separate():
    from app.security import hash_password
    owner_id = uuid4()
    conn = Connection([
        {"user_id": owner_id, "password_hash": hash_password("correct-password"), "status": "ACTIVE"},
        None,  # new session
        None,  # guest does not exist
    ])
    with TestClient(create_app(settings(), Pool(conn))) as client:
        client.cookies.set("checkit_guest", new_token())
        headers = csrf_headers(client)
        response = client.post("/api/auth/login", json={
            "email": "USER@example.com", "password": "correct-password", "claim_contract_id": str(uuid4())
        }, headers=headers)
        assert response.status_code == 200
        assert response.json()["claim_result"] == {"saved": False, "code": "CONTRACT_NOT_FOUND"}
        assert response.json()["user"]["id"] == str(owner_id)
        raw = client.cookies.get("checkit_session")
        assert raw and raw not in response.text
        assert conn.calls[0][1] == ("user@example.com",)
        assert conn.calls[1][1][1] == token_hash(raw)
        # Old CSRF must not work for the new authenticated identity.
        assert client.post("/api/auth/logout", headers=headers).status_code == 403


def test_pending_account_cannot_login():
    from app.security import hash_password
    conn = Connection([{"user_id": uuid4(), "password_hash": hash_password("correct-password"), "status": "PENDING"}])
    with TestClient(create_app(settings(), Pool(conn))) as client:
        response = client.post("/api/auth/login", json={
            "email": "user@example.com", "password": "correct-password"
        }, headers=csrf_headers(client))
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "EMAIL_VERIFICATION_REQUIRED"
        assert len(conn.calls) == 1
        assert "checkit_session" not in client.cookies


def test_confirmation_requires_unexpired_unused_token():
    conn = Connection([None])
    with TestClient(create_app(settings(), Pool(conn))) as client:
        raw = new_token()
        response = client.post("/api/auth/email-verification/confirm", json={"token": raw},
                               headers=csrf_headers(client))
        assert response.status_code == 400
        assert raw not in response.text
        sql, params = conn.calls[0]
        assert "used_at IS NULL" in sql and "revoked_at IS NULL" in sql
        assert "expires_at > clock_timestamp()" in sql
        assert params == (token_hash(raw),)


def test_secure_cookies_have_host_prefix():
    from app.access import cookie_names
    names = cookie_names(settings(cookie_secure=True))
    assert all(name.startswith("__Host-") for name in names.values())


def test_failed_commit_never_sends_success_cookie():
    import psycopg

    class FailingCommitPool(Pool):
        @contextmanager
        def connection(self):
            yield self.conn
            raise psycopg.OperationalError("private-password must not be exposed")

    conn = Connection([{"id": uuid4()}])
    with TestClient(create_app(settings(), FailingCommitPool(conn))) as client:
        response = client.post("/api/auth/guest", headers=csrf_headers(client))
        assert response.status_code == 503
        assert "private-password" not in response.text
        assert "checkit_guest" not in client.cookies
