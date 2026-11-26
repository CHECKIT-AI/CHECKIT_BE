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
        "source_url": "https://www.law.go.kr/1", "law_name": "근로기준법",
        "valid_from": "20260101", "valid_to": "20261231", "irrelevant": "omit",
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
    assert prompt["law_hits"][0]["metadata"]["valid_to"] == "20261231"
    assert "irrelevant" not in prompt["law_hits"][0]["metadata"]
    assert [candidate["law_chunk_ids"] for candidate in prompt["candidates"]] == [["law:1"], ["law:1"]]
    rules = " ".join(prompt["rules"])
    assert PROMPT_VERSION == "employment_review_v19"
    assert prompt["task"] == (
        "각 조항을 관련 법령 원문과 대조해 해당 문구에 법적 문제가 있는지 검토하세요. "
        "위법을 확정하지 마세요."
    )
    assert "제공된 law_hits의 실제 내용에서만" in rules
    assert "검색 순서나 법령 제목만으로 근거를 고르지 말고" in rules
    assert "그 candidate_id의 law_chunk_ids에 있는 ID" in rules
    assert "근거가 없으면 finding을 만들지 마세요" in rules
    assert "CLAUSE_SCAN은 해당 조항" in rules
    assert "NO_ISSUE_FOUND" in rules
    assert "위반 소지, 적용 요건 미충족" in rules
    assert calls[0]["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_document_review_receives_whole_contract_and_clause_results(monkeypatch):
    calls = []

    def post(self, url, **kwargs):
        calls.append(json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"]))
        return response(url, result_for(["candidate_0001"]))

    monkeypatch.setattr(httpx.Client, "post", post)
    clauses = [{"clause_id": "c1", "text": "임금 조항"},
               {"clause_id": "c2", "text": "근무 장소 조항"}]
    prior = [{"candidate_id": "scan_0001", "clause_id": "c1",
              "status": "CAUTION", "explanation": "검토 결과", "findings": []}]
    reviewer().judge(clauses, reviews()[:1], {}, clause_results=prior)
    assert calls[0]["document_clauses"] == clauses
    assert calls[0]["clause_review_results"] == prior
    assert "누락" in calls[0]["task"]
    rules = " ".join(calls[0]["rules"])
    assert "부속합의서·별도 서면" in rules
    assert "모든 MISSING 후보" in rules
    assert "법령이 부족해도 기재 여부는 별도로" in rules
    assert "ABSENT로 답하기 전에" in rules
    assert "항목 이름만 언급한 것은 실제 내용으로 간주하지 마세요" in rules
    assert "DOCUMENT_SCAN의 findings에는" in rules
    assert "DOCUMENT_SCAN의 finding은 MISSING만" in rules
    assert "CLAUSE_SCAN은" not in rules
    assert "NO_ISSUE_FOUND" not in rules


def test_presence_is_checked_without_law_and_kept_for_document_review(monkeypatch):
    prompts = []

    def post(self, url, **kwargs):
        prompt = json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"])
        prompts.append(prompt)
        body = result_for(["candidate_0001"])
        item = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        item["items"][0].update(status="MISSING_SUSPECTED", explanation="임금이 없습니다.",
                                document_presence="PRESENT" if len(prompts) == 1 else "ABSENT",
                                document_quote="기본급 278만 원" if len(prompts) == 1 else None,
                                document_clause_id="c1" if len(prompts) == 1 else None)
        if len(prompts) == 1:
            item["items"][0] = {name: item["items"][0][name] for name in (
                "candidate_id", "document_presence", "document_quote", "document_clause_id"
            )}
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(item)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    clauses = [{"clause_id": "c1", "text": "기본급 278만 원"}]
    missing = reviews()[:1]
    presence = reviewer().judge(clauses, [(missing[0][0], [])], {}, presence_only=True)
    answer = reviewer().judge(clauses, missing, {}, presence_results=presence)["candidate_0001"]
    assert "law_hits" not in prompts[0]
    assert "applicability" not in prompts[0]
    assert "'업무 중'처럼 단어만" in " ".join(prompts[0]["rules"])
    assert "월급·시급·일급 등 산정 단위" in " ".join(prompts[0]["rules"])
    assert "퇴직 후 미지급금 정산 기한" in " ".join(prompts[0]["rules"])
    assert prompts[1]["document_presence_results"][0]["document_quote"] == "기본급 278만 원"
    assert answer.document_presence == "PRESENT"
    assert answer.document_quote == "기본급 278만 원"
    assert answer.status == "NEEDS_CONFIRMATION"


@pytest.mark.parametrize("body", [
    {"candidates": []},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]},
    result_for(["candidate_0001"]),
    result_for(["candidate_0001", "candidate_0001"]),
])
def test_missing_duplicate_or_untrusted_answers_fail_without_retry(monkeypatch, body):
    calls = []

    def post(self, url, **kwargs):
        calls.append(1)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert len(calls) == 1


def test_rejected_response_logs_fixed_reason_without_contract_text(monkeypatch, caplog):
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kwargs:
                        response(url, result_for(["candidate_0001"])))
    caplog.set_level("WARNING", logger="app.analysis_llm")
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "private contract content"}], reviews(), {})
    assert "MISSING_OR_DUPLICATE_JUDGMENT" in caplog.text
    assert "private contract content" not in caplog.text


def test_input_limit_reports_failure_without_splitting(monkeypatch):
    calls = []

    def post(self, url, **kwargs):
        prompt = json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"])
        candidate_ids = [candidate["candidate_id"] for candidate in prompt["candidates"]]
        calls.append(candidate_ids)
        return httpx.Response(413, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(LLMInputTooLarge):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert calls == [["candidate_0001", "candidate_0002"]]


def test_read_timeout_fails_without_splitting(monkeypatch):
    calls = []

    def post(self, url, **kwargs):
        prompt = json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"])
        ids = [candidate["candidate_id"] for candidate in prompt["candidates"]]
        calls.append(ids)
        raise httpx.ReadTimeout("provider response timed out")

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert calls == [["candidate_0001", "candidate_0002"]]


@pytest.mark.parametrize("status", [503, 429])
def test_provider_error_stops_after_one_call(monkeypatch, status):
    calls = []

    def post(self, url, **kwargs):
        prompt = json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"])
        calls.append(len(prompt["candidates"]))
        return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(LLMUnavailable):
        reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert calls == [2]


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
    calls = []
    def post(self, url, **kwargs):
        calls.append(1)
        body = result_for(["candidate_0001", "candidate_0002"])
        items = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        items["items"][0].update(document_presence="PRESENT", document_quote="없는 문구",
                                 document_clause_id="c1", citation_chunk_ids=["law:1"])
        items["items"][1]["citation_chunk_ids"] = ["law:1"]
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(items)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    answers = reviewer().judge([{"clause_id": "c1", "text": "원문"}], reviews(), {})
    assert calls == [1]
    assert answers["candidate_0001"].document_presence == "UNCLEAR"
    assert answers["candidate_0001"].document_quote is None
    assert answers["candidate_0001"].citation_chunk_ids == ["law:1"]
    assert answers["candidate_0001"].status == "NEEDS_CONFIRMATION"
    assert answers["candidate_0002"].citation_chunk_ids == ["law:1"]


def test_missing_status_and_explanation_follow_document_evidence(monkeypatch):
    def post(self, url, **kwargs):
        body = result_for(["candidate_0001"])
        item = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        item["items"][0].update(status="MISSING_SUSPECTED", explanation="임금 항목이 없습니다.",
                                document_presence="PRESENT", document_quote="기본급 278만 원",
                                document_clause_id="c1")
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(item)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    answer = reviewer().judge([{"clause_id": "c1", "text": "기본급 278만 원"}], reviews()[:1], {})["candidate_0001"]
    assert answer.document_presence == "PRESENT"
    assert answer.status == "NEEDS_CONFIRMATION"
    assert "확인했습니다" in answer.explanation
    assert "없습니다" not in answer.explanation


def test_generic_work_mention_is_not_duties_evidence(monkeypatch):
    candidate = ({"candidate_id": "duties", "check_code": "MISSING_DUTIES",
                  "category": "MISSING", "clause_id": None, "explanation": "업무 확인",
                  "required_information": ["종사할 업무"], "retrieval_warnings": []}, [])

    def post(self, url, **kwargs):
        body = result_for(["duties"])
        item = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        item["items"][0].update(document_presence="PRESENT",
                                document_quote="업무 중 접한 자료는 외부에 전달하지 않는다.",
                                document_clause_id="c1")
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(item)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    answer = reviewer().judge([{"clause_id": "c1", "text": "업무 중 접한 자료는 외부에 전달하지 않는다."}],
                              [candidate], {})["duties"]
    assert answer.document_presence == "UNCLEAR"
    assert answer.status == "NEEDS_CONFIRMATION"


def test_final_pay_deadline_is_not_regular_payment_evidence(monkeypatch):
    candidate = ({"candidate_id": "payment", "check_code": "MISSING_WAGE_PAYMENT",
                  "category": "MISSING", "clause_id": None, "explanation": "지급 방법 확인",
                  "required_information": ["임금 지급 방법"], "retrieval_warnings": []}, [])

    def post(self, url, **kwargs):
        body = result_for(["payment"])
        item = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        item["items"][0].update(document_presence="PRESENT",
                                document_quote="퇴직 후 미지급 급여를 10일 안에 이체한다.",
                                document_clause_id="c1")
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(item)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    answer = reviewer().judge([{"clause_id": "c1", "text": "퇴직 후 미지급 급여를 10일 안에 이체한다."}],
                              [candidate], {})["payment"]
    assert answer.document_presence == "UNCLEAR"
    assert answer.status == "NEEDS_CONFIRMATION"


@pytest.mark.parametrize(("scan_category", "invalid_category", "valid_category"), [
    ("CLAUSE_SCAN", "MISSING", "LEGAL_RISK"),
    ("DOCUMENT_SCAN", "LEGAL_RISK", "MISSING"),
])
def test_invalid_scan_finding_does_not_discard_other_results(monkeypatch, scan_category,
                                                             invalid_category, valid_category):
    scan = ({"candidate_id": "scan_0001", "check_code": "DISCOVERED_ISSUE",
             "category": scan_category, "clause_id": "c1" if scan_category == "CLAUSE_SCAN" else None,
             "explanation": "추가 검토",
             "required_information": [], "retrieval_warnings": []}, reviews()[0][1])
    calls = []

    def post(self, url, **kwargs):
        calls.append(1)
        body = result_for(["scan_0001", "candidate_0002"])
        items = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        items["items"][0]["findings"] = [
            {"category": invalid_category, "explanation": "잘못된 추가 발견",
             "required_information": [], "citation_chunk_ids": []},
            {"category": valid_category, "explanation": "유효한 추가 발견",
             "required_information": [], "citation_chunk_ids": ["law:1"]},
        ]
        items["items"][1]["citation_chunk_ids"] = ["law:1"]
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(items)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    answers = reviewer().judge([{"clause_id": "c1", "text": "원문"}], [scan, reviews()[1]], {})
    assert calls == [1]
    assert [finding.explanation for finding in answers["scan_0001"].findings] == ["유효한 추가 발견"]
    assert answers["candidate_0002"].citation_chunk_ids == ["law:1"]


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


@pytest.mark.parametrize("explanation", [
    "법령의 요건을 충족하지 못합니다.",
    "근로자의 권리를 침해할 수 있으나 법적 문제가 없습니다.",
])
def test_no_issue_with_conflicting_explanation_is_held(monkeypatch, explanation):
    def post(self, url, **kwargs):
        body = result_for(["candidate_0002"])
        item = json.loads(body["candidates"][0]["content"]["parts"][0]["text"])
        item["items"][0].update(status="NO_ISSUE_FOUND", explanation=explanation)
        body["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(item)
        return response(url, body)

    monkeypatch.setattr(httpx.Client, "post", post)
    answer = reviewer().judge([{"clause_id": "c1", "text": "원문"}], [reviews()[1]], {})["candidate_0002"]
    assert answer.status == "NEEDS_CONFIRMATION"
    assert answer.explanation == "상태와 설명이 일치하지 않아 판단을 보류합니다."
