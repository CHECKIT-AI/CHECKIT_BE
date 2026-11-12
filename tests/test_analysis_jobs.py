from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.analysis_jobs as jobs
from app.access import require_csrf
from app.config import Settings
from app.main import create_app
from app.analysis_llm import Finding, Judgment, LLMInputTooLarge, LLMUnavailable

CONTRACT_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
GENERATION_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
REVISION_ID = UUID("550e8400-e29b-41d4-a716-446655440002")


class Pool:
    def open(self): pass
    def close(self): pass


class Conn:
    def __init__(self):
        self.inserted = None

    def execute(self, sql, args):
        if "FROM checkit.text_revisions" in sql:
            self.row = {"id": REVISION_ID, "content": "제1조(임금)\n시급 9,000원이다."}
        elif "INSERT INTO checkit.analysis_jobs" in sql:
            self.inserted = args
            self.row = None
        elif "SELECT id,status,stage,error_code FROM checkit.analysis_jobs" in sql:
            self.row = {"id": args[0], "status": "QUEUED", "stage": None, "error_code": None}
        else:
            raise AssertionError(sql)
        return self

    def fetchone(self):
        return self.row


def make_app(monkeypatch, conn):
    app = create_app(Settings(_env_file=None, classifier_enabled=True, rag_enabled=True,
                              gemini_api_key=SecretStr("test-key")), pool=Pool())
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[jobs.connection] = lambda: conn
    monkeypatch.setattr(jobs, "current_actor", lambda request, connection: SimpleNamespace(kind="MEMBER", id=CONTRACT_ID))
    monkeypatch.setattr(jobs, "require_contract", lambda connection, actor, contract_id, lock=False: {
        "contract_type": "EMPLOYMENT", "current_file_generation_id": GENERATION_ID,
    })
    monkeypatch.setattr(jobs, "run_job", lambda app, job_id: None)
    return app


def test_job_api_creates_owned_job_and_exposes_status(monkeypatch):
    conn = Conn()
    with TestClient(make_app(monkeypatch, conn)) as client:
        response = client.post(f"/api/analysis/contracts/{CONTRACT_ID}/jobs", json={
            "effective_date": "2026-11-09", "employee_count": 5,
            "privacy_confirmed": True,
            "gemini_notice_acknowledged": True,
        })
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert conn.inserted[2] == CONTRACT_ID
        assert conn.inserted[5].obj["employee_count"] == 5
        state = client.get(f"/api/analysis/contracts/{CONTRACT_ID}/jobs/{job_id}")
        assert state.status_code == 200
        assert state.json()["status"] == "QUEUED"
        assert state.json()["result"] is None
        schema = client.get("/openapi.json").json()
        assert f"/api/analysis/contracts/{{contract_id}}/jobs" in schema["paths"]


def test_development_analysis_page_serves_browser_only_ocr():
    with TestClient(create_app(Settings(_env_file=None), pool=Pool())) as client:
        response = client.get("/dev/analysis-test")
        assert response.status_code == 200
        assert 'type="file"' in response.text
        assert 'application/pdf,image/jpeg,image/png' in response.text
        assert '"/api/contracts"' in response.text
        assert '"/api/auth/login"' in response.text


def test_job_rejects_unconfirmed_revision(monkeypatch):
    class Missing(Conn):
        def execute(self, sql, args):
            super().execute(sql, args)
            if "FROM checkit.text_revisions" in sql:
                self.row = None
            return self
    with TestClient(make_app(monkeypatch, Missing())) as client:
        response = client.post(f"/api/analysis/contracts/{CONTRACT_ID}/jobs", json={
            "privacy_confirmed": True,
            "gemini_notice_acknowledged": True,
        })
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ANALYSIS_INPUT_UNAVAILABLE"


def test_stored_revision_rejects_oversized_clause_without_truncation():
    try:
        jobs.stored_clauses(CONTRACT_ID, "가" * 2001)
    except Exception as exc:
        assert getattr(exc, "code", None) == "ANALYSIS_INPUT_LIMIT"
    else:
        raise AssertionError("expected input limit")


def test_citations_require_official_source_and_applicable_effective_date():
    hit = {"chunk_id": "law:1", "metadata": {
        "source_url": "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=1",
        "article_effective_date": "20261008", "is_deleted": False,
    }}
    assert jobs._verified_citations(["law:1"], [hit], jobs.date(2026, 11, 9))
    assert not jobs._verified_citations(["law:1"], [hit], jobs.date(2026, 1, 1))
    hit["metadata"]["source_url"] = "https://example.com/law"
    assert not jobs._verified_citations(["law:1"], [hit], jobs.date(2026, 11, 9))


class WorkerConn:
    def __init__(self):
        self.failed_code = None
        self.recovery_action = None

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def execute(self, sql, args):
        if "status='RUNNING'" in sql and "RETURNING" in sql:
            self.row = {"id": CONTRACT_ID, "contract_id": CONTRACT_ID,
                        "file_generation_id": GENERATION_ID, "input_revision_id": REVISION_ID,
                        "analysis_context": {"effective_date": "2026-11-09", "top_k": 3, "employee_count": 5}}
        elif "FROM checkit.text_revisions" in sql:
            self.row = {"id": REVISION_ID, "content": "시급 9,000원으로 한다."}
        elif "status='FAILED'" in sql:
            self.failed_code = args[0]
            self.recovery_action = args[1]
            self.row = None
        else:
            raise AssertionError(sql)
        return self

    def fetchone(self): return self.row


class WorkerPool:
    def __init__(self): self.conn = WorkerConn()
    def connection(self): return self.conn


class WorkerSearch:
    def __init__(self): self.clauses = []
    def search(self, query, top_k):
        return {"corpus": "employment_basic_v004", "results": []}
    def search_clause(self, clause_id, text, labels, top_k):
        self.clauses.append(clause_id)
        return {"corpus": "employment_basic_v004", "results": []}


def test_worker_reviews_all_candidates_once_and_saves_only_after_judgment(monkeypatch):
    reviewed = []
    saved = []

    class Reviewer:
        def judge(self, clauses, reviews, context):
            reviewed.append((clauses, reviews))
            return {candidate["candidate_id"]: Judgment(
                status="NEEDS_CONFIRMATION", explanation="확인 필요",
                required_information=[], citation_chunk_ids=[])
                for candidate, _ in reviews}

    search = WorkerSearch()
    app = SimpleNamespace(state=SimpleNamespace(
        database_pool=WorkerPool(), classifier=SimpleNamespace(predict=lambda text: {
            "labels": [], "model_id": "test/model", "revision": "test-revision"}), rag_search=search,
        gemini_reviewer=Reviewer(), settings=SimpleNamespace(rag_corpus="employment_basic_v004",
                                                     gemini_model="gemini-3.8-flash")))
    monkeypatch.setattr(jobs, "_stage", lambda *args: None)
    monkeypatch.setattr(jobs, "_save_result", lambda *args: saved.append(args))
    jobs.run_job(app, CONTRACT_ID)
    assert len(reviewed) == 1 and saved
    assert reviewed[0][0][0]["text"] == "시급 9,000원으로 한다."
    assert len({candidate["candidate_id"] for candidate, _ in reviewed[0][1]}) == len(reviewed[0][1])
    assert len(saved[0][4]) == len([candidate for candidate, _ in reviewed[0][1]
                                   if candidate["category"] not in {"CLAUSE_SCAN", "DOCUMENT_SCAN"}])
    assert search.clauses == [reviewed[0][0][0]["clause_id"]]
    assert {candidate["category"] for candidate, _ in reviewed[0][1]} >= {"CLAUSE_SCAN", "DOCUMENT_SCAN"}
    assert app.state.database_pool.conn.failed_code is None


def test_worker_saves_discovered_issue_as_needs_confirmation_without_verified_law(monkeypatch):
    saved = []

    class Reviewer:
        def judge(self, clauses, reviews, context):
            answers = {candidate["candidate_id"]: Judgment(
                status="NEEDS_CONFIRMATION", explanation="확인 필요") for candidate, _ in reviews}
            answers["scan_0001"].findings = [Finding(
                category="LEGAL_RISK", explanation="추가 문제", citation_chunk_ids=[])]
            return answers

    app = SimpleNamespace(state=SimpleNamespace(
        database_pool=WorkerPool(), classifier=SimpleNamespace(predict=lambda text: {
            "labels": [], "model_id": "test/model", "revision": "test-revision"}),
        rag_search=WorkerSearch(), gemini_reviewer=Reviewer(),
        settings=SimpleNamespace(rag_corpus="employment_basic_v004", gemini_model="gemini-3.8-flash")))
    monkeypatch.setattr(jobs, "_stage", lambda *args: None)
    monkeypatch.setattr(jobs, "_save_result", lambda *args: saved.append(args))
    jobs.run_job(app, CONTRACT_ID)
    found = [(candidate, answer) for candidate, answer, _ in saved[0][4]
             if candidate.get("source") == "GEMINI"]
    assert len(found) == 1
    assert found[0][0]["clause_id"] == f"{CONTRACT_ID}:c0001"
    assert found[0][1].status == "NEEDS_CONFIRMATION"
    assert found[0][1].citation_chunk_ids == []


def test_empty_result_summary_does_not_claim_contract_is_safe():
    class SaveConn:
        def execute(self, sql, args):
            if "FROM checkit.contracts" in sql:
                self.row = {"current_file_generation_id": GENERATION_ID, "deletion_state": "AVAILABLE"}
            elif "FROM checkit.text_revisions" in sql:
                self.row = {"id": REVISION_ID}
            elif "INSERT INTO checkit.analysis_results" in sql:
                self.summary = args[4]
                self.row = {"id": CONTRACT_ID}
            else:
                self.row = None
            return self
        def fetchone(self): return self.row

    conn = SaveConn()
    jobs._save_result(conn, {"id": CONTRACT_ID, "contract_id": CONTRACT_ID,
                             "file_generation_id": GENERATION_ID, "input_revision_id": REVISION_ID},
                      [{"clause_id": "c1"}], [], [], "employment_basic_v004", "gemini-test")
    assert "검출된 문제 없음" in conn.summary
    assert "검토 범위에 한계" in conn.summary


def test_worker_records_sanitized_failure_code(monkeypatch):
    class Reviewer:
        def judge(self, clauses, reviews, context):
            raise LLMUnavailable("provider secret details")

    app = SimpleNamespace(state=SimpleNamespace(
        database_pool=WorkerPool(), classifier=SimpleNamespace(predict=lambda text: {
            "labels": [], "model_id": "test/model", "revision": "test-revision"}), rag_search=WorkerSearch(),
        gemini_reviewer=Reviewer(), settings=SimpleNamespace(rag_corpus="employment_basic_v004",
                                                     gemini_model="gemini-3.8-flash")))
    monkeypatch.setattr(jobs, "_stage", lambda *args: None)
    jobs.run_job(app, CONTRACT_ID)
    assert app.state.database_pool.conn.failed_code == "LLM_UNAVAILABLE"
    assert app.state.database_pool.conn.recovery_action == "RETRY"


def test_worker_reports_unsplittable_input_without_retry(monkeypatch):
    class Reviewer:
        def judge(self, clauses, reviews, context):
            raise LLMInputTooLarge("provider details")

    app = SimpleNamespace(state=SimpleNamespace(
        database_pool=WorkerPool(), classifier=SimpleNamespace(predict=lambda text: {
            "labels": [], "model_id": "test/model", "revision": "test-revision"}), rag_search=WorkerSearch(),
        gemini_reviewer=Reviewer(), settings=SimpleNamespace(rag_corpus="employment_basic_v004",
                                                     gemini_model="gemini-3.8-flash")))
    monkeypatch.setattr(jobs, "_stage", lambda *args: None)
    jobs.run_job(app, CONTRACT_ID)
    assert app.state.database_pool.conn.failed_code == "ANALYSIS_INPUT_LIMIT"
    assert app.state.database_pool.conn.recovery_action == "NONE"
