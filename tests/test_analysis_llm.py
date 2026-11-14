import json

import httpx
import pytest
from pydantic import SecretStr

from app.analysis_llm import GeminiReviewer, LLMInputTooLarge, LLMUnavailable, PROMPT_VERSION
from app.config import Settings


def reviewer():
    return GeminiReviewer(Settings(_env_file=None, gemini_api_key=SecretStr("test-key")))


def reviews():
    shared = {"chunk_id": "law:1", "content": "조문 원문과 예외", "metadata": {
        "source_url": "https://www.law.go.kr/1", "law_name": "근로기준법", "irrelevant": "omit",
    }}
    return [
        ({"candidate_id": "candidate_0001", "check_code": "MISSING_WAGE", "category": "MISSING",
          "clause_id": None, "explanation": "임금 확인", "required_information": [],
          "retrieval_warnings": []}, [shared]),
        ({"candidate_id": "candidate_0002", "check_code": "PRESET_PENALTY", "category": "LEGAL_RISK",
          "clause_id": "c1", "explanation": "위약금 확인", "required_information": [],
          "retrieval_warnings": []}, [shared]),
    ]


def result_for(candidate_ids, citations=None):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
        "items": [{"candidate_id": candidate_id, "status": "NEEDS_CONFIRMATION",
                   "explanation": "확인 필요", "required_information": [],
                   "citation_chunk_ids": (citations or {}).get(candidate_id, []), "findings": [],
                   "document_presence": "UNCLEAR" if candidate_id == "candidate_0001" else None,
                   "document_quote": None, "document_clause_id": None}
                  for candidate_id in candidate_ids],
    })}]}}]}


def response(url, body):
    return httpx.Response(200, request=httpx.Request("POST", url), json=body)


def test_one_gemini_call_deduplicates_law_and_contract_text(monkeypatch):
    calls = []

    def post(self, url, **kwargs):
        calls.append(kwargs)
        return response(url, result_for(["candidate_0001", "candidate_0002"], {
            "candidate_0002": ["law:1"],
        }))

    monkeypatch.setattr(httpx.Client, "post", post)
    clauses = [{"clause_id": "c1", "text": "퇴사하면 위약금 100만원"}]
    answers = reviewer().judge(clauses, reviews(), {"effective_date": "2026-11-09"})
    assert set(answers) == {"candidate_0001", "candidate_0002"}
    assert len(calls) == 1
    prompt = json.loads(calls[0]["json"]["contents"][0]["parts"][0]["text"])
    assert prompt["document_clauses"] == clauses
    assert len(prompt["law_hits"]) == 1
    assert prompt["law_hits"][0]["content"] == "조문 원문과 예외"
    assert "irrelevant" not in prompt["law_hits"][0]["metadata"]
    assert [candidate["law_chunk_ids"] for candidate in prompt["candidates"]] == [["law:1"], ["law:1"]]
    rules = " ".join(prompt["rules"])
    assert PROMPT_VERSION == "employment_review_v5"
    assert "제공된 law_hits의 실제 내용에서만" in rules
    assert "그 candidate_id의 law_chunk_ids에 있는 ID" in rules
    assert "근거가 없으면 finding을 만들지 마세요" in rules
    assert "document_presence" in rules
    assert calls[0]["json"]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("body", [
    {"candidates": []},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]},
    result_for(["candidate_0001"]),
    result_for(["candidate_0001", "candidate_0001"]),
])
def test_missing_duplicate_or_untrusted_answers_retry_then_fail(monkeypatch, body):
    calls = []

    def post(self, url, **kwargs):
        calls.append(1)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert len(calls) == 2


def test_rejected_response_logs_fixed_reason_without_contract_text(monkeypatch, caplog):
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kwargs:
                        response(url, result_for(["candidate_0001"])))
    caplog.set_level("WARNING", logger="app.analysis_llm")
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "private contract content"}], reviews(), {})
    assert "MISSING_OR_DUPLICATE_JUDGMENT" in caplog.text
    assert "private contract content" not in caplog.text


def test_input_limit_splits_only_after_provider_rejects_batch(monkeypatch):
    calls = []

    def post(self, url, **kwargs):
        prompt = json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"])
        candidate_ids = [candidate["candidate_id"] for candidate in prompt["candidates"]]
        calls.append(candidate_ids)
        if len(candidate_ids) > 1:
            return httpx.Response(413, request=httpx.Request("POST", url))
        return response(url, result_for(candidate_ids))

    monkeypatch.setattr(httpx.Client, "post", post)
    answers = reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert set(answers) == {"candidate_0001", "candidate_0002"}
    assert calls == [["candidate_0001", "candidate_0002"],
                     ["candidate_0001"], ["candidate_0002"]]

    def too_large(self, url, **kwargs):
        return httpx.Response(413, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", too_large)
    with pytest.raises(LLMInputTooLarge):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews()[:1], {})


def test_read_timeout_splits_batch_and_keeps_all_answers(monkeypatch):
    calls = []

    def post(self, url, **kwargs):
        prompt = json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"])
        ids = [candidate["candidate_id"] for candidate in prompt["candidates"]]
        calls.append(ids)
        if len(ids) > 1:
            raise httpx.ReadTimeout("provider response timed out")
        return response(url, result_for(ids))

    monkeypatch.setattr(httpx.Client, "post", post)
    answers = reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert set(answers) == {"candidate_0001", "candidate_0002"}
    assert calls == [["candidate_0001", "candidate_0002"],
                     ["candidate_0001"], ["candidate_0002"]]


def test_read_timeout_retries_single_review_and_bounds_batch_splits(monkeypatch):
    calls = []

    def post(self, url, **kwargs):
        prompt = json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"])
        calls.append(len(prompt["candidates"]))
        raise httpx.ReadTimeout("provider response timed out")

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews()[:1], {})
    assert calls == [1, 1]

    calls.clear()
    base, hits = reviews()[1]
    rows = [({**base, "candidate_id": f"candidate_{i:04d}"}, hits) for i in range(8)]
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], rows, {})
    assert calls == [8, 4, 2]


def test_invalid_candidate_citation_is_discarded_without_losing_other_answers(monkeypatch, caplog):
    rows = reviews()
    rows[1] = (rows[1][0], [{"chunk_id": "law:2", "content": "다른 법령", "metadata": {}}])
    calls = []

    def post(self, url, **kwargs):
        calls.append(1)
        body = result_for(["candidate_0001", "candidate_0002"], {
            "candidate_0001": ["law:2"], "candidate_0002": ["law:2"],
        })
        items = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        items["items"][0]["status"] = "PRESENT"
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(items)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    caplog.set_level("WARNING", logger="app.analysis_llm")
    answers = reviewer().judge([{"clause_id": "c1", "text": "private contract content"}], rows, {})
    assert len(calls) == 1
    assert answers["candidate_0001"].status == "NEEDS_CONFIRMATION"
    assert answers["candidate_0001"].citation_chunk_ids == []
    assert answers["candidate_0002"].citation_chunk_ids == ["law:2"]
    assert "Gemini citation discarded" in caplog.text
    assert "private contract content" not in caplog.text


def test_no_candidates_skip_gemini(monkeypatch):
    monkeypatch.setattr(httpx.Client, "post", lambda *args, **kwargs: pytest.fail("unexpected call"))
    assert reviewer().judge([], [], {}) == {}


def test_scan_finding_accepts_only_its_own_law(monkeypatch):
    scan = ({"candidate_id": "scan_0001", "check_code": "DISCOVERED_ISSUE",
             "category": "CLAUSE_SCAN", "clause_id": "c1", "explanation": "추가 검토",
             "required_information": [], "retrieval_warnings": []}, reviews()[0][1])

    def post(self, url, **kwargs):
        body = result_for(["scan_0001"])
        item = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        item["items"][0]["findings"] = [{"category": "LEGAL_RISK", "explanation": "추가 문제",
            "required_information": [], "citation_chunk_ids": ["law:1"]}]
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(item)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    assert reviewer().judge([{"clause_id": "c1", "text": "원문"}], [scan], {})["scan_0001"].findings[0].explanation == "추가 문제"
    scan[1][0]["chunk_id"] = "law:2"
    assert reviewer().judge([{"clause_id": "c1", "text": "원문"}], [scan], {})["scan_0001"].findings[0].citation_chunk_ids == []


def test_candidate_finding_is_ignored_but_scan_finding_is_not(monkeypatch):
    def post(self, url, **kwargs):
        body = result_for(["candidate_0001", "candidate_0002"])
        items = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        items["items"][0]["findings"] = [{"category": "MISSING", "explanation": "중복 발견",
            "required_information": [], "citation_chunk_ids": []}]
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(items)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    answers = reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert answers["candidate_0001"].findings == []


def test_document_presence_requires_exact_contract_quote(monkeypatch):
    def post(self, url, **kwargs):
        body = result_for(["candidate_0001", "candidate_0002"])
        items = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        items["items"][0].update(document_presence="PRESENT", document_quote="없는 문구",
                                 document_clause_id="c1")
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(items)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})


def test_non_missing_document_fields_are_ignored(monkeypatch):
    def post(self, url, **kwargs):
        body = result_for(["candidate_0001", "candidate_0002"])
        items = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        items["items"][1].update(document_presence="PRESENT", document_quote="퇴사하면",
                                  document_clause_id="c1")
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(items)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    answer = reviewer().judge([{"clause_id": "c1", "text": "퇴사하면 위약금 100만원"}], reviews(), {})["candidate_0002"]
    assert answer.document_presence is None
    assert answer.document_quote is None
    assert answer.document_clause_id is None
