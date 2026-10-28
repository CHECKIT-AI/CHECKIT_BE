from types import SimpleNamespace
from types import ModuleType
import sys

import pytest
from fastapi.testclient import TestClient

from app.access import require_csrf
from app.config import Settings
from app.errors import APIError
from app.main import create_app
from app.rag import LocalSearch, search_actor


class Pool:
    def open(self):
        pass

    def close(self):
        pass


def make_app():
    app = create_app(Settings(_env_file=None, rag_enabled=True), pool=Pool())
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[search_actor] = lambda: SimpleNamespace(kind="GUEST", id="test")
    return app


class Service:
    def search(self, query, top_k):
        assert query == "임금 지급"
        assert top_k == 5
        return {"corpus": "labor_standards_v001", "method": "dense", "results": [{
            "rank": 1, "chunk_id": "article::full", "cosine_distance": 0.2,
            "content": "법령 원문", "metadata": {"law_name": "근로기준법"},
        }]}


def test_search_response_and_swagger():
    app = make_app()
    app.state.rag_search.service = Service()
    with TestClient(app) as client:
        response = client.post("/api/rag/search", json={"query": " 임금 지급 "})
        assert response.status_code == 200
        assert response.json()["results"][0]["metadata"]["law_name"] == "근로기준법"
        assert response.headers["cache-control"] == "no-store"
        schema = client.get("/openapi.json").json()
        assert "200" in schema["paths"]["/api/rag/search"]["post"]["responses"]


def test_clause_labels_and_original_text_are_forwarded_and_linked():
    class ClauseService:
        def search_clause(self, clause_id, text, labels, top_k):
            assert (clause_id, text, labels, top_k) == ("c-7", "월급 2,500,000원은 공제하지 않는다.", ["임금"], 5)
            return {"corpus": "employment_basic_v004", "method": "dense", "results": [],
                    "clause_id": clause_id, "labels": labels, "retrieval_policy": "labels_soft_priority_v1"}

    app = make_app()
    app.state.rag_search.service = ClauseService()
    with TestClient(app) as client:
        response = client.post("/api/rag/search", json={"clause_id": "c-7", "labels": ["임금"],
                               "text": "월급 2,500,000원은 공제하지 않는다."})
        assert response.status_code == 200
        assert response.json()["clause_id"] == "c-7"
        assert response.json()["labels"] == ["임금"]
        assert response.json()["retrieval_policy"] == "labels_soft_priority_v1"


@pytest.mark.parametrize("patch", [
    {"text": " "}, {"labels": []}, {"labels": ["임대차"]}, {"labels": ["임금", "임금"]},
    {"clause_id": " "}, {"query": "혼합 입력"}, {"top_k": True}, {"text": "a" * 2001},
])
def test_invalid_clause_payload_is_rejected(patch):
    payload = {"clause_id": "c-7", "labels": ["임금"], "text": "월급 지급"}
    payload.update(patch)
    with TestClient(make_app()) as client:
        assert client.post("/api/rag/search", json=payload).status_code == 422


@pytest.mark.parametrize("body", [
    {"query": " "}, {"query": "a" * 2001}, {"query": "test", "top_k": 11},
    {"query": "test", "top_k": True}, {"query": "test", "corpus": "../../private"},
])
def test_invalid_input(body):
    with TestClient(make_app()) as client:
        assert client.post("/api/rag/search", json=body).status_code == 422


def test_csrf_and_session_required():
    app = make_app()
    del app.dependency_overrides[require_csrf]
    with TestClient(app) as client:
        assert client.post("/api/rag/search", json={"query": "test"}).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None

    def no_session():
        raise APIError(401, "AUTHENTICATION_REQUIRED", "인증 필요")

    app.dependency_overrides[search_actor] = no_session
    with TestClient(app) as client:
        assert client.post("/api/rag/search", json={"query": "test"}).status_code == 401


def test_disabled_busy_and_input_failure():
    service = LocalSearch(Settings(_env_file=None))
    with pytest.raises(APIError) as error:
        service.search("test", 5)
    assert error.value.code == "RAG_DISABLED"
    service.settings = Settings(_env_file=None, rag_enabled=True)
    service.lock.acquire()
    try:
        with pytest.raises(APIError) as error:
            service.search("test", 5)
        assert error.value.code == "RAG_BUSY"
    finally:
        service.lock.release()


def test_errors_hide_paths_and_release_lock():
    class Broken:
        def search(self, *_):
            raise RuntimeError("/private/secret/password")

    app = make_app()
    app.state.rag_search.service = Broken()
    with TestClient(app) as client:
        response = client.post("/api/rag/search", json={"query": "test"})
        assert response.status_code == 503
        assert "secret" not in response.text
    assert not app.state.rag_search.lock.locked()


def test_lazy_initialization_reuses_model_and_recovers(monkeypatch):
    module = ModuleType("RAG.service")
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("private model path")
        return Service()

    module.LawSearchService = create
    monkeypatch.setitem(sys.modules, "RAG.service", module)
    service = LocalSearch(Settings(_env_file=None, rag_enabled=True))
    with pytest.raises(APIError) as error:
        service.search("임금 지급", 5)
    assert error.value.code == "RAG_UNAVAILABLE"
    assert "private" not in error.value.message
    service.search("임금 지급", 5)
    service.search("임금 지급", 5)
    assert len(calls) == 2


def test_model_input_limit_is_422():
    class Oversized:
        def search(self, *_):
            raise ValueError("internal tokenizer details")

    app = make_app()
    app.state.rag_search.service = Oversized()
    with TestClient(app) as client:
        response = client.post("/api/rag/search", json={"query": "test"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "RAG_INPUT_LIMIT"


def test_reranked_keyword_candidate_and_year_warning_are_returned():
    class Reranked:
        def search(self, *_):
            return {"corpus": "employment_basic_v003", "method": "hybrid_rerank", "results": [{
                "rank": 1, "chunk_id": "keyword-only", "cosine_distance": None,
                "reranker_score": 2.5, "content": "공식 원문", "metadata": {"article_id": "x"},
            }], "warnings": ["2025년 고시 미수집"]}

    app = make_app()
    app.state.rag_search.service = Reranked()
    with TestClient(app) as client:
        response = client.post("/api/rag/search", json={"query": "2025년 최저임금"})
        assert response.status_code == 200
        body = response.json()
        assert body["method"] == "hybrid_rerank"
        assert body["results"][0]["cosine_distance"] is None
        assert body["results"][0]["reranker_score"] == 2.5
        assert body["warnings"] == ["2025년 고시 미수집"]


def test_body_limit_and_rate_limit():
    app = make_app()
    app.state.rag_search.service = Service()
    with TestClient(app) as client:
        assert client.post("/api/rag/search", content=b"x" * 16385).status_code == 413
        for _ in range(30):
            assert client.post("/api/rag/search", json={"query": "임금 지급"}).status_code == 200
        assert client.post("/api/rag/search", json={"query": "임금 지급"}).status_code == 429
