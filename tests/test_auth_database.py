"""Opt-in integration checks against the existing schema. No schema SQL is executed.

CHECKIT_RUN_DB_TESTS=1 .venv/bin/python -m pytest tests/test_auth_database.py -q
All synthetic records are contained in one force-rollback transaction per test.
"""
from contextlib import contextmanager
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from app.config import Settings
from app.database import verify_backend_role
from app.main import create_app
from app.security import hash_password, new_token, token_hash

pytestmark = pytest.mark.skipif(os.environ.get("CHECKIT_RUN_DB_TESTS") != "1",
                                reason="실제 DB 검증은 명시적으로 활성화할 때만 실행")


class TransactionPool:
    def __init__(self, conn):
        self.conn = conn

    def open(self):
        pass

    def close(self):
        pass

    @contextmanager
    def connection(self):
        # Each request can fail without aborting the outer rollback-only test transaction.
        with self.conn.transaction():
            yield self.conn


@pytest.fixture
def db_case():
    configured = Settings()
    with psycopg.connect(configured.database_url.get_secret_value(), sslmode="require",
                         connect_timeout=10, prepare_threshold=None, row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=True):
            verify_backend_role(conn)
            unique = uuid4().hex
            password = "checkit-test-password"
            encoded = hash_password(password)
            users = []
            sessions = []
            for index in range(2):
                user_id = conn.execute("INSERT INTO checkit.users(status) VALUES ('ACTIVE') RETURNING id").fetchone()["id"]
                email = f"auth-test-{unique}-{index}@example.invalid"
                conn.execute(
                    "INSERT INTO checkit.auth_identities(user_id,provider,provider_subject,email,password_hash) "
                    "VALUES (%s,'EMAIL',%s,%s,%s)", (user_id, email, email, encoded),
                )
                token = new_token()
                conn.execute("INSERT INTO checkit.auth_sessions(user_id,token_hash,expires_at) "
                             "VALUES (%s,%s,now()+interval '1 day')", (user_id, token_hash(token)))
                users.append((user_id, email))
                sessions.append(token)
            raw_guest = new_token()
            guest_id = conn.execute("INSERT INTO checkit.guest_sessions(token_hash) VALUES (%s) RETURNING id",
                                    (token_hash(raw_guest),)).fetchone()["id"]
            contracts = []
            for user_id, guest_owner, age, state in [
                (users[0][0], None, 0, "AVAILABLE"), (users[1][0], None, 0, "AVAILABLE"),
                (None, guest_id, 0, "AVAILABLE"), (None, guest_id, 25, "AVAILABLE"),
                (None, guest_id, 0, "DELETING"),
            ]:
                contract_id = conn.execute(
                    "INSERT INTO checkit.contracts(user_id,guest_session_id,contract_type,input_kind,first_uploaded_at,deletion_state) "
                    "VALUES (%s,%s,'EMPLOYMENT','PDF',now()-%s*interval '1 hour',%s) RETURNING id",
                    (user_id, guest_owner, age, state),
                ).fetchone()["id"]
                contracts.append(contract_id)
            settings = Settings(_env_file=None, database_url=configured.database_url,
                                csrf_secret="test-only-secret-" * 3, allowed_origins=["http://testserver"])
            with TestClient(create_app(settings, TransactionPool(conn))) as client:
                yield conn, client, users, sessions, raw_guest, contracts, password


def headers(client):
    return {"Origin": "http://testserver", "X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]}


def test_actual_owner_and_guest_expiry_queries(db_case):
    conn, client, users, sessions, raw_guest, contracts, password = db_case
    client.cookies.set("checkit_session", sessions[0])
    assert client.get(f"/api/contracts/{contracts[0]}").status_code == 200
    assert client.get(f"/api/contracts/{contracts[1]}").status_code == 404
    assert [row["id"] for row in client.get("/api/contracts").json()["contracts"]] == [str(contracts[0])]
    client.cookies.clear()
    client.cookies.set("checkit_guest", raw_guest)
    assert client.get(f"/api/contracts/{contracts[2]}").status_code == 200
    for index in (0, 1, 3, 4):
        assert client.get(f"/api/contracts/{contracts[index]}").status_code == 404


def test_actual_login_revocation_and_expiry(db_case):
    conn, client, users, sessions, raw_guest, contracts, password = db_case
    response = client.post("/api/auth/login", headers=headers(client), json={
        "email": users[0][1], "password": password,
    })
    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    raw = client.cookies.get("checkit_session")
    assert conn.execute("SELECT 1 FROM checkit.auth_sessions WHERE token_hash=%s", (token_hash(raw),)).fetchone()
    assert client.post("/api/auth/logout", headers=headers(client)).status_code == 204
    assert conn.execute("SELECT revoked_at FROM checkit.auth_sessions WHERE token_hash=%s",
                        (token_hash(raw),)).fetchone()["revoked_at"] is not None
    client.cookies.set("checkit_session", raw)
    assert client.get("/api/auth/me").status_code == 401
    conn.execute("UPDATE checkit.auth_sessions SET created_at=now()-interval '2 days', "
                 "expires_at=now()-interval '1 second' WHERE token_hash=%s", (token_hash(sessions[0]),))
    client.cookies.set("checkit_session", sessions[0])
    assert client.get("/api/auth/me").status_code == 401


def test_actual_claim_and_repeat_preserve_one_record(db_case):
    conn, client, users, sessions, raw_guest, contracts, password = db_case
    contract_id = contracts[2]
    generation = conn.execute("INSERT INTO checkit.file_generations(contract_id,input_kind) "
                              "VALUES (%s,'PDF') RETURNING id", (contract_id,)).fetchone()["id"]
    revision = conn.execute("INSERT INTO checkit.text_revisions(contract_id,file_generation_id,revision,kind,content,confirmed_at) "
                            "VALUES (%s,%s,1,'EXTRACTED','synthetic test text',now()) RETURNING id",
                            (contract_id, generation)).fetchone()["id"]
    job = conn.execute("INSERT INTO checkit.analysis_jobs(contract_id,request_id,kind,file_generation_id,input_revision_id,status,finished_at) "
                       "VALUES (%s,%s,'ANALYSIS',%s,%s,'SUCCEEDED',now()) RETURNING id",
                       (contract_id, uuid4(), generation, revision)).fetchone()["id"]
    conn.execute("INSERT INTO checkit.analysis_results(contract_id,job_id,file_generation_id,input_revision_id,summary,corpus_version) "
                 "VALUES (%s,%s,%s,%s,'synthetic summary','test-only')", (contract_id, job, generation, revision))
    client.cookies.set("checkit_session", sessions[0])
    client.cookies.set("checkit_guest", raw_guest)
    for _ in range(2):
        assert client.post(f"/api/contracts/{contract_id}/claim", headers=headers(client)).status_code == 200
    row = conn.execute("SELECT user_id,guest_session_id,expires_at FROM checkit.contracts WHERE id=%s", (contract_id,)).fetchone()
    assert row == {"user_id": users[0][0], "guest_session_id": None, "expires_at": None}
    assert client.post(f"/api/contracts/{contracts[3]}/claim", headers=headers(client)).status_code == 404


def test_actual_signup_verification_and_resend_with_mock_mail(db_case, monkeypatch):
    conn, client, users, sessions, raw_guest, contracts, password = db_case
    configured = client.app.state.settings
    configured.smtp_host = "smtp.example.invalid"
    configured.smtp_from = "sender@example.invalid"
    configured.verification_page_url = "https://example.invalid/verify"
    delivered = []
    monkeypatch.setattr("app.auth.send_verification", lambda settings, email, token: delivered.append(token))
    email = f"signup-{uuid4().hex}@example.invalid"
    credentials = {"email": email, "password": password}
    assert client.post("/api/auth/signup", headers=headers(client), json=credentials).status_code == 202
    assert len(delivered) == 1
    pending = client.post("/api/auth/login", headers=headers(client), json=credentials)
    assert pending.status_code == 403
    # Repeated signup/resend must never replace the original password.
    assert client.post("/api/auth/signup", headers=headers(client), json={
        "email": email, "password": "different-test-password"
    }).status_code == 202
    assert len(delivered) == 2
    assert client.post("/api/auth/email-verification/confirm", headers=headers(client),
                       json={"token": delivered[0]}).status_code == 400
    assert client.post("/api/auth/email-verification/confirm", headers=headers(client),
                       json={"token": delivered[1]}).status_code == 200
    assert client.post("/api/auth/email-verification/confirm", headers=headers(client),
                       json={"token": delivered[1]}).status_code == 400
    assert "checkit_session" not in client.cookies
    assert client.post("/api/auth/login", headers=headers(client), json=credentials).status_code == 200
