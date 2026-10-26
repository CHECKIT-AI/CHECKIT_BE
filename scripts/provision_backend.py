"""Explicit owner operation: python -m scripts.provision_backend."""
from pathlib import Path

import psycopg
from psycopg import sql

from app.config import Settings


def safe_error(exc, stage):
    """Return only fixed messages; never print driver messages or SQL text."""
    state = getattr(exc, "sqlstate", None)
    message = str(exc).lower()
    if state == "28P01" or "password authentication failed" in message:
        reason = "DB 인증 실패: DB 소유자 비밀번호와 URI 인코딩을 확인하세요. Supabase 웹 로그인 비밀번호와 다릅니다."
    elif state == "42501":
        reason = "권한 부족: 관리자 URI가 DB 소유자 계정인지 확인하세요."
    elif state == "42710":
        reason = "계정 또는 정책이 이미 존재합니다. 기존 권한 검토가 필요합니다."
    elif state == "42P01" or state == "3F000":
        reason = "필요한 스키마 또는 테이블이 없습니다. 올바른 프로젝트인지 확인하세요. 초기 SQL은 재실행하지 마세요."
    elif "translate host name" in message or "name or service not known" in message or "nodename nor servname" in message:
        reason = "서버 주소를 해석하지 못했습니다. Connect의 호스트와 네트워크·DNS를 확인하세요."
    elif "network is unreachable" in message or "no route to host" in message:
        reason = "DB 서버로 접근할 수 없습니다. 직접 연결의 IPv6 접근성과 Session pooler 연결을 확인하세요."
    elif "timeout" in message or "timed out" in message:
        reason = "연결 시간이 초과됐습니다. 서버 주소·포트·네트워크 접근을 확인하세요."
    elif "tenant or user not found" in message:
        reason = "Pooler 계정 식별 실패: Connect의 관리자 사용자명과 프로젝트 접미사를 확인하세요."
    elif isinstance(exc, (psycopg.ProgrammingError, ValueError)) and stage == "연결":
        reason = "연결 문자열 형식을 확인하세요. PostgreSQL URI와 비밀번호 URL 인코딩이 필요합니다."
    elif stage == "권한·RLS 설정":
        reason = "권한·정책 설정에 실패했습니다. 테이블 14개의 존재·RLS 활성화·소유권을 확인하세요."
    else:
        reason = "원인을 확정하지 못했습니다. 표시된 단계와 오류 코드로 추가 확인이 필요합니다."
    # SQLSTATE is exactly five ASCII alphanumeric characters, never arbitrary error data.
    code = state if isinstance(state, str) and len(state) == 5 and state.isascii() and state.isalnum() else "없음"
    return f"설정 실패 단계: {stage} / SQLSTATE: {code}\n{reason}\n원시 오류·연결 문자열·비밀번호는 출력하지 않습니다."


def main():
    settings = Settings()
    admin = settings.admin_database_url.get_secret_value()
    password = settings.backend_password.get_secret_value()
    if not admin or not password:
        print("설정 필요: CHECKIT_ADMIN_DATABASE_URL, CHECKIT_BACKEND_PASSWORD (값은 출력하지 않음)")
        return 2
    stage = "연결"
    try:
        with psycopg.connect(admin, sslmode="require", connect_timeout=10) as conn:
            stage = "기존 계정 확인"
            exists = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = 'checkit_backend'"
            ).fetchone()
            if exists:
                # Existing passwords/privileges are not silently changed.
                print("checkit_backend 계정이 이미 있습니다. 기존 권한을 검토한 뒤 진행하세요.")
                return 2
            stage = "계정 생성"
            conn.execute(sql.SQL(
                "CREATE ROLE checkit_backend LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOBYPASSRLS PASSWORD {}"
            ).format(sql.Literal(password)))
            stage = "권한·RLS 설정"
            conn.execute((Path(__file__).resolve().parents[1] / "database/002_backend_access.sql").read_text())
            stage = "트랜잭션 확정"
        print("백엔드 계정·14개 테이블 권한·전용 RLS 정책 설정 완료")
        return 0
    except Exception as exc:
        print(safe_error(exc, stage))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
