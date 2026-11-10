from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg.types.json import Jsonb

from app.access import connection, current_actor, owner_predicate, require_contract, require_csrf
from app.analysis import MAX_DOCUMENT_LENGTH, TextPage, stored_clauses
from app.api_docs import ENDPOINTS, UUID_EXAMPLE, error_response
from app.errors import APIError
from app.privacy import has_direct_identifier

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


class ConfirmedTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_kind: Literal["PDF", "IMAGES"]
    pages: list[TextPage] = Field(min_length=1, max_length=10)
    privacy_confirmed: Literal[True]
    gemini_notice_acknowledged: Literal[True]

    @model_validator(mode="after")
    def contiguous_pages(self):
        if [page.page for page in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("페이지를 1부터 순서대로 전달하세요.")
        return self


class ConfirmedTextOutput(BaseModel):
    contract_id: UUID
    revision_id: UUID


@router.post("", status_code=201, response_model=ConfirmedTextOutput,
             dependencies=[Depends(require_csrf)],
             summary="확인·마스킹된 근로계약서 텍스트 저장",
             description="브라우저에서 OCR·수정·마스킹을 마친 페이지별 텍스트만 저장합니다. PDF·이미지 원본은 받지 않습니다. Gemini 전송 안내 확인이 필요합니다.",
             responses={401: error_response("AUTHENTICATION_REQUIRED", "회원 세션 필요", "인증이 필요합니다."),
                        403: error_response("CSRF_FAILED", "CSRF 또는 Origin 오류", "보안 토큰을 확인하세요."),
                        413: error_response("REQUEST_TOO_LARGE", "본문 262,144바이트 초과", "요청 크기가 너무 큽니다."),
                        422: error_response("PERSONAL_DATA_DETECTED", "입력 형식·페이지 순서·원문 길이·개인정보 탐지 오류", "개인정보를 가린 뒤 다시 확인해 주세요."),
                        429: error_response("RATE_LIMITED", "세션당 분당 10회 초과", "잠시 후 다시 시도하세요.", retryable=True),
                        503: error_response("DATABASE_UNAVAILABLE", "DB 요청 실패", "데이터베이스 요청을 처리할 수 없습니다.", retryable=True)})
def create_confirmed_text(body: ConfirmedTextInput, request: Request,
                          conn=Depends(connection, scope="function")):
    actor = current_actor(request, conn)
    request.app.state.auth_limiter.check(f"contract-text:{actor.id}", limit=10)
    content = "\n".join(page.text for page in body.pages)
    if has_direct_identifier(content):
        raise APIError(422, "PERSONAL_DATA_DETECTED", "개인정보를 가린 뒤 다시 확인해 주세요.")
    if len(content) > MAX_DOCUMENT_LENGTH:
        raise APIError(422, "ANALYSIS_INPUT_LIMIT", "확정 원문 길이를 줄여 주세요.")
    page_ranges = []
    start = 0
    for page in body.pages:
        page_ranges.append({"page": page.page, "start": start, "end": start + len(page.text)})
        start += len(page.text) + 1
    stored_clauses(UUID(int=0), content, page_ranges)
    contract_id = conn.execute(
        "INSERT INTO checkit.contracts (user_id,contract_type,input_kind) "
        "VALUES (%s,'EMPLOYMENT',%s) RETURNING id", (actor.id, body.input_kind),
    ).fetchone()["id"]
    generation_id = conn.execute(
        "INSERT INTO checkit.file_generations (contract_id,input_kind) VALUES (%s,%s) RETURNING id",
        (contract_id, body.input_kind),
    ).fetchone()["id"]
    conn.execute("UPDATE checkit.contracts SET current_file_generation_id=%s WHERE id=%s",
                 (generation_id, contract_id))
    revision_id = conn.execute(
        "INSERT INTO checkit.text_revisions "
        "(contract_id,file_generation_id,revision,kind,content,blocks,confirmed_at) "
        "VALUES (%s,%s,1,'USER_EDITED',%s,%s,now()) RETURNING id",
        (contract_id, generation_id, content, Jsonb(page_ranges)),
    ).fetchone()["id"]
    return {"contract_id": contract_id, "revision_id": revision_id}


@router.get("", **ENDPOINTS["list"])
def list_contracts(request: Request,
                   limit: int = Query(default=20, ge=1, le=100, title="조회 개수",
                                      description="조회 개수. 1~100, 기본 20.", examples=[20]),
                   offset: int = Query(default=0, ge=0, le=10000, title="건너뛸 개수",
                                       description="건너뛸 개수. 0~10000, 기본 0.", examples=[0]),
                   conn=Depends(connection, scope="function")):
    actor = current_actor(request, conn)
    predicate, owner_id = owner_predicate(actor)
    rows = conn.execute(
        "SELECT id,contract_type,input_kind,created_at,updated_at "
        f"FROM checkit.contracts WHERE deletion_state='AVAILABLE' AND ({predicate}) "
        "ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s", (owner_id, limit, offset),
    ).fetchall()
    return {"contracts": rows, "limit": limit, "offset": offset}


@router.get("/{contract_id}", **ENDPOINTS["detail"])
def detail(request: Request,
           contract_id: UUID = Path(title="조회할 계약서 ID",
                                    description="필수. 목록에서 얻은 실제 계약서 UUID.",
                                    examples=[UUID_EXAMPLE]),
           conn=Depends(connection, scope="function")):
    actor = current_actor(request, conn)
    contract = require_contract(conn, actor, contract_id)
    # Metadata only. Never expose local paths/storage keys through the public response.
    generation = contract["current_file_generation_id"]
    files = conn.execute(
        "SELECT id,original_filename,media_type,size_bytes FROM checkit.file_assets "
        "WHERE contract_id=%s AND generation_id=%s AND role='ORIGINAL' ORDER BY created_at,id",
        (contract_id, generation),
    ).fetchall()
    pages = conn.execute(
        "SELECT id,file_asset_id,source_page_number,page_order,width,height,coordinate_unit "
        "FROM checkit.document_pages WHERE contract_id=%s AND generation_id=%s ORDER BY page_order",
        (contract_id, generation),
    ).fetchall()
    revision = conn.execute(
        "SELECT id,revision,kind,content,blocks,confirmed_at FROM checkit.text_revisions "
        "WHERE contract_id=%s AND file_generation_id=%s ORDER BY revision DESC LIMIT 1",
        (contract_id, generation),
    ).fetchone()
    result = conn.execute(
        "SELECT id,input_revision_id,file_generation_id,summary,completed_at "
        "FROM checkit.analysis_results WHERE contract_id=%s", (contract_id,),
    ).fetchone()
    if result:
        result["items"] = conn.execute(
            "SELECT id,check_code,labels,status,quoted_text,explanation,required_information,source_locations,rule_candidate "
            "FROM checkit.check_items WHERE result_id=%s ORDER BY created_at,id", (result["id"],),
        ).fetchall()
        counts = {status: 0 for status in ("CAUTION", "MISSING_SUSPECTED", "NEEDS_CONFIRMATION", "PRESENT")}
        for item in result["items"]:
            counts[item["status"]] += 1
        citations = conn.execute(
            "SELECT c.id,c.check_item_id,c.law_id,c.law_name,c.article_id,c.article_number,c.chunk_id,"
            "c.content,c.effective_date,c.source_url,c.corpus_version "
            "FROM checkit.law_citations c JOIN checkit.check_items i ON i.id=c.check_item_id "
            "WHERE i.result_id=%s ORDER BY c.created_at,c.id", (result["id"],),
        ).fetchall()
        result["counts"] = counts
        result["citations"] = citations
        result["is_current_generation"] = result["file_generation_id"] == generation
        result["is_current_revision"] = bool(revision and result["input_revision_id"] == revision["id"])
    # Recheck ownership/deletion after assembling text/results.
    require_contract(conn, actor, contract_id)
    return {"contract": contract, "files": files, "pages": pages, "text": revision, "current_result": result}
