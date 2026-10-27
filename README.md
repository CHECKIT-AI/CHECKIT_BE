# CheckIt Backend

FastAPI + Supabase PostgreSQL 기반 계약서 분석 백엔드입니다.

## 실행

Python 3.13을 설치하고, `app/`과 `requirements-lock.txt`가 있는 `CheckIt_BE` 폴더에서 실행합니다.

### 1. 패키지 설치

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
```

### 2. 환경변수 설정

`.env.example`을 복사해 `.env`를 만들고, 백엔드 담당자에게 전달받은 값을 입력합니다.

```dotenv
CHECKIT_DATABASE_URL="전달받은_PostgreSQL_연결_URI"
```

- 서버용 `checkit_backend` 계정 URI가 필요합니다. 조회 전용 `checkit_reader`는 사용할 수 없습니다.
- `CHECKIT_ADMIN_DATABASE_URL`, `CHECKIT_BACKEND_PASSWORD`는 비워둡니다.
- `.env`는 GitHub나 프론트 코드에 올리지 않습니다.
- DB는 이미 준비되어 있습니다. 초기 SQL과 계정 생성 스크립트는 실행하지 마세요.

### 3. 서버 실행

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

[Swagger 열기](http://127.0.0.1:8000/docs) · [DB 연결 확인](http://127.0.0.1:8000/health/ready)

DB 확인에서 `200`, `{"status":"ok"}`가 나오면 정상입니다. `/`의 404는 기본 화면이 없어서 나옵니다.
종료는 `Ctrl+C`. 코드·환경변수 변경 후 서버를 재시작합니다.

<details>
<summary>Windows PowerShell 명령</summary>

가상환경 생성·설치 후 위 안내대로 `.env`를 설정하고 서버를 실행합니다.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

</details>

## Swagger 테스트

각 API에서 **Try it out → 입력 → Execute**를 누릅니다.

1. `GET /api/auth/csrf` → `csrf_token` 복사
2. `POST /api/auth/guest` → `X-CSRF-Token`에 붙여넣기, 본문 없음
3. `GET /api/contracts` → 비회원 기록 목록 확인. 빈 배열도 정상

모든 POST에는 CSRF 헤더가 필요합니다. 토큰은 10분 유효하며, 재발급·비회원 생성·로그인 후에는 최신 값을 사용합니다. 쿠키는 브라우저가 자동 전달합니다.

이메일 로그인은 인증 완료된 서비스 회원 계정이 필요합니다. 신규 가입 메일 발송에는 SMTP 설정이 필요하며, 미설정 시 `503 EMAIL_NOT_CONFIGURED`가 나옵니다.

카카오·구글 키를 `.env`에 입력했다면 [소셜 로그인 테스트](http://localhost:8000/api/auth/oauth/test)에서 버튼으로 로그인할 수 있습니다. 프론트 완료 주소가 비어 있으면 개발용 완료 화면으로 돌아옵니다. **localhost로 접속하고 단일 서버 프로세스**로 테스트하세요. 자세한 내용은 [소셜 로그인 안내](docs/social-login-setup.md)에 있습니다.

## 로컬 Chroma 검색 연결

`CheckIt_BE`와 `CheckIt_Data`를 같은 상위 폴더에 준비합니다. 검색 로직·청크·인덱스는 Data에 두고 백엔드 프로세스 안에서 호출합니다. 별도 Data 서버는 필요 없습니다.

백엔드 폴더에서 추가 패키지를 설치합니다. 모델 의존성 설치로 시간이 걸릴 수 있습니다.

```bash
.venv/bin/python -m pip install -r requirements-rag.txt
```

백엔드 `.env`에 추가하고 서버를 재시작합니다.

```dotenv
CHECKIT_RAG_ENABLED=true
CHECKIT_RAG_CORPUS=labor_standards_v001
CHECKIT_RAG_DEVICE=cpu
```

Data의 기존 `data/rag/processed/<corpus>/chunks.jsonl`과 `storage/rag/<corpus>/index_manifest.json`, `chroma/`가 필요합니다. Git 클론만으로는 이 데이터가 생기지 않습니다. 준비 방법은 Data README를 참고하세요. Data는 **editable 설치**로 연결하므로 설치 후 해당 폴더를 옮기지 않습니다.

Swagger에서 CSRF 발급 → 비회원 세션 생성 → 응답의 최신 CSRF 토큰으로 `POST /api/rag/search`를 호출합니다. 회원 로그인 상태에서도 사용할 수 있습니다.

```json
{"query":"퇴사한 뒤 남은 월급은 언제까지 받아야 하나요?","top_k":5}
```

응답은 `corpus`, `method`, `results`이며 결과마다 조문 원문·메타데이터·cosine 거리를 반환합니다. 현재 기본 인덱스는 근로기준법이며 설명 생성·위법 판정은 포함하지 않습니다. 검색 문장은 저장하지 않습니다.

첫 요청에 모델을 로딩하며 캐시에 없으면 다운로드가 필요합니다. **단일 worker**로 실행하고 발표 전에 한 번 검색해 준비하세요. 동시 검색은 `503 RAG_BUSY`, 세션당 분당 30회 초과는 `429`입니다. 일반 `/health/ready`는 DB만 확인하며 검색 준비 상태는 실제 검색으로 확인합니다.

외부 테스트는 HTTPS 접속 주소와 접근 가능한 네트워크가 별도로 필요합니다. `127.0.0.1`은 외부에서 접속할 수 없습니다. 공개 HTTPS 환경에서는 production·보안 쿠키·명시적인 프론트 Origin 등 기존 인증 설정도 맞춰야 합니다. 이 변경 자체가 서버를 인터넷에 공개하지는 않습니다.

## 프론트 연동

API 기본 주소는 `http://127.0.0.1:8000/api`입니다. 쿠키 전달을 위해 fetch에 `credentials: "include"`를 사용합니다.

별도 프론트 서버를 쓰면 백엔드 `.env`에 해당 Origin을 추가하고 재시작합니다.

```dotenv
CHECKIT_ALLOWED_ORIGINS=["http://127.0.0.1:8000","http://127.0.0.1:5173"]
```

주소·포트는 실제 환경에 맞춥니다. `localhost`와 `127.0.0.1`은 혼용하지 마세요. 같은 DB URI를 쓰면 팀원들도 같은 개발 DB에 연결됩니다.

## 구현 상태

- **완료:** 이메일·카카오·구글 인증 API, 비회원 세션, 소유권·만료 검사, 기록 조회·회원 귀속, 로컬 Chroma 법령 검색 API(추가 설치·설정 필요)
- **예정:** 업로드, OCR·AI 분석 파이프라인, 분석·취소·원본 다운로드·삭제, 비회원 자동 정리

회원 기록은 직접 삭제 전까지, 비회원 기록은 최초 업로드 후 24시간 보관하는 정책입니다. 현재 만료 접근 차단은 구현됐으며 실제 자동 삭제는 구현 전입니다.

## 파일 구조

```text
CheckIt_BE/
├── app/
│   ├── main.py          # 서버·CORS·헬스 체크
│   ├── api_docs.py      # Swagger 설명
│   ├── auth.py          # 회원·비회원 인증 API
│   ├── contracts.py     # 기록 조회·회원 귀속 API
│   ├── rag.py           # Data 패키지 연결·법령 검색 API
│   ├── access.py        # 세션·CSRF·소유권 검사
│   ├── security.py      # 해시·토큰·요청 제한
│   ├── database.py      # DB 연결 풀
│   ├── config.py        # 환경변수
│   ├── mail.py          # 인증 메일
│   └── errors.py        # 공통 오류
├── database/            # 기존 스키마·권한·검증 SQL
├── scripts/             # 관리자 설정·DB 검증 도구
├── tests/               # 자동 테스트
├── docs/                # 상세 안내·설계 문서
├── .env.example         # 환경변수 양식
└── requirements-lock.txt
```

요청은 **FastAPI → 세션·소유권 검사 → Supabase PostgreSQL** 순으로 처리합니다. 원본 파일은 향후 서버 폴더에 저장하고 DB에는 저장 키만 기록합니다.

## 자세한 안내

- [카카오·구글 개발자 등록 및 환경변수 설정](docs/social-login-setup.md)
- [인증·쿠키·CSRF·SMTP 설정](docs/auth-implementation.md)
- [DB 관리자 설정·검증](docs/backend-setup.md)
- [프론트 API 설계](docs/frontend-api-guide.md) — 미구현 목표 포함

로컬 테스트: `.venv/bin/python -m pytest -q` (실제 DB 테스트는 기본 제외)
