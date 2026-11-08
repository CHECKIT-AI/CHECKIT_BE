from dataclasses import dataclass
from uuid import UUID

from fastapi import Header, Request

from app.errors import APIError, not_found, unauthorized
from app.security import valid_token, token_hash, verify_csrf


def cookie_names(settings):
    prefix = "__Host-" if settings.cookie_secure else ""
    return {name: f"{prefix}checkit_{name}" for name in ("session", "csrf", "oauth")}


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


def current_actor(request: Request, conn) -> Actor:
    names = cookie_names(request.app.state.settings)
    return member(conn, request.cookies.get(names["session"]))


def owner_predicate(actor: Actor):
    return "user_id=%s", actor.id


def require_contract(conn, actor: Actor, contract_id: UUID, *, lock=False):
    predicate, owner_id = owner_predicate(actor)
    row = conn.execute(
        "SELECT id, contract_type, input_kind, current_file_generation_id, "
        "first_uploaded_at, created_at, updated_at FROM checkit.contracts "
        f"WHERE id=%s AND deletion_state='AVAILABLE' AND ({predicate})"
        + (" FOR UPDATE" if lock else ""), (contract_id, owner_id),
    ).fetchone()
    if not row:
        raise not_found()
    return row
