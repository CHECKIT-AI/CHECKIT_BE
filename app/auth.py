import logging
import re
from threading import BoundedSemaphore
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.access import (Actor, claim_contract, connection, cookie_names, guest,
                        member, require_csrf)
from app.api_docs import ENDPOINTS
from app.errors import APIError, unauthorized
from app.mail import ensure_mail_config, send_verification
from app.security import (hash_password, new_token, sign_csrf, token_hash,
                          valid_token, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])
password_slots = BoundedSemaphore(2)


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(
        max_length=254, title="이메일 주소",
        description="필수. 서비스 회원 이메일 문자열. 앞뒤 공백을 제거하고 소문자로 처리합니다. 최대 254자.",
        examples=[""],
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
            raise ValueError("이메일 형식을 확인하세요.")
        return value


class Credentials(EmailInput):
    password: SecretStr = Field(
        min_length=1, max_length=128, title="회원 비밀번호",
        description="필수. 가입 시 정한 서비스 회원용 비밀번호 문자열입니다. DB 접속 비밀번호가 아닙니다.",
        examples=[""],
    )


class SignupInput(Credentials):
    password: SecretStr = Field(
        min_length=1, max_length=128, title="새 회원 비밀번호",
        description="필수. 새로 정할 12~128자 문자열. 빈칸에 실제 사용할 비밀번호를 입력하세요.",
        examples=[""],
        # The existing endpoint checks the same minimum and returns PASSWORD_POLICY.
        json_schema_extra={"minLength": 12},
    )


class LoginInput(Credentials):
    claim_contract_id: UUID | None = Field(
        default=None, title="함께 저장할 비회원 계약서 ID",
        description="선택. 비회원 완료 결과를 로그인 계정으로 저장할 때만 실제 UUID 문자열 입력. 일반 로그인은 생략하거나 null.",
    )


class VerificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(
        min_length=43, max_length=43, title="이메일 인증 토큰",
        description="필수. 빈칸에 수신한 메일 링크의 #token= 뒤에 있는 실제 43자 문자열만 입력. CSRF 토큰이나 링크 전체가 아닙니다.",
        examples=[""],
    )


def throttle(request, category, email="", limit=10):
    limiter = request.app.state.auth_limiter
    ip = request.client.host if request.client else "unknown"
    limiter.check(f"{category}:ip:{ip}", limit=limit)
    if email:
        limiter.check(f"{category}:email:{token_hash(email)}", limit=limit)


def password_work(function, *args):
    if not password_slots.acquire(blocking=False):
        raise APIError(429, "RATE_LIMITED", "잠시 후 다시 시도해 주세요.", retryable=True)
    try:
        return function(*args)
    finally:
        password_slots.release()


def set_cookie(response, settings, name, value, max_age):
    response.set_cookie(cookie_names(settings)[name], value, max_age=max_age,
                        secure=settings.cookie_secure, httponly=True, samesite="lax", path="/")


def issue_csrf(request, response, *, member_token=None, guest_token=None):
    settings = request.app.state.settings
    names = cookie_names(settings)
    context = new_token()
    set_cookie(response, settings, "csrf", context, 600)
    return sign_csrf(settings.csrf_secret.get_secret_value(), context,
                     request.cookies.get(names["session"], "") if member_token is None else member_token,
                     request.cookies.get(names["guest"], "") if guest_token is None else guest_token)


def user_response(owner):
    return {"id": owner.id, "status": "ACTIVE", "provider": owner.provider}


@router.get("/csrf", **ENDPOINTS["csrf"])
def csrf(request: Request, response: Response):
    throttle(request, "csrf", limit=60)
    return {"csrf_token": issue_csrf(request, response)}


@router.post("/guest", dependencies=[Depends(require_csrf)], **ENDPOINTS["guest"])
def create_guest(request: Request, response: Response, conn=Depends(connection, scope="function")):
    throttle(request, "guest")
    settings = request.app.state.settings
    names = cookie_names(settings)
    if request.cookies.get(names["session"]):
        member(conn, request.cookies[names["session"]])
        raise APIError(409, "ALREADY_AUTHENTICATED", "이미 회원으로 로그인되어 있습니다.")
    old = request.cookies.get(names["guest"])
    try:
        visitor = guest(conn, old)
        return {"kind": "GUEST", "guest_session_id": visitor.id,
                "csrf_token": issue_csrf(request, response)}
    except APIError as exc:
        if exc.status != 401:
            raise
    raw = new_token()
    visitor = conn.execute(
        "INSERT INTO checkit.guest_sessions(token_hash) VALUES (%s) RETURNING id",
        (token_hash(raw),),
    ).fetchone()
    # Browser access can persist; every contract still has its own fixed 24-hour deadline.
    set_cookie(response, settings, "guest", raw, 30 * 86400)
    return {"kind": "GUEST", "guest_session_id": visitor["id"],
            "csrf_token": issue_csrf(request, response, guest_token=raw)}


@router.get("/me", **ENDPOINTS["me"])
def me(request: Request, conn=Depends(connection, scope="function")):
    owner = member(conn, request.cookies.get(cookie_names(request.app.state.settings)["session"]))
    return {"user": user_response(owner)}


@router.post("/login", dependencies=[Depends(require_csrf)], **ENDPOINTS["login"])
def login(request: Request, response: Response,
          payload: LoginInput = Body(description="필수 JSON 본문. 일반 로그인은 email·password만 입력하고 claim_contract_id는 생략하거나 null로 둡니다.",
                                     openapi_examples={
                                         "login": {"summary": "일반 이메일 로그인", "value": {
                                             "email": "", "password": ""}},
                                         "claim": {"summary": "로그인하며 비회원 완료 결과도 저장", "value": {
                                             "email": "", "password": "",
                                             "claim_contract_id": None}},
                                     }), conn=Depends(connection, scope="function")):
    throttle(request, "login", payload.email)
    row = conn.execute(
        "SELECT i.user_id, i.password_hash, u.status FROM checkit.auth_identities i "
        "JOIN checkit.users u ON u.id=i.user_id "
        "WHERE i.provider='EMAIL' AND i.provider_subject=%s", (payload.email,),
    ).fetchone()
    encoded = row["password_hash"] if row else request.app.state.dummy_password_hash
    correct = password_work(verify_password, payload.password.get_secret_value(), encoded)
    if not row or not correct:
        raise APIError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호를 확인하세요.")
    if row["status"] != "ACTIVE":
        raise APIError(403, "EMAIL_VERIFICATION_REQUIRED", "이메일 인증을 완료해 주세요.")
    owner = Actor("MEMBER", row["user_id"], "EMAIL")
    settings = request.app.state.settings
    names = cookie_names(settings)
    old = request.cookies.get(names["session"])
    if valid_token(old):
        conn.execute("UPDATE checkit.auth_sessions SET revoked_at=now() WHERE token_hash=%s", (token_hash(old),))
    raw = new_token()
    conn.execute(
        "INSERT INTO checkit.auth_sessions(user_id, token_hash, expires_at) "
        "VALUES (%s,%s,now() + %s * interval '1 second')",
        (owner.id, token_hash(raw), settings.session_seconds),
    )
    claim_result = None
    if payload.claim_contract_id:
        try:
            with conn.transaction():
                visitor = guest(conn, request.cookies.get(names["guest"]))
                claim_result = claim_contract(conn, owner, visitor, payload.claim_contract_id)
        except APIError:
            # Claim failure must not undo successful login.
            claim_result = {"saved": False, "code": "CONTRACT_NOT_FOUND"}
    set_cookie(response, settings, "session", raw, settings.session_seconds)
    return {"user": user_response(owner), "csrf_token": issue_csrf(request, response, member_token=raw),
            "claim_result": claim_result}


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)], **ENDPOINTS["logout"])
def logout(request: Request, response: Response, conn=Depends(connection, scope="function")):
    settings = request.app.state.settings
    names = cookie_names(settings)
    raw = request.cookies.get(names["session"])
    if valid_token(raw):
        conn.execute("UPDATE checkit.auth_sessions SET revoked_at=now() WHERE token_hash=%s", (token_hash(raw),))
    for name in ("session", "csrf"):
        response.delete_cookie(names[name], path="/", secure=settings.cookie_secure,
                               httponly=True, samesite="lax")


def deliver_mail(settings, email, token):
    try:
        send_verification(settings, email, token)
    except Exception:
        logging.getLogger("checkit.mail").warning("인증 메일 발송 실패. SMTP 설정 확인 및 재발송 필요.")


ACCEPTED = {"message": "가입 가능한 주소라면 인증 메일이 발송됩니다. 메일을 확인해 주세요."}


def schedule_verification(conn, request, tasks, email, encoded=None):
    settings = request.app.state.settings
    ensure_mail_config(settings)
    # Serialize same-email signup/resend without introducing a schema or account linking.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("signup:" + email,))
    identity = conn.execute(
        "SELECT i.id, i.user_id, u.status FROM checkit.auth_identities i "
        "JOIN checkit.users u ON u.id=i.user_id "
        "WHERE i.provider='EMAIL' AND i.provider_subject=%s FOR UPDATE OF i, u", (email,),
    ).fetchone()
    if identity is None and encoded is not None:
        user = conn.execute("INSERT INTO checkit.users DEFAULT VALUES RETURNING id").fetchone()
        identity = conn.execute(
            "INSERT INTO checkit.auth_identities(user_id,provider,provider_subject,email,password_hash) "
            "VALUES (%s,'EMAIL',%s,%s,%s) RETURNING id,user_id", (user["id"], email, email, encoded),
        ).fetchone()
        identity["status"] = "PENDING"
    if identity and identity["status"] == "PENDING":
        conn.execute(
            "UPDATE checkit.email_tokens SET revoked_at=now() "
            "WHERE user_id=%s AND used_at IS NULL AND revoked_at IS NULL", (identity["user_id"],),
        )
        raw = new_token()
        conn.execute(
            "INSERT INTO checkit.email_tokens(user_id,identity_id,target_email,token_hash,expires_at) "
            "VALUES (%s,%s,%s,%s,now()+interval '24 hours')",
            (identity["user_id"], identity["id"], email, token_hash(raw)),
        )
        # Function-scope DB dependency commits before the response/background task runs.
        # A failed commit prevents delivery of a token for a rolled-back account.
        tasks.add_task(deliver_mail, settings, email, raw)
    return ACCEPTED


@router.post("/signup", status_code=202, dependencies=[Depends(require_csrf)], **ENDPOINTS["signup"])
def signup(request: Request, tasks: BackgroundTasks,
           payload: SignupInput = Body(examples=[{"email": "", "password": ""}]),
           conn=Depends(connection, scope="function")):
    throttle(request, "signup", payload.email, limit=5)
    ensure_mail_config(request.app.state.settings)
    password = payload.password.get_secret_value()
    if len(password) < 12:
        raise APIError(422, "PASSWORD_POLICY", "비밀번호는 12~128자로 입력하세요.")
    encoded = password_work(hash_password, password)
    return schedule_verification(conn, request, tasks, payload.email, encoded)


@router.post("/email-verification/resend", status_code=202, dependencies=[Depends(require_csrf)], **ENDPOINTS["resend"])
def resend(request: Request, tasks: BackgroundTasks,
           payload: EmailInput = Body(examples=[{"email": ""}]),
           conn=Depends(connection, scope="function")):
    throttle(request, "signup", payload.email, limit=5)
    return schedule_verification(conn, request, tasks, payload.email)


@router.post("/email-verification/confirm", dependencies=[Depends(require_csrf)], **ENDPOINTS["confirm"])
def confirm(request: Request,
            payload: VerificationInput = Body(examples=[{"token": ""}]),
            conn=Depends(connection, scope="function")):
    throttle(request, "verify")
    raw = payload.token.get_secret_value()
    row = None
    if valid_token(raw):
        row = conn.execute(
            "UPDATE checkit.email_tokens SET used_at=clock_timestamp() "
            "WHERE token_hash=%s AND used_at IS NULL AND revoked_at IS NULL "
            "AND expires_at > clock_timestamp() RETURNING user_id,identity_id,target_email", (token_hash(raw),),
        ).fetchone()
    if not row:
        raise APIError(400, "INVALID_VERIFICATION_TOKEN", "인증 링크가 만료됐거나 사용할 수 없습니다.")
    conn.execute("UPDATE checkit.users SET status='ACTIVE',email_verified_at=now() WHERE id=%s", (row["user_id"],))
    conn.execute("UPDATE checkit.auth_identities SET verified_at=now() WHERE id=%s", (row["identity_id"],))
    return {"verified": True, "login_required": True}
