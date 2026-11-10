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
