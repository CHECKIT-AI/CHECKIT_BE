# CheckIt Backend

CheckIt 계약서 분석 웹서비스의 FastAPI 백엔드입니다. 프론트엔드 팀원은 아래 순서대로 로컬 서버를 실행하고 Swagger에서 구현된 API를 테스트할 수 있습니다.

## 1. 처음 실행하기

### 준비할 것

- **Python 3.13**: 현재 설치·테스트한 버전입니다.
- GitHub에서 내려받은 프로젝트 코드(CHECKIT_BE)
- 백엔드 담당자에게 별도 전달받은 **개발 DB용 `CHECKIT_DATABASE_URL`**

**코드에는 DB 연결 정보가 포함되어 있지 않습니다.** 각자 로컬 `.env`에 연결 정보를 입력해야 합니다. 서버 실행에는 `checkit_backend` 계정의 PostgreSQL 연결 URI가 필요합니다. `checkit_reader`는 조회 전용 계정이므로 이 서버 실행용으로 사용할 수 없습니다.

DB 계정·테이블은 이미 준비되어 있습니다. 팀원은 초기 SQL이나 계정 생성 스크립트를 실행할 필요가 없습니다. 개발 DB 접속 정보가 없다면 백엔드 담당자에게 요청하세요.

### ① 코드 내려받기와 폴더 열기

GitHub의 **Code → Clone 또는 Download ZIP**으로 코드를 내려받습니다. VS Code 등에서 `CheckIt_BE` 폴더를 열고 터미널을 실행하세요.

이후 모든 명령은 **`app/`, `requirements-lock.txt`, `.env.example`이 있는 폴더**에서 실행합니다. 저장소가 상위 `CheckIt` 폴더를 포함한다면 먼저 이동합니다.

```bash
cd CheckIt_BE
```

이미 `CheckIt_BE`에서 터미널을 열었다면 위 명령은 생략합니다.

### ② 가상환경 생성과 패키지 설치

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
```

**Windows PowerShell**

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

가상환경을 별도로 활성화할 필요 없이 위 실행 파일 경로를 그대로 사용하면 됩니다. 패키지 설치는 처음 실행할 때, 또는 requirements 파일이 변경됐을 때 필요합니다.

### ③ 로컬 `.env` 설정

VS Code 파일 탐색기에서 **`.env.example`을 복사해 `.env`라는 이름으로 저장**합니다. 기존 `.env`가 있다면 덮어쓰지 않습니다.

`.env`를 열고 `CHECKIT_DATABASE_URL`의 빈 값에 전달받은 PostgreSQL 연결 URI를 입력하세요.

```dotenv
# 아래 설명 문구를 전달받은 실제 연결 URI로 교체합니다.
CHECKIT_DATABASE_URL="전달받은_PostgreSQL_연결_URI"
```

| 항목 | 프론트 팀원이 설정할 내용 |
| --- | --- |
| `CHECKIT_DATABASE_URL` | **필수.** 개발 DB의 `checkit_backend` 계정 연결 URI |
| `CHECKIT_ADMIN_DATABASE_URL` | 비워둡니다. 관리자용 계정 생성 설정 |
| `CHECKIT_BACKEND_PASSWORD` | 비워둡니다. 계정 생성용 설정으로, 서버는 URL 안의 비밀번호를 사용 |
| `CHECKIT_ENVIRONMENT` | 로컬에서는 `development` 유지 |
| `CHECKIT_COOKIE_SECURE` | 로컬 HTTP에서는 `false` 유지 |
| `CHECKIT_CSRF_SECRET` | 로컬에서는 비워도 실행 가능. 재시작 시 CSRF 재발급 필요 |
| SMTP 관련 항목 | 실제 회원가입 인증 메일을 테스트할 때만 별도 설정 |

연결 URI는 `postgresql://...` 형태입니다. `https://...supabase.co` 형태의 프로젝트 API URL이나 anon/service_role 키를 넣는 칸이 아닙니다. 전달받은 비밀번호가 URL 인코딩되어 있다면 임의로 다시 인코딩하지 않습니다.

`.env`는 현재 `.gitignore`에서 제외하며 **GitHub에 올리지 않습니다.** DB 연결 URI를 프론트의 `VITE_*`, `NEXT_PUBLIC_*` 등 브라우저에 전달되는 환경변수에도 넣지 마세요. DB 연결 정보는 FastAPI 서버 환경에서만 사용합니다.

### ④ 서버 실행

**macOS / Linux**

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`Uvicorn running on http://127.0.0.1:8000`이 나오면 아래 주소를 엽니다.

| 주소 | 용도 | 정상 결과 |
| --- | --- | --- |
| [Swagger](http://127.0.0.1:8000/docs) | API 설명 확인·직접 호출 | 한국어 API 목록 |
| [서버 상태](http://127.0.0.1:8000/health/live) | 서버가 응답하는지 확인 | `200`, `{"status":"ok"}` |
| [DB 연결 상태](http://127.0.0.1:8000/health/ready) | 전용 DB 계정·조회 가능 여부 확인 | `200`, `{"status":"ok"}` |

서버 터미널은 켜둡니다. 종료하려면 **Ctrl+C**를 누릅니다. 코드나 `.env`를 수정한 뒤에는 종료 후 다시 실행하세요. 다음에 켤 때는 같은 폴더에서 서버 실행 명령만 입력하면 됩니다.

> 기본 주소 `/`와 `/favicon.ico`의 404는 정상입니다. 기본 화면과 탭 아이콘은 아직 없습니다. `/docs`로 접속하세요.

## 2. Swagger에서 테스트하기

각 API를 펼쳐 **Try it out → 필요한 값 입력 → Execute** 순서로 사용합니다. 실제 결과는 **Server response**에서 확인합니다. 아래 Responses의 예시는 실제 저장된 데이터가 아닙니다.

### 먼저 해볼 수 있는 비회원 테스트

SMTP나 회원 계정 없이도 확인할 수 있는 흐름입니다.

| 순서 | API | 입력할 값 | 확인할 결과 |
| --- | --- | --- | --- |
| 1 | `GET /health/ready` | 없음 | `200`, DB 연결 성공 |
| 2 | `GET /api/auth/csrf` | 없음 | 응답의 `csrf_token` 복사 |
| 3 | `POST /api/auth/guest` | `X-CSRF-Token`에 2번 토큰 입력. 본문 없음 | 비회원 세션과 **새 csrf_token** 발급 |
| 4 | `GET /api/contracts` | `limit=20`, `offset=0` 또는 기본값 | `200`, 본인 비회원 기록 목록 |
| 5 | `GET /api/auth/me` | 없음 | 회원 로그인을 안 했으므로 `401`이 정상 |

업로드 API는 아직 없으므로 새 비회원의 `contracts`가 빈 배열이어도 정상입니다. 브라우저에서 쿠키 저장을 허용해야 합니다.

### 이메일 로그인 테스트

**가입 인증이 완료된 개발용 서비스 계정**이 필요합니다. 서비스 회원 이메일·비밀번호는 DB 계정 정보와 별개입니다.

1. `GET /api/auth/csrf`를 실행합니다.
2. `POST /api/auth/login`의 `X-CSRF-Token`에 복사한 토큰을 입력합니다.
3. Request body의 예시 선택에서 **일반 이메일 로그인**을 고르고 실제 서비스 회원 이메일·비밀번호를 입력합니다. `claim_contract_id`는 생략하거나 `null`로 둡니다.
4. 로그인 성공 후 `GET /api/auth/me`에서 회원 정보를 확인합니다.
5. 이후 POST에는 **로그인 응답의 새 csrf_token**을 사용합니다.
6. `POST /api/auth/logout`은 본문 없이 최신 CSRF 헤더만 넣어 실행합니다. `204`와 빈 본문이 정상입니다.

처음 회원가입부터 테스트하려면 **SMTP 설정과 이메일 인증 화면 연결**이 필요합니다. 설정이 없으면 signup/resend는 `503 EMAIL_NOT_CONFIGURED`를 반환합니다. 자동으로 활성화된 테스트 회원은 제공하지 않습니다. 설정 방법은 [인증 구현 안내](docs/auth-implementation.md)를 참고하세요.

### 공통 규칙

- **모든 POST:** `X-CSRF-Token` 필수. 문자열 값만 입력하고 큰따옴표는 제외합니다.
- **CSRF 유효 기간:** 10분. `/auth/csrf` 재실행, 비회원 세션 생성, 로그인 후에는 최신 토큰을 사용합니다.
- **쿠키:** 브라우저가 자동 저장·전송합니다. Swagger의 Authorize에 Bearer 토큰을 넣는 방식이 아닙니다.
- **UUID:** 실제 계약서 조회 응답에서 얻은 ID를 사용합니다. Swagger의 예시 UUID는 실제 기록이 아닙니다.
- **Origin:** Swagger에서는 브라우저가 자동 전달합니다. `localhost`와 `127.0.0.1`은 쿠키를 공유하지 않으므로 같은 주소를 유지하세요.
- **공유 개발 DB:** 각자 서버를 실행해도 같은 URL을 쓰면 같은 DB에 연결됩니다. Swagger의 POST는 실제 개발 DB에 계정·세션 등을 저장합니다. 개인별 복제 DB가 자동 생성되는 것은 아닙니다.

## 3. 프론트엔드 코드에서 연결하기

예를 들어 프론트를 `http://127.0.0.1:5173`, API를 `http://127.0.0.1:8000`에서 실행한다면 백엔드 `.env`의 허용 Origin에 프론트 주소를 추가하고 서버를 재시작합니다.

```dotenv
CHECKIT_ALLOWED_ORIGINS=["http://127.0.0.1:8000","http://localhost:8000","http://127.0.0.1:5173"]
```

실제 사용하는 주소·포트만 넣습니다. 프론트를 `localhost:5173`으로 열었다면 허용 목록도 해당 주소로 추가하고 API 호출 주소도 `localhost:8000`으로 통일하세요. `/docs` 같은 경로는 Origin 값에 넣지 않습니다.

쿠키 인증을 위해 요청마다 `credentials: "include"`를 사용합니다. 아래는 비회원 세션 생성 후 목록을 조회하는 예시입니다.

```javascript
const API_BASE = "http://127.0.0.1:8000/api";

const csrfResponse = await fetch(`${API_BASE}/auth/csrf`, {
  credentials: "include",
});
if (!csrfResponse.ok) throw new Error("CSRF 발급 실패");
let { csrf_token: csrfToken } = await csrfResponse.json();

const guestResponse = await fetch(`${API_BASE}/auth/guest`, {
  method: "POST",
  credentials: "include",
  headers: { "X-CSRF-Token": csrfToken },
});
if (!guestResponse.ok) throw new Error("비회원 세션 생성 실패");
csrfToken = (await guestResponse.json()).csrf_token; // 이후 POST에는 새 값 사용

const listResponse = await fetch(`${API_BASE}/contracts?limit=20&offset=0`, {
  credentials: "include",
});
if (!listResponse.ok) throw new Error("계약서 목록 조회 실패");
const records = await listResponse.json();
```

다른 API의 요청 필드와 응답 예시는 Swagger에서 확인합니다. 로그인 상태에서는 비회원 세션 생성 대신 로그인 흐름을 사용합니다.

## 4. 자주 만나는 오류

| 현상 | 확인할 내용 |
| --- | --- |
| `/` 또는 `/favicon.ico`가 404 | 기본 화면/아이콘 미구현. `/docs`로 접속 |
| `CHECKIT_DATABASE_URL` 설정 필요 | `CheckIt_BE/.env` 입력 여부와 현재 실행 폴더 확인 |
| `/health/ready`가 503 | URI·네트워크·전용 DB 계정 확인. reader/관리자 계정으로 실행하지 않음 |
| 로그인 전 `/auth/me`가 401 | 정상. 회원 로그인 세션이 필요한 API |
| `403 CSRF_FAILED` | 같은 브라우저에서 CSRF 재발급 → 최신 값 입력. 호스트·Origin·쿠키 확인 |
| `401 INVALID_CREDENTIALS` | 서비스 회원 이메일·비밀번호 확인. DB 비밀번호를 넣지 않음 |
| `403 EMAIL_VERIFICATION_REQUIRED` | 해당 회원의 이메일 가입 인증 필요 |
| `503 EMAIL_NOT_CONFIGURED` | 실제 가입/재발송을 위한 SMTP·인증 화면 설정 필요 |
| 계약서가 404 | 실제 UUID인지 확인. 타인 소유·만료·삭제 중 기록도 동일하게 404 |
| 422 | JSON 필수 필드·이메일·UUID·길이·정수 범위 확인. 허용되지 않은 필드는 제거 |
| 429 | 잠시 후 재시도. CSRF 발급·가입·로그인 등에 요청 제한 적용 |
| 프론트에서 CORS 오류 | 허용 Origin, 실제 프론트 주소·포트, 백엔드 재시작 여부 확인 |
| `Address already in use` | 기존 8000 포트 서버 종료 후 실행. 포트를 바꾸면 호출 주소·허용 Origin도 맞춤 |

문제 공유 시 오류 코드·메시지와 호출 경로를 전달하세요. 연결 URI·비밀번호·쿠키·인증 토큰은 제외합니다.

## 5. 현재 구현 범위

| 구분 | 상태 |
| --- | --- |
| FastAPI ↔ Supabase PostgreSQL 연결·상태 확인 | 완료 |
| 이메일 가입·인증·로그인·로그아웃 | 구현 완료. 실제 SMTP 발송은 설정·검증 필요 |
| 비회원 세션·CSRF 보호 | 완료 |
| 본인 계약서 목록·상세·저장 결과 조회 | 완료 |
| 비회원 완료 결과의 회원 귀속 | 완료 |
| 타인 소유·만료·삭제 중 기록 접근 차단 | 구현된 조회·귀속 API에 적용 |
| PDF·사진 업로드와 서버 파일 저장 | 후속 구현 |
| OCR·AI 패키지·Chroma RAG 연동 | 후속 구현 |
| 원본 다운로드·분석·취소·삭제 API | 후속 구현 |
| 비회원 데이터 24시간 자동 삭제 | 후속 구현 |
| 카카오·구글 로그인 | 후속 구현 |

회원 기록은 직접 삭제할 때까지 보관합니다. 비회원 기록은 최초 업로드 후 24시간으로 고정하며 조회·귀속 시 만료를 검사합니다. 실제 파일·DB 자동 정리는 아직 구현 전입니다.

## 6. 파일 구조

```text
CheckIt_BE/
├── README.md                    # 팀원용 실행·Swagger·연동 안내
├── .env.example                 # 공유 가능한 환경변수 양식
├── .env                         # 각자 로컬 설정. Git 제외
├── .gitignore
├── requirements.txt             # 서버 직접 의존성 범위
├── requirements-dev.txt         # 테스트 도구 의존성
├── requirements-lock.txt        # 검증한 패키지 고정 버전
├── app/
│   ├── main.py                  # 앱 생성, CORS, 오류, 헬스 체크
│   ├── api_docs.py              # Swagger 한국어 설명·응답 예시
│   ├── config.py                # 환경변수 로딩
│   ├── database.py              # 연결 풀·전용 DB 계정 검사
│   ├── auth.py                  # 이메일/비회원 인증 API·입력 모델
│   ├── access.py                # 세션·CSRF·소유권·만료·귀속 검사
│   ├── security.py              # 비밀번호 해시·토큰·요청 제한
│   ├── mail.py                  # SMTP 가입 인증 메일
│   ├── contracts.py             # 계약서 목록·상세·회원 귀속 API
│   └── errors.py                # 공통 API 오류
├── database/
│   ├── 001_initial_schema.sql   # 이미 적용된 테이블. 재실행 금지
│   ├── 002_backend_access.sql   # 이미 적용된 계정 권한·RLS 정책
│   ├── verify_schema.sql        # 롤백하는 개발용 DB 검증 SQL
│   └── README.md
├── scripts/
│   ├── provision_backend.py     # 관리자용 계정 생성. 팀원 실행 불필요
│   └── verify_database.py       # 전용 계정 DB 저장·조회 검증
├── tests/                      # 보안·API·선택적 실제 DB 통합 테스트
└── docs/                       # 상세 설정·인증 구현·서비스 설계 문서
```

`__init__.py`와 자동 생성되는 `.venv/`, `__pycache__/` 등은 위 트리에서 생략했습니다.

## 7. 내부 구성

```text
Swagger / 프론트엔드
        ↓ HTTP + 쿠키 + POST의 CSRF 헤더
FastAPI 라우터 (auth.py / contracts.py)
        ↓ 세션·소유권·만료 검사 (access.py)
PostgreSQL 연결 풀 (database.py)
        ↓ checkit_backend 전용 계정
Supabase PostgreSQL의 checkit 스키마
```

- 회원·비회원 세션 비밀값은 HttpOnly 쿠키로 전달하고 DB에는 해시만 저장합니다.
- Supabase Data API 대신 PostgreSQL 드라이버로 직접 연결합니다. 모든 테이블의 RLS를 유지하며 사용자별 소유권 검사는 FastAPI에서 수행합니다.
- 원본 PDF·사진은 향후 **서버 폴더에 저장하고 DB에는 저장 키만 기록**합니다. 현재 업로드는 구현 전입니다.
- Chroma 법령 검색과 AI 패키지는 후속 연결 대상입니다. 일반 로그인·조회 서버 실행에 별도 AI 패키지 설치는 아직 필요하지 않습니다.

## 8. 선택 사항: 테스트 실행

macOS / Linux 기준입니다. Windows에서는 실행 파일을 `.\.venv\Scripts\python.exe`로 바꿉니다.

```bash
.venv/bin/python -m pytest -q
```

기본 테스트는 실제 DB·메일 서버에 접속하지 않습니다. 현재 로컬 테스트 27개 통과, 실제 DB 테스트 4개는 기본 실행에서 건너뜁니다. Supabase 통합 테스트도 별도로 실행해 통과했으며 테스트 데이터는 롤백했습니다.

실제 DB 통합 테스트·검증 도구는 [인증 구현 안내](docs/auth-implementation.md), [백엔드 설정 안내](docs/backend-setup.md)를 참고하세요. 프론트 API 테스트를 시작할 때 실행할 필요는 없습니다.

## 9. 관련 문서

| 문서 | 내용 |
| --- | --- |
| [인증 구현 안내](docs/auth-implementation.md) | 현재 인증 API·쿠키·CSRF·SMTP 설정·DB 테스트 |
| [백엔드 설정 안내](docs/backend-setup.md) | 관리자용 계정 설정·연결·검증 |
| [프론트 API 설계](docs/frontend-api-guide.md) | 화면별 목표 API 흐름. 미구현 항목 포함 |
| [계약서 API 설계](docs/api-design.md) | 업로드·분석·취소·조회·삭제 목표 명세 |
| [로그인·계정 설계](docs/auth-api-design.md) | 인증 요구사항과 소셜 로그인 목표 명세 |
| [AI 패키지 인터페이스](docs/ai-interface-design.md) | 추출·분석 함수 입력/출력과 백엔드 책임 |
| [DB 속성 설명서](docs/database-dictionary.md) | 테이블·컬럼 설명 |

현재 동작 여부는 이 README와 Swagger, 인증 구현 안내를 기준으로 확인하세요. 기존 설계 문서에는 아직 구현하지 않은 목표 기능도 포함되어 있습니다.
