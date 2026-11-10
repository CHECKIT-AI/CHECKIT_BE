"""OCR-bypass contract analysis orchestration through classification and law retrieval."""

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.access import current_actor, require_csrf
from app.api_docs import error_response
from app.classifier import ClassificationOutput
from app.errors import APIError
from app.rag import SearchHit
from app.privacy import has_direct_identifier


router = APIRouter(prefix="/api/analysis", tags=["analysis"])

MAX_CLAUSE_LENGTH = 2000
MAX_CLAUSES = 100
MAX_DOCUMENT_LENGTH = 30000
HEADING = re.compile(
    r"(?m)^(?=(?:제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^\n)]*\))?|\d+\s*[.)]|[가-하]\s*[.)])\s*)"
)


class TextPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, le=500, strict=True)
    text: str = Field(min_length=1, max_length=20000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value):
        if not value.strip():
            raise ValueError("페이지 원문이 필요합니다.")
        return value.strip()


class ContractTextAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    pages: list[TextPage] = Field(min_length=1, max_length=100)
    top_k: int = Field(default=5, ge=1, le=10, strict=True)

    @field_validator("contract_id")
    @classmethod
    def strip_contract_id(cls, value):
        return value.strip()

    @field_validator("pages")
    @classmethod
    def unique_ordered_pages(cls, value):
        numbers = [page.page for page in value]
        if len(numbers) != len(set(numbers)):
            raise ValueError("페이지 번호가 중복되었습니다.")
        if numbers != sorted(numbers):
            raise ValueError("페이지를 번호순으로 전달하세요.")
        return value


class ClauseSource(BaseModel):
    page: int
    ordinal_on_page: int


class LawCandidate(BaseModel):
    rank: int
    chunk_id: str
    content: str
    metadata: dict[str, str | int | float | bool]


class LLMClauseContext(BaseModel):
    clause_id: str
    page: int
    clause_text: str
    classifier_labels: list[str]
    law_candidates: list[LawCandidate]
    instruction_scope: Literal["ISSUE_AND_APPLICABILITY_REVIEW"] = "ISSUE_AND_APPLICABILITY_REVIEW"


class AnalyzedClause(BaseModel):
    clause_id: str
    source: ClauseSource
    text: str
    classification: ClassificationOutput
    corpus: str
    retrieval_method: Literal["dense", "hybrid_rerank"]
    retrieval_policy: Literal["labels_soft_priority_v1"] | None = None
    retrieval_results: list[SearchHit]
    retrieval_warnings: list[str] = Field(default_factory=list)
    llm_context: LLMClauseContext


class ContractAnalysisOutput(BaseModel):
    contract_id: str
    input_mode: Literal["OCR_BYPASS_TEXT"] = "OCR_BYPASS_TEXT"
    stages_completed: list[Literal["OCR_SKIPPED", "CLAUSE_COMPLETE", "CLASSIFICATION_COMPLETE", "RETRIEVAL_COMPLETE"]]
    clauses: list[AnalyzedClause]
    document_context: dict[str, object]


def split_page_clauses(text: str) -> list[str]:
    """Split clean OCR text without rewriting or normalizing the source wording."""
    starts = [match.start() for match in HEADING.finditer(text)]
    if starts:
        if starts[0] > 0 and text[:starts[0]].strip():
            starts.insert(0, 0)
        starts.append(len(text))
        clauses = [text[starts[i]:starts[i + 1]].strip() for i in range(len(starts) - 1)]
    else:
        clauses = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    return clauses or [text.strip()]


def split_contract(contract_id: str, pages: list[TextPage]):
    output = []
    sequence = 0
    for page in pages:
        for ordinal, text in enumerate(split_page_clauses(page.text), 1):
            if len(text) > MAX_CLAUSE_LENGTH:
                raise APIError(
                    422, "CLAUSE_TOO_LONG",
                    f"{page.page}페이지 {ordinal}번째 조항이 분류 입력 제한을 초과합니다.",
                )
            sequence += 1
            output.append({
                "clause_id": f"{contract_id}:c{sequence:04d}",
                "page": page.page, "ordinal_on_page": ordinal, "text": text,
            })
    return output


def stored_clauses(contract_id: UUID, content: str, blocks: list | None = None) -> list[dict]:
    page_ranges = blocks if blocks and all(
        isinstance(block, dict) and set(block) == {"page", "start", "end"}
        for block in blocks
    ) else [{"page": None, "start": 0, "end": len(content)}]
    parts = [(block["page"], text) for block in page_ranges
             for text in split_page_clauses(content[block["start"]:block["end"]])]
    if (len(content) > MAX_DOCUMENT_LENGTH or len(parts) > MAX_CLAUSES
            or any(len(text) > MAX_CLAUSE_LENGTH for _, text in parts)):
        raise APIError(422, "ANALYSIS_INPUT_LIMIT", "확정 원문의 조항 수 또는 조항 길이를 줄여 주세요.")
    return [{"clause_id": f"{contract_id}:c{i:04d}", "page": page, "text": text}
            for i, (page, text) in enumerate(parts, 1)]


def analysis_actor(request: Request):
    with request.app.state.database_pool.connection() as conn:
        return current_actor(request, conn)


@router.post(
    "/contracts/text", response_model=ContractAnalysisOutput,
    dependencies=[Depends(require_csrf)],
    summary="OCR 우회 계약서 조항 분류·법령 검색",
    description="정제된 페이지별 계약서 원문을 조항으로 분리하고, 각 조항을 멀티라벨 분류한 뒤 employment_basic_v004 법령 검색 결과와 LLM 전달용 컨텍스트를 반환합니다. 실제 LLM 판단은 수행하지 않습니다.",
    responses={
        401: error_response("AUTHENTICATION_REQUIRED", "회원 세션 필요", "인증이 필요합니다.", "LOGIN"),
        403: error_response("CSRF_FAILED", "CSRF 토큰 또는 Origin 오류", "보안 토큰을 확인하세요."),
        413: error_response("REQUEST_TOO_LARGE", "본문 262,144바이트 초과", "요청 크기가 너무 큽니다."),
        422: error_response("PERSONAL_DATA_DETECTED", "입력 형식·페이지 순서·조항 길이·개인정보 탐지 오류", "개인정보를 가린 뒤 다시 확인해 주세요."),
        429: error_response("RATE_LIMITED", "세션당 분당 10회 초과", "잠시 후 다시 시도하세요.", retryable=True),
        503: error_response("ANALYSIS_UNAVAILABLE", "분류 또는 검색 준비 실패", "분류 모델과 RAG 준비 상태를 확인하세요.", retryable=True),
    },
)
def analyze_contract_text(body: ContractTextAnalysisInput, request: Request,
                          actor=Depends(analysis_actor)):
    request.app.state.auth_limiter.check(f"analysis:{actor.kind}:{actor.id}", limit=10)
    if any(has_direct_identifier(page.text) for page in body.pages):
        raise APIError(422, "PERSONAL_DATA_DETECTED", "개인정보를 가린 뒤 다시 확인해 주세요.")
    clauses = split_contract(body.contract_id, body.pages)
    analyzed = []
    label_coverage = set()
    for clause in clauses:
        classification = request.app.state.classifier.predict(clause["text"])
        labels = classification["labels"]
        label_coverage.update(labels)
        retrieval = request.app.state.rag_search.search_clause(
            clause["clause_id"], clause["text"], labels, body.top_k,
        )
        candidates = [{
            "rank": hit["rank"], "chunk_id": hit["chunk_id"],
            "content": hit["content"], "metadata": hit["metadata"],
        } for hit in retrieval["results"]]
        analyzed.append({
            "clause_id": clause["clause_id"],
            "source": {"page": clause["page"], "ordinal_on_page": clause["ordinal_on_page"]},
            "text": clause["text"], "classification": classification,
            "corpus": retrieval["corpus"], "retrieval_method": retrieval["method"],
            "retrieval_policy": retrieval.get("retrieval_policy"),
            "retrieval_results": retrieval["results"],
            "retrieval_warnings": retrieval.get("warnings", []),
            "llm_context": {
                "clause_id": clause["clause_id"], "page": clause["page"],
                "clause_text": clause["text"], "classifier_labels": labels,
                "law_candidates": candidates,
            },
        })
    return {
        "contract_id": body.contract_id, "input_mode": "OCR_BYPASS_TEXT",
        "stages_completed": ["OCR_SKIPPED", "CLAUSE_COMPLETE", "CLASSIFICATION_COMPLETE", "RETRIEVAL_COMPLETE"],
        "clauses": analyzed,
        "document_context": {
            "clause_count": len(analyzed), "page_count": len(body.pages),
            "classifier_label_coverage": sorted(label_coverage),
            "missing_required_review_needed": True,
            "note": "누락 분석은 전체 조항 목록과 근로형태·사업장 적용요건을 함께 LLM에 전달해 별도 수행해야 합니다.",
        },
    }
