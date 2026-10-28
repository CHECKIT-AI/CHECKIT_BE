**CheckIt Backend 기술 지침**

**저장소 역할 및 기술 스택**

CheckIt의 FastAPI 백엔드로 회원·비회원 인증, 이메일·소셜 로그인, 계약서 기록 조회·귀속, PostgreSQL 접근 및 선택적 법령 RAG 검색 API를 담당한다.

- Python 3.13
- FastAPI, Pydantic Settings, psycopg 3 connection pool
- PostgreSQL/Supabase, pytest
- 의존성 버전 기준: requirements-lock.txt
- ASGI 진입점: app.main:app

**주요 디렉터리 및 진입점**

| 경로 | 역할 |
| --- | --- |
| README.md | 실행법 및 구현 범위 |
| app/main.py | 앱 생성, CORS, 예외 처리, 라우터 연결 |
| app/config.py, .env.example | 환경변수 |
| app/auth.py, app/oauth.py | 인증 및 OAuth |
| app/access.py, app/security.py | 접근 제어, CSRF, 토큰, 요청 제한 |
| app/contracts.py | 계약서 API |
| app/database.py | DB 연결 풀 및 역할 검증 |
| app/rag.py | Data 검색 서비스 어댑터 |
| database/ | 기준 스키마 및 권한 SQL |
| scripts/ | 관리자·DB 검증 도구 |
| tests/ | 단위·API·DB 통합 테스트 |

DB 관련 작업에서만 database/*.sql을, RAG 연동 작업에서만 Data의 공개 검색 인터페이스를 확인한다.

**실행 및 테스트**

모든 명령은 저장소 루트에서 실행한다.

**환경 준비**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
```

**서버 실행**

```bash
.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000
```

**기본 테스트**

```bash
.venv/bin/python -m pytest -q
```

**선택적 DB 통합 테스트**

```bash
CHECKIT_RUN_DB_TESTS=1 .venv/bin/python -m pytest \
  tests/test_auth_database.py tests/test_oauth_database.py -q
```

기본 테스트는 실제 DB 통합 테스트를 제외한다.

DB 통합 테스트는 강제 롤백 트랜잭션을 사용하지만 공유 DB에 연결되므로, 명시적 요청이나 사용자 승인 없이 실행하지 않는다.

**API 및 인증 계약**

주요 API 그룹:

- /api/auth
- /api/contracts
- /api/rag
- /health/live, /health/ready

필수 규칙:

- POST 요청의 기존 CSRF 및 Origin 검증을 우회하지 않는다.
- 쿠키 인증, credentials: include, 최신 CSRF 토큰 사용 계약을 유지한다.
- 인증·검증 오류에 비밀번호, 토큰, 이메일 인증값, DB 연결 정보 또는 내부 예외를 포함하지 않는다.
- 공개 계약서 응답에 내부 파일 경로나 저장 키를 노출하지 않는다.
- API 스키마나 오류 코드 변경 시 관련 Pydantic 모델, Swagger 설명 및 테스트를 갱신한다.
- 기존 프론트엔드 API 계약의 호환성을 확인한다.

**데이터베이스 계약**

기준 스키마는 checkit이며 14개 테이블로 구성된다.

**인증**

- users, auth_identities, auth_sessions, email_tokens, guest_sessions

**계약서·파일**

- contracts, file_generations, file_assets, document_pages

**분석**

- text_revisions, analysis_jobs, analysis_results, check_items, law_citations

DB 필수 규칙:

- 웹 애플리케이션에는 checkit_backend 역할을 사용하며 owner/admin 연결을 전달하지 않는다.
- RLS, PUBLIC 권한 제거, 소유권·만료·삭제 상태 검사를 약화하지 않는다.
- 기존 DB에 초기 스키마나 프로비저닝 SQL을 다시 실행하지 않는다.
- 스키마 변경 시 기준 SQL, 권한 SQL, 검증 SQL, 관련 쿼리와 테스트의 영향을 확인한다.
- 원본 파일은 DB에 직접 저장한다고 가정하지 않는다. DB에는 내부 저장 키와 메타데이터를 저장한다.

**Data/RAG 연동 계약**

RAG는 선택 기능이며 기본값은 비활성화다.

**의존성 설치**

```bash
.venv/bin/python -m pip install -r requirements-rag.txt
```

- requirements-rag.txt는 ../CheckIt_Data를 editable 설치한다.
- 기본 RAG 설정: employment_basic_v004, dense, cpu
- chunks, manifest, Chroma 인덱스는 Git 클론만으로 생성되지 않는다.

POST /api/rag/search는 다음 두 입력 형식 중 하나만 사용한다.

**일반 검색**

- query, top_k

**조항 검색**

- clause_id, labels, text, top_k

연동 규칙:

- 두 입력 형식을 혼합하거나 라벨을 중복 전달하지 않는다.
- RAG 계약 변경 시 CheckIt_Data/RAG/service.py와 양쪽 관련 테스트를 확인한다.
- 모델은 프로세스당 하나를 로딩한다.
- 동시 추론은 RAG_BUSY로 거부한다.
- RAG 활성 서버는 현재 단일 worker 전제를 유지한다.
