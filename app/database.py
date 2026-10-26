from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import Settings


def create_pool(settings: Settings) -> ConnectionPool:
    url = settings.database_url.get_secret_value()
    if not url:
        raise RuntimeError("CHECKIT_DATABASE_URL 환경변수를 설정하세요.")
    return ConnectionPool(
        conninfo=url,
        min_size=0,
        max_size=5,
        timeout=5,
        open=False,
        configure=configure_backend_connection,
        kwargs={
            "sslmode": "require",
            "connect_timeout": 5,
            "prepare_threshold": None,
            "row_factory": dict_row,
            "options": "-c statement_timeout=10000 -c timezone=UTC",
        },
    )


def verify_backend_role(connection) -> None:
    role = connection.execute(
        "SELECT current_user AS name, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    if not role or role["name"] != "checkit_backend" or any(
        role[key] for key in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb")
    ):
        raise RuntimeError("백엔드 전용 DB 계정과 권한을 확인하세요.")


def configure_backend_connection(connection) -> None:
    # Refuse owner/elevated credentials before any pooled connection serves an API.
    verify_backend_role(connection)
    connection.commit()
