from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request

from app.access import (claim_contract, connection, cookie_names, current_actor,
                        guest, member, owner_predicate, require_contract, require_csrf)
from app.api_docs import ENDPOINTS, UUID_EXAMPLE
from app.errors import APIError

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.get("", **ENDPOINTS["list"])
def list_contracts(request: Request,
                   limit: int = Query(default=20, ge=1, le=100, title="조회 개수",
                                      description="선택. 한 번에 받을 기록 수. 정수 1~100, 기본 20.", examples=[20]),
                   offset: int = Query(default=0, ge=0, le=10000, title="건너뛸 개수",
                                       description="선택. 앞에서 건너뛸 기록 수. 정수 0~10000, 기본 0. 다음 20개는 offset=20.", examples=[0]),
                   conn=Depends(connection, scope="function")):
    actor = current_actor(request, conn)
    predicate, owner_id = owner_predicate(actor)
    rows = conn.execute(
        "SELECT id,contract_type,input_kind,created_at,updated_at,expires_at "
        f"FROM checkit.contracts WHERE deletion_state='AVAILABLE' AND ({predicate}) "
        "ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s", (owner_id, limit, offset),
    ).fetchall()
    return {"contracts": rows, "limit": limit, "offset": offset}


@router.get("/{contract_id}", **ENDPOINTS["detail"])
def detail(request: Request,
           contract_id: UUID = Path(title="조회할 계약서 ID",
                                    description="필수 UUID. GET /api/contracts 응답의 contracts[].id에 있는 실제 본인 계약서 ID를 입력하세요. 아래 값은 형식 예시입니다.",
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
            "SELECT id,check_code,labels,status,quoted_text,explanation,required_information,source_locations "
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
    # Recheck expiry/deletion after assembling text/results; long reads must not extend access.
    require_contract(conn, actor, contract_id)
    return {"contract": contract, "files": files, "pages": pages, "text": revision, "current_result": result}


@router.post("/{contract_id}/claim", dependencies=[Depends(require_csrf)], **ENDPOINTS["claim"])
def claim(request: Request,
          contract_id: UUID = Path(title="회원 계정에 저장할 계약서 ID",
                                   description="필수 UUID. 같은 브라우저에서 만든 유효한 비회원 완료 결과의 실제 계약서 ID. 현재 회원과 원래 비회원 쿠키가 함께 필요합니다.",
                                   examples=[UUID_EXAMPLE]),
          conn=Depends(connection, scope="function")):
    names = cookie_names(request.app.state.settings)
    owner = member(conn, request.cookies.get(names["session"]))
    try:
        visitor = guest(conn, request.cookies.get(names["guest"]))
    except APIError:
        visitor = None
    return claim_contract(conn, owner, visitor, contract_id)
