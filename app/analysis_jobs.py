"""Persisted, member-owned employment contract analysis jobs."""

from datetime import date
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb

from app.access import connection, current_actor, require_contract, require_csrf
from app.analysis import MAX_CLAUSE_LENGTH, split_page_clauses
from app.analysis_llm import GeminiReviewer, LLMUnavailable, PROMPT_VERSION
from app.analysis_rules import RULE_VERSION, candidates
from app.api_docs import error_response
from app.errors import APIError, not_found

router = APIRouter(prefix="/api/analysis/contracts", tags=["analysis"])
MAX_CLAUSES = 100
MAX_CANDIDATES = 50
MAX_DOCUMENT_LENGTH = 30000


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_date: date | None = None
    employee_count: int | None = Field(default=None, ge=1, le=100000, strict=True)
    work_type: str | None = Field(default=None, max_length=80)
    weekly_hours: float | None = Field(default=None, gt=0, le=168)
    top_k: int = Field(default=5, ge=1, le=10, strict=True)


class JobAccepted(BaseModel):
    job_id: UUID
    status: str


class JobStatus(BaseModel):
    job_id: UUID
    status: str
    stage: str | None
    error_code: str | None
    result: dict | None


def stored_clauses(contract_id: UUID, content: str) -> list[dict]:
    # text_revisions.content is a single confirmed document, not a page map.
    parts = split_page_clauses(content)
    if (len(content) > MAX_DOCUMENT_LENGTH or len(parts) > MAX_CLAUSES
            or any(len(part) > MAX_CLAUSE_LENGTH for part in parts)):
        raise APIError(422, "ANALYSIS_INPUT_LIMIT", "확정 원문의 조항 수 또는 조항 길이를 줄여 주세요.")
    return [{"clause_id": f"{contract_id}:c{i:04d}", "page": None, "text": text}
            for i, text in enumerate(parts, 1)]


def _revision(conn, contract_id, generation):
    return conn.execute(
        "SELECT id,content FROM checkit.text_revisions "
        "WHERE contract_id=%s AND file_generation_id=%s AND confirmed_at IS NOT NULL "
        "ORDER BY revision DESC LIMIT 1", (contract_id, generation),
    ).fetchone()


@router.post(
    "/{contract_id}/jobs", status_code=202, response_model=JobAccepted,
    dependencies=[Depends(require_csrf)], summary="확정 근로계약서 분석 job 생성",
    description="회원 소유 계약서의 현재 세대·최신 확정 원문을 분류·규칙 검사·법령 검색·Gemini JSON 판단하고 결과를 저장합니다.",
    responses={401: error_response("AUTHENTICATION_REQUIRED", "회원 세션 필요", "인증이 필요합니다."),
               403: error_response("CSRF_FAILED", "CSRF 또는 Origin 오류", "보안 토큰을 확인하세요."),
               404: error_response("CONTRACT_NOT_FOUND", "접근 가능한 계약서 없음", "접근 가능한 계약서를 찾을 수 없습니다."),
               413: error_response("REQUEST_TOO_LARGE", "본문 262,144바이트 초과", "요청 크기가 너무 큽니다."),
               409: error_response("ANALYSIS_CONFLICT", "확정 원문 없음 또는 분석 진행 중", "계약서 상태를 확인하세요."),
               422: error_response("ANALYSIS_INPUT_LIMIT", "입력 형식 또는 원문 길이 오류", "입력을 확인하세요."),
               429: error_response("RATE_LIMITED", "세션당 분당 10회 초과", "잠시 후 다시 시도하세요.", retryable=True),
               503: error_response("ANALYSIS_UNAVAILABLE", "분석 기능 미설정", "분석 설정을 확인하세요.")},
)
def create_job(body: JobInput, background: BackgroundTasks, request: Request,
               contract_id: UUID = Path(), conn=Depends(connection, scope="function")):
    actor = current_actor(request, conn)
    request.app.state.auth_limiter.check(f"analysis:{actor.kind}:{actor.id}", limit=10)
    settings = request.app.state.settings
    if not (settings.classifier_enabled and settings.rag_enabled and settings.gemini_api_key.get_secret_value()):
        raise APIError(503, "ANALYSIS_UNAVAILABLE", "분석 기능 설정을 확인하세요.")
    contract = require_contract(conn, actor, contract_id, lock=True)
    if contract["contract_type"] != "EMPLOYMENT" or not contract["current_file_generation_id"]:
        raise APIError(409, "ANALYSIS_INPUT_UNAVAILABLE", "분석 가능한 근로계약서가 아닙니다.")
    revision = _revision(conn, contract_id, contract["current_file_generation_id"])
    if not revision:
        raise APIError(409, "ANALYSIS_INPUT_UNAVAILABLE", "현재 세대의 확정 원문이 필요합니다.")
    stored_clauses(contract_id, revision["content"])
    context = body.model_dump(mode="json")
    job_id = uuid4()
    try:
        conn.execute(
            "INSERT INTO checkit.analysis_jobs "
            "(id,request_id,contract_id,kind,file_generation_id,input_revision_id,status,analysis_context) "
            "VALUES (%s,%s,%s,'ANALYSIS',%s,%s,'QUEUED',%s)",
            (job_id, uuid4(), contract_id, contract["current_file_generation_id"],
             revision["id"], Jsonb(context)),
        )
    except Exception as exc:
        # The partial unique index enforces one active analysis per contract.
        if getattr(exc, "sqlstate", None) == "23505":
            raise APIError(409, "ANALYSIS_CONFLICT", "이미 분석이 진행 중입니다.") from None
        raise
    background.add_task(run_job, request.app, job_id)
    return {"job_id": job_id, "status": "QUEUED"}


@router.get(
    "/{contract_id}/jobs/{job_id}", response_model=JobStatus, summary="분석 job 상태 조회",
    description="회원 소유 계약서의 job 상태와 성공 시 저장된 JSON 점검 결과를 반환합니다.",
    responses={401: error_response("AUTHENTICATION_REQUIRED", "회원 세션 필요", "인증이 필요합니다."),
               404: error_response("CONTRACT_NOT_FOUND", "계약서 또는 job 없음", "접근 가능한 계약서를 찾을 수 없습니다."),
               503: error_response("DATABASE_UNAVAILABLE", "DB 요청 실패", "데이터베이스 요청을 처리할 수 없습니다.", retryable=True)},
)
def get_job(request: Request, contract_id: UUID, job_id: UUID,
            conn=Depends(connection, scope="function")):
    actor = current_actor(request, conn)
    require_contract(conn, actor, contract_id)
    job = conn.execute(
        "SELECT id,status,stage,error_code FROM checkit.analysis_jobs "
        "WHERE id=%s AND contract_id=%s AND kind='ANALYSIS'", (job_id, contract_id),
    ).fetchone()
    if not job:
        raise not_found()
    result = None
    if job["status"] == "SUCCEEDED":
        result = conn.execute(
            "SELECT id,summary,completed_at,model_versions,prompt_version,corpus_version,rule_version "
            "FROM checkit.analysis_results WHERE job_id=%s", (job_id,),
        ).fetchone()
        if result:
            result["items"] = conn.execute(
                "SELECT id,check_code,labels,status,quoted_text,explanation,required_information,source_locations,rule_candidate "
                "FROM checkit.check_items WHERE result_id=%s ORDER BY created_at,id", (result["id"],),
            ).fetchall()
            result["citations"] = conn.execute(
                "SELECT c.check_item_id,c.law_id,c.law_name,c.article_id,c.article_number,c.chunk_id,"
                "c.content,c.effective_date,c.source_url,c.corpus_version "
                "FROM checkit.law_citations c JOIN checkit.check_items i ON i.id=c.check_item_id "
                "WHERE i.result_id=%s ORDER BY c.created_at,c.id", (result["id"],),
            ).fetchall()
    return {"job_id": job_id, "status": job["status"], "stage": job["stage"],
            "error_code": job["error_code"], "result": result}


def _stage(pool, job_id, stage):
    with pool.connection() as conn:
        conn.execute("UPDATE checkit.analysis_jobs SET stage=%s WHERE id=%s AND status='RUNNING'", (stage, job_id))


def _law_hits(search, candidate, top_k):
    if candidate["clause_id"]:
        return search.search_clause(candidate["clause_id"], candidate["quoted_text"],
                                    candidate["labels"], top_k)
    return search.search(candidate["explanation"] + " 근로기준법 근로조건 명시", top_k)


def _save_result(conn, job, clauses, classified, decisions, corpus, model):
    contract = conn.execute(
        "SELECT current_file_generation_id,deletion_state FROM checkit.contracts WHERE id=%s FOR UPDATE",
        (job["contract_id"],),
    ).fetchone()
    revision = _revision(conn, job["contract_id"], job["file_generation_id"])
    if (not contract or contract["deletion_state"] != "AVAILABLE"
            or contract["current_file_generation_id"] != job["file_generation_id"]
            or not revision or revision["id"] != job["input_revision_id"]):
        raise APIError(409, "ANALYSIS_STALE_INPUT", "분석 중 계약서 입력이 변경되었습니다.")
    conn.execute("DELETE FROM checkit.analysis_results WHERE contract_id=%s", (job["contract_id"],))
    counts = {status: sum(1 for _, answer, _ in decisions if answer.status == status)
              for status in ("CAUTION", "MISSING_SUSPECTED", "NEEDS_CONFIRMATION", "PRESENT")}
    summary = f"{len(clauses)}개 조항, {len(decisions)}개 후보 검토: " + ", ".join(
        f"{key} {value}건" for key, value in counts.items())
    result_id = conn.execute(
        "INSERT INTO checkit.analysis_results "
        "(contract_id,job_id,file_generation_id,input_revision_id,summary,model_versions,prompt_version,corpus_version,rule_version) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (job["contract_id"], job["id"], job["file_generation_id"], job["input_revision_id"],
         summary, Jsonb({"classifier_model": classified[0]["model_id"] if classified else "",
                         "classifier_revision": classified[0]["revision"] if classified else "",
                         "gemini_model": model}), PROMPT_VERSION, corpus, RULE_VERSION),
    ).fetchone()["id"]
    for candidate, answer, hits in decisions:
        item_id = conn.execute(
            "INSERT INTO checkit.check_items "
            "(result_id,check_code,labels,status,quoted_text,explanation,required_information,source_locations,rule_candidate) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (result_id, candidate["check_code"], Jsonb(candidate["labels"]), answer.status,
             candidate["quoted_text"], answer.explanation, Jsonb(answer.required_information),
             Jsonb(candidate["source_locations"]), Jsonb(candidate)),
        ).fetchone()["id"]
        by_id = {hit["chunk_id"]: hit for hit in hits}
        for chunk_id in answer.citation_chunk_ids:
            hit = by_id[chunk_id]
            meta = hit["metadata"]
            source = meta.get("source_url", "")
            if not source.startswith("https://"):
                raise ValueError("citation has no trusted source URL")
            effective = meta.get("article_effective_date") or meta.get("snapshot_effective_date")
            effective_date = date.fromisoformat(effective) if effective and "-" in effective else (
                date.fromisoformat(f"{effective[:4]}-{effective[4:6]}-{effective[6:8]}") if effective else None)
            conn.execute(
                "INSERT INTO checkit.law_citations "
                "(check_item_id,law_id,law_name,article_id,article_number,chunk_id,content,effective_date,source_url,corpus_version) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (item_id, str(meta.get("law_id") or meta.get("notice_id") or "notice"),
                 str(meta.get("law_name") or meta.get("notice_title") or "최저임금 고시"),
                 str(meta.get("article_id") or chunk_id),
                 str(meta.get("article_no", "")), chunk_id, hit["content"], effective_date,
                 source, corpus),
            )
    conn.execute(
        "UPDATE checkit.analysis_jobs SET status='SUCCEEDED',stage='EXPLAIN',finished_at=now() WHERE id=%s",
        (job["id"],),
    )


def run_job(app, job_id: UUID):
    pool = app.state.database_pool
    try:
        with pool.connection() as conn:
            job = conn.execute(
                "UPDATE checkit.analysis_jobs SET status='RUNNING',stage='CLASSIFY',started_at=now() "
                "WHERE id=%s AND status='QUEUED' RETURNING id,contract_id,file_generation_id,input_revision_id,analysis_context",
                (job_id,),
            ).fetchone()
            if not job:
                return
            revision = _revision(conn, job["contract_id"], job["file_generation_id"])
            if not revision or revision["id"] != job["input_revision_id"]:
                raise APIError(409, "ANALYSIS_STALE_INPUT", "분석 중 계약서 입력이 변경되었습니다.")
            clauses = stored_clauses(job["contract_id"], revision["content"])
        classified = [app.state.classifier.predict(clause["text"]) for clause in clauses]
        found = candidates(clauses, classified, job["analysis_context"])
        if len(found) > MAX_CANDIDATES:
            raise APIError(422, "ANALYSIS_INPUT_LIMIT", "문제 후보 수가 분석 제한을 초과했습니다.")
        _stage(pool, job_id, "RETRIEVE")
        reviewer = app.state.gemini_reviewer
        decisions = []
        corpus = app.state.settings.rag_corpus
        for candidate in found:
            retrieved = _law_hits(app.state.rag_search, candidate, job["analysis_context"]["top_k"])
            corpus = retrieved["corpus"]
            hits = retrieved["results"]
            _stage(pool, job_id, "EVALUATE")
            review_input = {**candidate}
            if candidate["clause_id"] is None:
                review_input["document_clauses"] = [
                    {"clause_id": clause["clause_id"], "text": clause["text"],
                     "labels": classification["labels"]}
                    for clause, classification in zip(clauses, classified)
                ]
            review_input["retrieval_warnings"] = retrieved.get("warnings", [])
            answer = reviewer.judge(review_input, hits, job["analysis_context"])
            # The 2026-only reviewed notice cannot substantiate other-year conclusions.
            effective = job["analysis_context"].get("effective_date")
            if not effective or date.fromisoformat(effective).year != 2026:
                answer.status = "NEEDS_CONFIRMATION"
                answer.citation_chunk_ids = []
            decisions.append((candidate, answer, hits))
        with pool.connection() as conn:
            _save_result(conn, job, clauses, classified, decisions, corpus, app.state.settings.gemini_model)
    except Exception as exc:
        code = (exc.code if isinstance(exc, APIError) else "LLM_UNAVAILABLE" if isinstance(exc, LLMUnavailable)
                else "ANALYSIS_FAILED")
        try:
            with pool.connection() as conn:
                conn.execute(
                    "UPDATE checkit.analysis_jobs SET status='FAILED',error_code=%s,recovery_action='RETRY',finished_at=now() "
                    "WHERE id=%s AND status IN ('QUEUED','RUNNING')", (code, job_id),
                )
        except Exception:
            pass


def recover_interrupted_jobs(pool):
    with pool.connection() as conn:
        conn.execute(
            "UPDATE checkit.analysis_jobs SET status='FAILED',error_code='ANALYSIS_INTERRUPTED',"
            "recovery_action='RETRY',finished_at=now() "
            "WHERE kind='ANALYSIS' AND status IN ('QUEUED','RUNNING')",
        )
