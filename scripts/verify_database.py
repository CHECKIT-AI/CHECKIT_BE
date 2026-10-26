"""Backend-role integration test. All synthetic writes are rolled back."""
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.config import Settings
from app.database import verify_backend_role


def main():
    url = Settings().database_url.get_secret_value()
    if not url:
        print("설정 필요: CHECKIT_DATABASE_URL (값은 출력하지 않음)")
        return 2
    try:
        with psycopg.connect(url, sslmode="require", connect_timeout=10,
                             row_factory=dict_row, prepare_threshold=None) as connection:
            verify_backend_role(connection)
            connection.execute("SET LOCAL statement_timeout = '15s'")
            test_sql = (Path(__file__).resolve().parents[1] / "database/verify_schema.sql").read_text()
            # Run the validation body in this connection's transaction; never commit fixtures.
            body = test_sql.split("BEGIN;", 1)[1].rsplit("ROLLBACK;", 1)[0]
            try:
                connection.execute(body)
            finally:
                connection.rollback()
        print("전용 계정 연결·저장·조회·보관 정책·파일 제약 검증 통과. 테스트 데이터 롤백 완료.")
        return 0
    except Exception:
        print("DB 검증 실패: 연결 설정·002 적용·기존 스키마 일치 여부를 확인하세요. 비밀값은 출력하지 않습니다.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
