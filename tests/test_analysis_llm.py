import json

import httpx
import pytest
from pydantic import SecretStr

from app.analysis_llm import GeminiReviewer, LLMUnavailable
from app.config import Settings


def reviewer():
    return GeminiReviewer(Settings(_env_file=None, gemini_api_key=SecretStr("test-key")))


def test_gemini_structured_json_and_citation_allowlist(monkeypatch):
    captured = {}

    def post(self, url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
                "status": "CAUTION", "explanation": "검토 필요", "required_information": [],
                "citation_chunk_ids": ["law:1"],
            })}]},
        }]})

    monkeypatch.setattr(httpx.Client, "post", post)
    result = reviewer().judge({"quoted_text": "원문"},
                              [{"chunk_id": "law:1", "content": "법령", "metadata": {}}], {})
    assert result.status == "CAUTION"
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("body", [
    {"candidates": []},
    {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
        "status": "CAUTION", "explanation": "검토", "required_information": [],
        "citation_chunk_ids": ["invented"],
    })}]}}]},
])
def test_gemini_failure_or_untrusted_citation_fails_closed(monkeypatch, body):
    def post(self, url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(LLMUnavailable):
        reviewer().judge({}, [{"chunk_id": "law:1", "content": "법령", "metadata": {}}], {})
