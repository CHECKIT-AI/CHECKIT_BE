import psycopg

from scripts.provision_backend import safe_error


def test_auth_error_is_redacted():
    output = safe_error(psycopg.errors.InvalidPassword(
        'password authentication failed postgresql://secret-user:secret-password@secret-host/db'
    ), "연결")
    assert "28P01" in output
    assert "DB 인증 실패" in output
    assert "secret-" not in output


def test_permission_error_reports_stage_without_sql():
    output = safe_error(psycopg.errors.InsufficientPrivilege(
        "CREATE ROLE secret-user PASSWORD 'secret-password'"
    ), "계정 생성")
    assert "42501" in output
    assert "계정 생성" in output
    assert "secret-" not in output


def test_unknown_error_is_redacted():
    assert "secret-password" not in safe_error(RuntimeError("secret-password"), "연결")
