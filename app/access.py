from dataclasses import dataclass
from uuid import UUID

from fastapi import Header, Request

from app.errors import APIError, not_found, unauthorized
from app.security import valid_token, token_hash, verify_csrf


def cookie_names(settings):
    prefix = "__Host-" if settings.cookie_secure else ""
    return {name: f"{prefix}checkit_{name}" for name in ("session", "guest", "csrf", "oauth")}


def connection(request: Request):
    with request.app.state.database_pool.connection() as conn:
        yield conn


def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(
        default=None, alias="X-CSRF-Token",
        description="필수. /api/auth/csrf 응답의 최신 csrf_token. 10분 유효.",
    ),
):
    settings = request.app.state.settings
    names = cookie_names(settings)
    if request.headers.get("origin") not in settings.allowed_origins:
        raise APIError(403, "CSRF_FAILED", "요청 출처를 확인할 수 없습니다.")
    if not verify_csrf(settings.csrf_secret.get_secret_value(),
                       request.cookies.get(names["csrf"], ""),
                       request.cookies.get(names["session"], ""),
                       request.cookies.get(names["guest"], ""),
                       x_csrf_token or ""):
        raise APIError(403, "CSRF_FAILED", "보안 토큰을 새로 발급받고 다시 시도해 주세요.")


@dataclass(frozen=True)
class Actor:
    kind: str
    id: UUID
    provider: str | None = None


def member(conn, raw: str | None) -> Actor:
    if not valid_token(raw):
        raise unauthorized()
    row = conn.execute(
        "SELECT u.id, i.provider FROM checkit.auth_sessions s "
        "JOIN checkit.users u ON u.id=s.user_id "
        "JOIN checkit.auth_identities i ON i.user_id=u.id "
        "WHERE s.token_hash=%s AND s.revoked_at IS NULL "
        "AND s.expires_at > clock_timestamp() AND u.status='ACTIVE'",
        (token_hash(raw),),
    ).fetchone()
    if not row:
        raise unauthorized()
    return Actor("MEMBER", row["id"], row["provider"])


def guest(conn, raw: str | None) -> Actor:
    if not valid_token(raw):
        raise unauthorized()
    row = conn.execute(
        "SELECT id FROM checkit.guest_sessions WHERE token_hash=%s AND revoked_at IS NULL",
        (token_hash(raw),),
    ).fetchone()
    if not row:
        raise unauthorized()
    return Actor("GUEST", row["id"])


def current_actor(request: Request, conn) -> Actor:
    names = cookie_names(request.app.state.settings)
    # An invalid member cookie never falls back to another identity silently.
    if names["session"] in request.cookies:
        return member(conn, request.cookies[names["session"]])
    return guest(conn, request.cookies.get(names["guest"]))


def owner_predicate(actor: Actor):
    if actor.kind == "MEMBER":
        return "user_id=%s", actor.id
    return "guest_session_id=%s AND expires_at > clock_timestamp()", actor.id


def require_contract(conn, actor: Actor, contract_id: UUID, *, lock=False):
    predicate, owner_id = owner_predicate(actor)
    row = conn.execute(
        "SELECT id, contract_type, input_kind, current_file_generation_id, "
        "first_uploaded_at, expires_at, created_at, updated_at FROM checkit.contracts "
        f"WHERE id=%s AND deletion_state='AVAILABLE' AND ({predicate})"
        + (" FOR UPDATE" if lock else ""), (contract_id, owner_id),
    ).fetchone()
    if not row:
        raise not_found()
    return row


def claim_contract(conn, owner: Actor, visitor: Actor | None, contract_id: UUID):
    # Lock, then recheck expiry using wall-clock time, including time spent waiting.
    row = conn.execute(
        "SELECT user_id, guest_session_id, deletion_state, expires_at "
        "FROM checkit.contracts WHERE id=%s FOR UPDATE", (contract_id,),
    ).fetchone()
    if not row or row["deletion_state"] != "AVAILABLE":
        raise not_found()
    if row["user_id"] == owner.id:
        return {"contract_id": contract_id, "saved": True}
    if visitor is None or row["user_id"] is not None or row["guest_session_id"] != visitor.id:
        raise not_found()
    # Do not allow claim of arbitrary unfinished uploads: the UI saves completed results.
    result = conn.execute(
        "UPDATE checkit.contracts SET user_id=%s, guest_session_id=NULL "
        "WHERE id=%s AND deletion_state='AVAILABLE' AND expires_at > clock_timestamp() "
        "AND EXISTS (SELECT 1 FROM checkit.analysis_results WHERE contract_id=%s) "
        "RETURNING id", (owner.id, contract_id, contract_id),
    ).fetchone()
    if not result:
        raise not_found()
    return {"contract_id": contract_id, "saved": True}
