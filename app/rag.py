"""Local Data package adapter and authenticated retrieval route."""
from threading import Lock
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.access import current_actor, require_csrf
from app.api_docs import error_response
from app.errors import APIError

router = APIRouter(prefix="/api/rag", tags=["rag"])

ClauseLabel = Literal["임금", "근로시간", "휴일", "휴가", "근무 장소·업무", "계약기간", "계약 종료",
                      "손해배상·위약금", "기타 근로조건", "그 외"]


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000, description="검색할 질문 또는 계약 문구. 1~2000자.")
    top_k: int = Field(default=5, ge=1, le=10, strict=True, description="반환할 조문 수. 1~10, 기본 5.")

    @field_validator("query")
    @classmethod
    def strip_query(cls, value):
        if not value.strip():
            raise ValueError("검색 문장을 입력하세요.")
        return value.strip()


class ClauseSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clause_id: str = Field(min_length=1, max_length=128, description="원본 조항과 연결할 ID")
    labels: list[ClauseLabel] = Field(min_length=1, max_length=10, description="분류 모델의 복수 라벨. 법률 판정 결과가 아닙니다.")
    text: str = Field(min_length=1, max_length=2000, description="해당 조항 원문. 실제 금액·시간·날짜를 보존합니다.")
    top_k: int = Field(default=5, ge=1, le=10, strict=True)

    @field_validator("clause_id", "text")
    @classmethod
    def strip_nonempty(cls, value):
        if not value.strip():
            raise ValueError("조항 ID와 원문을 입력하세요.")
        return value.strip()

    @field_validator("labels")
    @classmethod
    def unique_labels(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("중복된 라벨입니다.")
        return value


class SearchHit(BaseModel):
    rank: int
    chunk_id: str
    cosine_distance: float | None = Field(default=None, description="낮을수록 가까운 벡터 거리. 키워드 전용 후보는 null이며 정확도 확률이 아닙니다.")
    reranker_score: float | None = Field(default=None, description="재정렬 모델의 raw logit. 확률이 아닙니다.")
    content: str
    metadata: dict[str, str | int | float | bool]
    base_rank: int | None = Field(default=None, description="라벨 우선순위 적용 전 순위")
    matched_labels: list[ClauseLabel] = Field(default_factory=list)
    label_priority_score: float | None = Field(default=None, description="검색 점수에 제한된 라벨 보너스를 더한 값. 확률이 아닙니다.")


class SearchOutput(BaseModel):
    corpus: str
    method: Literal["dense", "hybrid_rerank"]
    results: list[SearchHit]
    warnings: list[str] = Field(default_factory=list)
    clause_id: str | None = None
    labels: list[ClauseLabel] = Field(default_factory=list)
    retrieval_policy: Literal["labels_soft_priority_v1"] | None = None


class LocalSearch:
    """One model per process; reject concurrent inference instead of queuing it."""
    def __init__(self, settings):
        self.settings = settings
        self.service = None
        self.lock = Lock()

    def search(self, query, top_k):
        return self._run(lambda service: service.search(query, top_k))

    def search_clause(self, clause_id, text, labels, top_k):
        return self._run(lambda service: service.search_clause(clause_id, text, labels, top_k))

    def _run(self, invoke):
        if not self.settings.rag_enabled:
            raise APIError(503, "RAG_DISABLED", "검색 기능을 활성화해야 합니다.")
        if not self.lock.acquire(blocking=False):
            raise APIError(503, "RAG_BUSY", "검색 처리 중입니다. 잠시 후 다시 시도하세요.", retryable=True)
        try:
            if self.service is None:
                try:
                    from RAG.service import LawSearchService
                    self.service = LawSearchService(
                        corpus=self.settings.rag_corpus, device=self.settings.rag_device,
                        method=self.settings.rag_method,
                    )
                except Exception:
                    raise APIError(503, "RAG_UNAVAILABLE", "Data 패키지·인덱스·모델 준비 상태를 확인하세요.") from None
            try:
                return invoke(self.service)
            except ValueError:
                raise APIError(422, "RAG_INPUT_LIMIT", "모델 입력 제한을 확인하고 검색 문장을 줄여 주세요.") from None
            except Exception:
                raise APIError(503, "RAG_UNAVAILABLE", "검색 요청을 처리할 수 없습니다.", retryable=True) from None
        finally:
            self.lock.release()


def search_actor(request: Request):
    # Release the DB connection before loading the model or doing inference.
    with request.app.state.database_pool.connection() as conn:
        return current_actor(request, conn)


@router.post(
    "/search", response_model=SearchOutput, dependencies=[Depends(require_csrf)],
    summary="관련 법령 검색",
    description='회원 또는 비회원 세션과 CSRF 헤더 필요. 기본 입력: '
                '{"clause_id":"clause_007","labels":["임금"],"text":"해당 조항 원문","top_k":5}. '
                '라벨은 작은 우선순위 신호이며 검색 범위를 차단하지 않습니다. '
                '기존 {"query":"검색 문장","top_k":5} 형식도 지원합니다. 두 형식을 섞을 수 없습니다. '
                '설정된 법령 인덱스를 검색합니다. 기본 인덱스는 근로관계 12개 법령·선택 별표·2026년 최저임금 고시입니다. '
                '명시한 연도와 연간 고시 기간을 대조하며, 일반 법령의 과거 버전은 자동 복원하지 않습니다. '
                '첫 요청은 모델 로딩으로 오래 걸릴 수 있습니다.',
    responses={
        401: error_response("AUTHENTICATION_REQUIRED", "회원·비회원 세션 필요", "인증이 필요합니다.", "LOGIN"),
        403: error_response("CSRF_FAILED", "CSRF 토큰 또는 Origin 오류", "보안 토큰을 확인하세요."),
        413: error_response("REQUEST_TOO_LARGE", "본문 16,384바이트 초과", "요청 크기가 너무 큽니다."),
        422: error_response("INVALID_INPUT", "입력 형식·길이·top_k 범위·모델 입력 제한 오류", "입력 형식을 확인하세요."),
        429: error_response("RATE_LIMITED", "세션당 분당 30회 초과", "잠시 후 다시 시도하세요.", retryable=True),
        503: error_response("RAG_UNAVAILABLE", "검색 비활성화·준비 실패·동시 처리 중 또는 DB 연결 실패", "검색 준비 상태를 확인하세요."),
    },
)
def search(body: ClauseSearchInput | SearchInput, request: Request, actor=Depends(search_actor)):
    request.app.state.auth_limiter.check(f"rag:{actor.kind}:{actor.id}", limit=30)
    if isinstance(body, ClauseSearchInput):
        return request.app.state.rag_search.search_clause(body.clause_id, body.text, body.labels, body.top_k)
    return request.app.state.rag_search.search(body.query, body.top_k)
