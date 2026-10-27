from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
import psycopg
from psycopg_pool import PoolTimeout

from app.access import Actor, claim_contract, cookie_names, guest, require_csrf
from app.auth import issue_csrf, set_cookie, throttle
from app.config import valid_oauth_url
from app.errors import APIError
from app.oauth_providers import authorization_url, provider_config
from app.security import new_token, token_hash, valid_token

router = APIRouter(prefix="/api/auth/oauth", tags=["auth"])
Provider = Literal["kakao", "google"]


class OAuthStartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_path: str = Field(default="/", max_length=256, description="선택. 로그인 후 프론트 내부 이동 경로.")
    claim_contract_id: UUID | None = Field(default=None, description="선택. 함께 저장할 비회원 완료 결과 UUID.")

    @field_validator("return_path")
    @classmethod
    def relative_path(cls, value):
        if (not value.startswith("/") or value.startswith("//") or "\\" in value or "%" in value
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)):
            raise ValueError("서비스 내부 상대 경로만 허용합니다.")
        return value


def completion_url(settings):
    configured = settings.oauth_frontend_complete_url
    if not configured and settings.environment == "development":
        return "/api/auth/oauth/complete"
    if not valid_oauth_url(configured, settings.environment):
        raise APIError(503, "OAUTH_NOT_CONFIGURED", "로그인 완료 화면 주소를 설정하세요.")
    return configured


def finish(settings, *, error=None, context=None, claim=None):
    parameters = {"oauth_status": "error" if error else "success"}
    if error:
        parameters["error_code"] = error
    if context:
        parameters["return_path"] = context.return_path
    if claim is not None:
        parameters["claim_status"] = "saved" if claim["saved"] else "failed"
    response = RedirectResponse(completion_url(settings) + "#" + urlencode(parameters), status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/{provider}/start", dependencies=[Depends(require_csrf)],
             summary="카카오·구글 로그인 시작",
             description="provider: kakao 또는 google. CSRF 헤더 필수. 응답의 authorization_url로 브라우저를 이동하세요.",
             responses={200: {"description": "인가 화면 URL", "content": {"application/json": {
                 "example": {"authorization_url": "https://제공자/인가주소"}}}},
                        403: {"description": "CSRF 검증 실패"}, 429: {"description": "요청 제한"},
                        503: {"description": "키·시크릿·콜백·완료 화면 설정 필요"}})
def start(provider: Provider, request: Request,
          payload: OAuthStartInput = Body(examples=[{"return_path": "/", "claim_contract_id": None}])):
    throttle(request, "oauth-start")
    settings = request.app.state.settings
    provider_config(settings, provider)
    completion_url(settings)
    names = cookie_names(settings)
    browser = new_token()
    state, context = request.app.state.oauth_states.create(
        provider, browser, request.cookies.get(names["session"], ""),
        request.cookies.get(names["guest"], ""), payload.return_path, payload.claim_contract_id,
    )
    from fastapi.responses import JSONResponse
    response = JSONResponse({"authorization_url": authorization_url(settings, provider, state, context)})
    set_cookie(response, settings, "oauth", browser, 600)
    return response


def social_member(conn, provider, identity):
    # Same email across providers never links accounts. Serialize first signup by provider subject.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                 (f"social:{provider}:{identity.subject}",))
    row = conn.execute(
        "SELECT u.id,u.status FROM checkit.auth_identities i JOIN checkit.users u ON u.id=i.user_id "
        "WHERE i.provider=%s AND i.provider_subject=%s", (provider.upper(), identity.subject),
    ).fetchone()
    if row:
        if row["status"] != "ACTIVE":
            raise APIError(403, "ACCOUNT_INACTIVE", "로그인할 수 없는 계정입니다.")
        return Actor("MEMBER", row["id"], provider.upper())
    email = identity.email.strip().lower() if identity.email else None
    row = conn.execute("INSERT INTO checkit.users(status,email_verified_at) "
                       "VALUES ('ACTIVE',CASE WHEN %s THEN now() ELSE NULL END) RETURNING id", (bool(email),)).fetchone()
    conn.execute(
        "INSERT INTO checkit.auth_identities(user_id,provider,provider_subject,email,verified_at) "
        "VALUES (%s,%s,%s,%s,now())", (row["id"], provider.upper(), identity.subject, email),
    )
    return Actor("MEMBER", row["id"], provider.upper())


def create_social_session(request, provider, identity, context):
    settings = request.app.state.settings
    names = cookie_names(settings)
    claim = None
    with request.app.state.database_pool.connection() as conn:
        owner = social_member(conn, provider, identity)
        raw = new_token()
        old = request.cookies.get(names["session"])
        if valid_token(old):
            conn.execute("UPDATE checkit.auth_sessions SET revoked_at=now() WHERE token_hash=%s", (token_hash(old),))
        conn.execute("INSERT INTO checkit.auth_sessions(user_id,token_hash,expires_at) "
                     "VALUES (%s,%s,now()+%s*interval '1 second')",
                     (owner.id, token_hash(raw), settings.session_seconds))
        if context.claim_contract_id:
            try:
                with conn.transaction():
                    visitor = guest(conn, request.cookies.get(names["guest"]))
                    claim = claim_contract(conn, owner, visitor, context.claim_contract_id)
            except APIError:
                claim = {"saved": False}
    # Pool commits before success cookies are constructed.
    response = finish(settings, context=context, claim=claim)
    set_cookie(response, settings, "session", raw, settings.session_seconds)
    issue_csrf(request, response, member_token=raw)
    return response


@router.get("/{provider}/callback", status_code=303, response_class=RedirectResponse, summary="카카오·구글 로그인 콜백",
            description="제공자가 code·state 또는 오류를 전달하는 주소. 직접 호출하지 않습니다. 처리 후 완료 화면으로 303 이동합니다.",
            responses={303: {"description": "완료 화면으로 이동. fragment의 oauth_status 및 error_code 확인"},
                       503: {"description": "로그인 완료 화면 설정 필요"}},
            openapi_extra={"parameters": [
                {"name": name, "in": "query", "required": False, "schema": {"type": "string"},
                 "description": description}
                for name, description in (("code", "제공자가 발급한 인가 코드"),
                                          ("state", "로그인 시작 요청의 일회성 state"),
                                          ("error", "제공자가 반환한 오류 코드"))]})
def callback(provider: Provider, request: Request):
    settings = request.app.state.settings
    completion_url(settings)
    names = cookie_names(settings)
    consumed = False
    try:
        # Query string is removed from the ASGI scope before Uvicorn access logging.
        query = parse_qs(request.scope.get("oauth_callback_query", b"").decode("utf-8"),
                         keep_blank_values=True, max_num_fields=12)
        if any(len(values) != 1 for values in query.values()):
            raise APIError(400, "INVALID_OAUTH_STATE", "로그인 요청을 확인할 수 없습니다.")
        state = query.get("state", [""])[0]
        context = request.app.state.oauth_states.consume(
            state, provider, request.cookies.get(names["oauth"], ""),
            request.cookies.get(names["session"], ""), request.cookies.get(names["guest"], ""),
        )
        consumed = True
        if "error" in query:
            raise APIError(400, "OAUTH_DENIED", "소셜 로그인이 취소됐거나 거절됐습니다.")
        code = query.get("code", [""])[0]
        if not 1 <= len(code) <= 4096:
            raise APIError(400, "OAUTH_CODE_INVALID", "소셜 로그인 인가 코드가 없습니다.")
        identity = request.app.state.oauth_client.exchange(settings, provider, code, context)
        response = create_social_session(request, provider, identity, context)
    except APIError as exc:
        response = finish(settings, error=exc.code)
    except (ValueError, UnicodeError):
        response = finish(settings, error="INVALID_OAUTH_STATE")
    except (psycopg.Error, PoolTimeout):
        response = finish(settings, error="DATABASE_UNAVAILABLE")
    if consumed:
        response.delete_cookie(names["oauth"], path="/", secure=settings.cookie_secure,
                               httponly=True, samesite="lax")
    return response


class OAuthCallbackRedactionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") in {
            "/api/auth/oauth/kakao/callback", "/api/auth/oauth/google/callback"
        }:
            scope["oauth_callback_query"] = scope.get("query_string", b"")
            scope["query_string"] = b""
        await self.app(scope, receive, send)


TEST_HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>CheckIt 로그인 테스트</title>
<style>body{font:16px system-ui;max-width:720px;margin:48px auto;padding:16px}button{padding:12px;margin:4px}pre{white-space:pre-wrap;background:#f3f4f6;padding:16px}</style>
<h1>CheckIt 소셜 로그인 테스트</h1><p>localhost:8000에서 실행하세요. 로그인 후 회원 정보가 표시됩니다.</p>
<button data-provider="kakao">카카오 로그인</button><button data-provider="google">구글 로그인</button>
<button id="me">내 정보 확인</button><button id="logout">로그아웃</button><pre id="result"></pre>
<script>
const out=document.getElementById('result');
async function csrf(){const r=await fetch('/api/auth/csrf',{credentials:'include'});const d=await r.json();if(!r.ok)throw Error(d.error?.message||'CSRF 발급 실패');return d.csrf_token;}
async function me(){const r=await fetch('/api/auth/me',{credentials:'include'});out.textContent=JSON.stringify(await r.json(),null,2);}
document.querySelectorAll('[data-provider]').forEach(b=>b.onclick=async()=>{try{
const token=await csrf();const r=await fetch('/api/auth/oauth/'+b.dataset.provider+'/start',{
method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-CSRF-Token':token},
body:JSON.stringify({return_path:'/',claim_contract_id:null})});const d=await r.json();
if(!r.ok)throw Error(d.error?.message||'로그인 시작 실패');window.location.assign(d.authorization_url);
}catch(e){out.textContent=e.message;}});
document.getElementById('me').onclick=()=>me().catch(()=>out.textContent='연결 실패');
document.getElementById('logout').onclick=async()=>{try{const token=await csrf();const r=await fetch('/api/auth/logout',{
method:'POST',credentials:'include',headers:{'X-CSRF-Token':token}});if(!r.ok)throw Error('로그아웃 실패');out.textContent='로그아웃 완료';}catch(e){out.textContent=e.message;}};
const status=new URLSearchParams(location.hash.slice(1));history.replaceState(null,'',location.pathname);
if(status.get('oauth_status')==='error'){out.textContent='로그인 실패: '+(status.get('error_code')||'UNKNOWN');}
else{me().catch(()=>out.textContent='연결 실패');}
</script></html>"""


@router.get("/test", include_in_schema=False)
@router.get("/complete", include_in_schema=False)
def test_page(request: Request):
    if request.app.state.settings.environment != "development":
        raise APIError(404, "NOT_FOUND", "페이지를 찾을 수 없습니다.")
    return HTMLResponse(TEST_HTML, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                           "X-Content-Type-Options": "nosniff"})
