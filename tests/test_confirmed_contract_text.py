from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.access import require_csrf
from app.config import Settings
from app.main import create_app
import app.contracts as contracts
from app.analysis_jobs import stored_clauses


IDS = [UUID(int=i) for i in (1, 2, 3)]


class Pool:
    def open(self): pass
    def close(self): pass


class Conn:
    def __init__(self):
        self.calls = []
        self.rows = iter(IDS)

    def execute(self, sql, args):
        self.calls.append((sql, args))
        self.row = {"id": next(self.rows)} if "RETURNING id" in sql else None
        return self

    def fetchone(self):
        return self.row


def client_for(monkeypatch, conn):
    app = create_app(Settings(_env_file=None), pool=Pool())
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[contracts.connection] = lambda: conn
    monkeypatch.setattr(contracts, "current_actor", lambda request, connection: SimpleNamespace(id=UUID(int=10)))
    return TestClient(app)


def payload():
    return {"input_kind": "IMAGES", "pages": [
        {"page": 1, "text": "제1조(임금)\n시급 12,000원"},
        {"page": 2, "text": "제2조(휴일)\n주휴일은 일요일"},
    ], "privacy_confirmed": True, "gemini_notice_acknowledged": True}


def test_confirmed_text_is_saved_without_original_files_and_keeps_page_locations(monkeypatch):
    conn = Conn()
    with client_for(monkeypatch, conn) as client:
        response = client.post("/api/contracts", json=payload())
        assert response.status_code == 201
        assert response.json() == {"contract_id": str(IDS[0]), "revision_id": str(IDS[2])}
    assert not any("file_assets" in sql or "document_pages" in sql for sql, _ in conn.calls)
    revision_args = next(args for sql, args in conn.calls if "INSERT INTO checkit.text_revisions" in sql)
    content, blocks = revision_args[2], revision_args[3].obj
    assert [row["page"] for row in stored_clauses(IDS[0], content, blocks)] == [1, 2]
    assert content[blocks[1]["start"]:blocks[1]["end"]] == payload()["pages"][1]["text"]


def test_text_submission_rejects_unreviewed_or_unmasked_input(monkeypatch):
    conn = Conn()
    with client_for(monkeypatch, conn) as client:
        body = payload()
        body["privacy_confirmed"] = False
        assert client.post("/api/contracts", json=body).status_code == 422
        body = payload()
        body["pages"][0]["text"] = "담당자 010-1234-5678"
        response = client.post("/api/contracts", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "PERSONAL_DATA_DETECTED"
        body = payload()
        body["pages"] = [body["pages"][1]]
        assert client.post("/api/contracts", json=body).status_code == 422
    assert conn.calls == []


def test_delete_contract_requires_ownership_and_removes_record(monkeypatch):
    class DeleteConn:
        def __init__(self, owned):
            self.owned = owned
            self.calls = []

        def execute(self, sql, args):
            self.calls.append((sql, args))
            self.row = {"id": IDS[0]} if self.owned and "FROM checkit.contracts" in sql else None
            return self

        def fetchone(self):
            return self.row

    owned = DeleteConn(True)
    with client_for(monkeypatch, owned) as client:
        response = client.delete(f"/api/contracts/{IDS[0]}")
        assert response.status_code == 204
        assert not response.content
        schema = client.get("/openapi.json").json()
        assert "delete" in schema["paths"]["/api/contracts/{contract_id}"]
        preflight = client.options(f"/api/contracts/{IDS[0]}", headers={
            "Origin": "http://localhost:8000", "Access-Control-Request-Method": "DELETE"})
        assert preflight.headers["access-control-allow-methods"].find("DELETE") >= 0
    assert "FOR UPDATE" in owned.calls[0][0]
    assert owned.calls[1] == ("DELETE FROM checkit.contracts WHERE id=%s AND user_id=%s",
                              (IDS[0], UUID(int=10)))

    other = DeleteConn(False)
    with client_for(monkeypatch, other) as client:
        response = client.delete(f"/api/contracts/{IDS[0]}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CONTRACT_NOT_FOUND"
    assert len(other.calls) == 1


def test_delete_contract_requires_csrf(monkeypatch):
    app = create_app(Settings(_env_file=None), pool=Pool())
    with TestClient(app) as client:
        response = client.delete(f"/api/contracts/{IDS[0]}", headers={"Origin": "http://localhost:8000"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_FAILED"
