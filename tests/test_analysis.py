from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.access import require_csrf
from app.analysis import analysis_actor, split_page_clauses
from app.config import Settings
from app.main import create_app


class Pool:
    def open(self): pass
    def close(self): pass


class Classifier:
    def predict(self, text):
        label = "임금" if "임금" in text else "근로시간"
        return {"model_id":"test/model", "revision":"a"*40, "max_length":256,
                "labels":[label], "scores":[{"label":label,"score":0.9,"threshold":0.5}]}


class Search:
    def search_clause(self, clause_id, text, labels, top_k):
        return {"corpus":"employment_basic_v004", "method":"dense", "warnings":[],
                "clause_id":clause_id, "labels":labels,
                "retrieval_policy":"labels_soft_priority_v1", "results":[{
                    "rank":1, "chunk_id":"law::full", "cosine_distance":0.1,
                    "content":"법령 원문", "metadata":{"article_id":"law-1","law_name":"근로기준법"},
                    "base_rank":1, "matched_labels":labels, "label_priority_score":0.9,
                }]}


def make_app():
    app = create_app(Settings(_env_file=None, classifier_enabled=True, rag_enabled=True), pool=Pool())
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[analysis_actor] = lambda: SimpleNamespace(kind="MEMBER", id="test")
    app.state.classifier = Classifier()
    app.state.rag_search = Search()
    return app


def test_split_numbered_articles_preserves_text():
    text = "제1조(임금)\n임금은 매월 지급한다.\n제2조 (근로시간)\n주 40시간으로 한다."
    assert split_page_clauses(text) == [
        "제1조(임금)\n임금은 매월 지급한다.",
        "제2조 (근로시간)\n주 40시간으로 한다.",
    ]


def test_split_blank_paragraph_fallback():
    assert split_page_clauses("임금은 월급으로 한다.\n\n근무지는 서울이다.") == [
        "임금은 월급으로 한다.", "근무지는 서울이다.",
    ]


def test_contract_text_runs_classification_retrieval_and_builds_llm_context():
    with TestClient(make_app()) as client:
        response = client.post("/api/analysis/contracts/text", json={
            "contract_id":"contract-1", "top_k":3,
            "pages":[{"page":1,"text":"제1조(임금)\n임금은 매월 지급한다.\n제2조(근로시간)\n주 40시간으로 한다."}],
        })
        assert response.status_code == 200
        body = response.json()
        assert body["input_mode"] == "OCR_BYPASS_TEXT"
        assert body["stages_completed"][-1] == "RETRIEVAL_COMPLETE"
        assert [x["clause_id"] for x in body["clauses"]] == ["contract-1:c0001", "contract-1:c0002"]
        assert body["clauses"][0]["classification"]["labels"] == ["임금"]
        context = body["clauses"][0]["llm_context"]
        assert context["clause_text"] == "제1조(임금)\n임금은 매월 지급한다."
        assert context["law_candidates"][0]["metadata"]["article_id"] == "law-1"
        assert body["document_context"]["missing_required_review_needed"] is True


@pytest.mark.parametrize("body", [
    {"contract_id":"bad id", "pages":[{"page":1,"text":"text"}]},
    {"contract_id":"c", "pages":[{"page":2,"text":"two"},{"page":1,"text":"one"}]},
    {"contract_id":"c", "pages":[{"page":1,"text":"one"},{"page":1,"text":"again"}]},
    {"contract_id":"c", "pages":[{"page":1,"text":" "}]},
])
def test_invalid_payload(body):
    with TestClient(make_app()) as client:
        assert client.post("/api/analysis/contracts/text", json=body).status_code == 422


def test_clause_over_model_limit_is_rejected_without_truncation():
    with TestClient(make_app()) as client:
        response = client.post("/api/analysis/contracts/text", json={
            "contract_id":"c", "pages":[{"page":1,"text":"가"*2001}],
        })
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CLAUSE_TOO_LONG"


def test_swagger_and_analysis_body_limit():
    with TestClient(make_app()) as client:
        schema = client.get("/openapi.json").json()
        assert "/api/analysis/contracts/text" in schema["paths"]
        assert client.post("/api/analysis/contracts/text", content=b"x"*262145).status_code == 413
