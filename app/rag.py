"""Local Data package adapter and authenticated retrieval route."""
from threading import Lock
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.access import current_actor, require_csrf
from app.api_docs import error_response
from app.errors import APIError

router = APIRouter(prefix="/api/rag", tags=["rag"])


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


class SearchHit(BaseModel):
    rank: int
    chunk_id: str
    cosine_distance: float = Field(description="낮을수록 가까운 검색 결과. 정확도 확률이 아닙니다.")
    content: str
    metadata: dict[str, str | int | float | bool]


class SearchOutput(BaseModel):
    corpus: str
    method: Literal["dense"]
    results: list[SearchHit]


class LocalSearch:
    """One model per process; reject concurrent inference instead of queuing it."""
    def __init__(self, settings):
        self.settings = settings
        self.service = None
        self.lock = Lock()

    def search(self, query, top_k):
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
                    )
                except Exception:
                    raise APIError(503, "RAG_UNAVAILABLE", "Data 패키지·인덱스·모델 준비 상태를 확인하세요.") from None
            try:
                return self.service.search(query, top_k)
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
    description='회원 또는 비회원 세션과 CSRF 헤더 필요. 입력: {"query":"검색 문장","top_k":5}. '
                '현재 근로기준법 검색만 지원합니다. 첫 요청은 모델 로딩으로 오래 걸릴 수 있습니다.',
    responses={
        401: error_response("AUTHENTICATION_REQUIRED", "회원·비회원 세션 필요", "인증이 필요합니다.", "LOGIN"),
        403: error_response("CSRF_FAILED", "CSRF 토큰 또는 Origin 오류", "보안 토큰을 확인하세요."),
        413: error_response("REQUEST_TOO_LARGE", "본문 16,384바이트 초과", "요청 크기가 너무 큽니다."),
        422: error_response("INVALID_INPUT", "입력 형식·길이·top_k 범위·모델 입력 제한 오류", "입력 형식을 확인하세요."),
        429: error_response("RATE_LIMITED", "세션당 분당 30회 초과", "잠시 후 다시 시도하세요.", retryable=True),
        503: error_response("RAG_UNAVAILABLE", "검색 비활성화·준비 실패·동시 처리 중 또는 DB 연결 실패", "검색 준비 상태를 확인하세요."),
    },
)
def search(body: SearchInput, request: Request, actor=Depends(search_actor)):
    request.app.state.auth_limiter.check(f"rag:{actor.kind}:{actor.id}", limit=30)
    return request.app.state.rag_search.search(body.query, body.top_k)
