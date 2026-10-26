# 백엔드 연결 구현 · 2026-10-26

DB 연결 기반과 내부 검증 도구에 이어 인증·조회·귀속 API를 구현했습니다. 현재 범위와 SMTP/CSRF 설정은 [인증 구현 안내](auth-implementation.md)를 참고하세요. OCR·AI·파일 업로드·자동 삭제는 아직 구현 전입니다. `001_initial_schema.sql`은 재실행하지 않습니다. 기존 문서의 ‘DB 미생성’ 표현은 과거 설계 시점의 기록입니다.

## 1. 실행 환경

프로젝트 루트 `CheckIt_BE`에서 실행합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
# .env가 없다면 .env.example을 복사합니다. 기존 파일은 덮어쓰지 않습니다.
cp -n .env.example .env
chmod 600 .env
```

`.env`는 Git 제외 대상입니다. 값을 채팅이나 터미널 명령 인자에 넣지 말고 로컬 편집기 또는 비밀 관리 도구에서 입력합니다. 실행 명령·스크린샷에도 연결 문자열을 노출하지 않습니다.

`requirements-lock.txt`는 이번 로컬 테스트 환경의 고정 버전이며, 개발 의존성을 포함합니다. 직접 의존성 범위는 requirements.txt와 requirements-dev.txt에서 관리합니다.

## 2. 전용 계정 생성

Supabase의 Connect에서 직접 연결 또는 session pooler의 PostgreSQL 연결 정보를 확인합니다. 직접 연결 주소의 네트워크 접근성이 없으면 session pooler를 사용합니다. Data API URL·anon key·service_role key는 PostgreSQL 접속 정보가 아닙니다.

로컬 `.env`에 `CHECKIT_ADMIN_DATABASE_URL`(DB 소유자 URI), `CHECKIT_BACKEND_PASSWORD`(새 전용 비밀번호)를 입력합니다. URI 비밀번호의 예약 문자는 URL 인코딩해야 합니다. SSL을 강제하며 배포 시 신뢰할 CA와 호스트 검증도 구성합니다.

```bash
.venv/bin/python -m scripts.provision_backend
```

이 명령만 소유자 계정을 사용합니다. 새 `checkit_backend` 역할 생성과 `002_backend_access.sql` 적용은 한 트랜잭션입니다. 기존 역할이 있으면 변경 없이 중단합니다. 초기 스키마나 `checkit_reader`는 변경하지 않습니다. 기존 역할 검토 없이 비밀번호를 교체하지 않습니다.

백엔드 역할은 checkit 14개 테이블의 SELECT/INSERT/UPDATE/DELETE만 사용하고, RLS는 유지합니다. 역할 전용 정책이 모든 행을 허용하므로 **사용자별 격리는 FastAPI가 인증·소유권·만료 조건으로 강제해야 합니다.** UUID나 클라이언트 user_id만으로 조회하는 공개 API를 만들면 안 됩니다. 이 단계는 공개 데이터 API를 제공하지 않습니다. 새 테이블에 권한이 자동 부여되지 않습니다.

## 3. 전용 연결과 검증

`CHECKIT_DATABASE_URL`을 전용 계정 URI로 입력합니다. 직접 연결 사용자명은 `checkit_backend`, pooler는 공급자가 요구하는 프로젝트 접미사가 필요할 수 있습니다. 웹서버 환경에는 소유자 URI·계정 생성 비밀번호를 전달하지 말고 로컬 `.env`에서도 프로비저닝 후 제거합니다.

```bash
.venv/bin/python -m scripts.verify_database
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`GET /health/live`: 프로세스 응답. `GET /health/ready`: 전용 역할 확인 및 contracts SELECT 실행. DB 상세 오류는 응답하지 않습니다. 준비 상태 실패는 HTTP 503입니다. 연결 풀은 최대 5개이며 prepared statement를 비활성화했습니다.

검증 스크립트는 기존 `verify_schema.sql`의 검증 본문을 전용 계정으로 실행하고 테스트 데이터를 항상 롤백합니다. 회원/비회원·파일 메타데이터 저장·조회, 24시간 만료, 회원 귀속 시 만료 해제, PDF 중복·형식 혼합 거부를 확인합니다. 실제 원본 파일이나 분석 결과 저장 검증을 대신하지 않습니다. `checkit_reader`의 실제 로그인 검증도 별도입니다.

```bash
.venv/bin/python -m pytest -q
```

## 후속 구현

사용자 실행으로 전용 계정 생성·DB 저장/조회 검증·FastAPI health/ready 200을 확인했습니다. 새 인증 코드의 로컬 테스트와 실제 DB 검증 범위는 인증 구현 안내를 참고하세요. 설치된 Starlette의 httpx TestClient 지원 중단 예정 경고가 있습니다.

서버 파일 저장 및 업로드 검사 → AI 패키지 어댑터 → 분석·원본 다운로드·삭제 API 순서로 연결합니다. 파일 저장은 서버 폴더와 DB 저장 키 방식, 회원은 직접 삭제 전까지 보관, 비회원은 최초 업로드 후 24시간 정책을 유지합니다. 조회·귀속 API의 만료 차단은 구현했고 실제 자동 삭제 작업은 후속 구현입니다. 법령 RAG용 Chroma는 사용자 계약서 DB와 분리합니다.
