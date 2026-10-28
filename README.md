# CheckIt Backend

FastAPI + Supabase PostgreSQL 기반 계약서 분석 백엔드입니다.

## 최근 변경 요약 (2026-10-28)

- **RAG 입력:** `POST /api/rag/search`가 `clause_id`, `labels`, `text`, `top_k`를 받아 분류 라벨과 조항 원문을 함께 검색합니다. 기존 `query` 입력도 유지합니다.
- **검색 대상:** `employment_basic_v004`, **503청크**. 원문으로 전체 인덱스의 후보를 찾고 라벨로 작은 우선순위만 부여하며, 원문 금액·시간·날짜를 보존합니다.
- **응답 연결:** 조항 ID·라벨·정책 버전과 근거별 원문·출처·기본 순위·라벨 반영 정보를 반환합니다. 미수집 연도 고시는 `warnings`로 알립니다.
- **검증:** 백엔드 RAG 테스트 **22개**, Data 테스트 **24개** 통과. 실제 인증·CSRF를 포함한 조항 4건·기존 query 1건·중복 라벨 거부를 확인했습니다.

수동 라벨을 붙인 합성 조항 30개에서 Hit@1은 66.7%→70.0%, Hit@5는 93.3%(28/30)로 같았습니다. 이는 검색 개발 평가이며 **실제 분류 모델·OCR·위법 판정·설명 생성까지 연결한 결과는 아닙니다**. [조항 입력 평가 기록](../CheckIt_Data/test/rag/comparisons/labeled_clauses_v001_20261028/REPORT.md)을 참고하세요.


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

2026-10-28 기준 기본 검색 대상은 **`employment_basic_v004`(503청크)**입니다. Data의 BGE-M3 Chroma 인덱스를 사용하며, 백엔드 API의 검색 방식은 `dense`입니다. Data에 별도로 구축된 BM25는 이 API에서 사용하지 않습니다.

**RAG(Chroma) 기능을 테스트하려면 백엔드 담당자에게 서버 실행 및 접속 주소를 요청하세요.** 전달받은 Cloudflare HTTPS 주소의 `/docs`에서 테스트할 수 있으며, 백엔드 클론이나 Chroma 설치는 필요 없습니다. 임시 주소는 변경될 수 있으므로 테스트 전에 최신 주소를 확인합니다.

아래는 검색 환경을 직접 준비하는 경우의 설정입니다.

`CheckIt_BE`와 `CheckIt_Data`를 같은 상위 폴더에 준비합니다. 검색 로직·청크·인덱스는 Data에 두고 백엔드 프로세스 안에서 호출합니다. 별도 Data 서버는 필요 없습니다.

백엔드 폴더에서 추가 패키지를 설치합니다. 모델 의존성 설치로 시간이 걸릴 수 있습니다.

```bash
.venv/bin/python -m pip install -r requirements-rag.txt
```

백엔드 `.env`에 추가하고 서버를 재시작합니다.

```dotenv
CHECKIT_RAG_ENABLED=true
CHECKIT_RAG_CORPUS=employment_basic_v004
CHECKIT_RAG_METHOD=dense
CHECKIT_RAG_DEVICE=cpu
```

Data의 `data/rag/processed/employment_basic_v004/chunks.jsonl`과 `storage/rag/<corpus>/index_manifest.json`, `chroma/`가 필요합니다. Git 클론만으로는 이 데이터가 생기지 않습니다. 현재 503개 corpus에는 기존 8개 법령 외에 시행규칙 3개·공휴일 규정·선택 별표 8개·고시가 필요합니다. 기본 법령 수집 명령만으로는 전체 구성이 생성되지 않습니다. 준비·재구축 방법은 [Data README](../CheckIt_Data/README.md)와 [원문 보완 기록](../CheckIt_Data/BASIC_LABOR_COVERAGE.md)을 참고하세요. Data는 **editable 설치**로 연결하므로 설치 후 해당 폴더를 옮기지 않습니다.

Swagger에서 CSRF 발급 → 비회원 세션 생성 → 응답의 최신 CSRF 토큰으로 `POST /api/rag/search`를 호출합니다. 회원 로그인 상태에서도 사용할 수 있습니다.

```json
{
  "clause_id": "clause_007",
  "labels": ["임금", "기타 근로조건"],
  "text": "월급에서 회사 대여금을 매달 공제한다.",
  "top_k": 5
}
```

분류 모델 결과의 라벨과 **해당 조항 원문**을 함께 전달합니다. `clause_id`는 원본 조항과 연결할 1~128자 ID, `text`는 1~2000자입니다. 라벨은 아래 10개 한국어 이름 중 중복 없이 1~10개를 받습니다.

`임금`, `근로시간`, `휴일`, `휴가`, `근무 장소·업무`, `계약기간`, `계약 종료`, `손해배상·위약금`, `기타 근로조건`, `그 외`.

라벨은 작은 우선순위 신호로만 사용합니다. 전체 인덱스의 상위 20개 후보를 유지해 원문으로 검색하고, 연결 근거에 제한된 보너스를 적용합니다. 원문의 실제 금액·날짜·시간을 치환하지 않습니다. `그 외`도 검색을 생략하지 않습니다. 결과에 `clause_id`, `labels`, `retrieval_policy`를 반환하며 각 hit의 `base_rank`, `matched_labels`, `label_priority_score`로 우선순위 반영을 확인합니다. 프론트는 응답의 `rank` 순서를 유지합니다. `cosine_distance`는 변경 전 원래 거리이고 우선순위 점수는 정확도 확률이 아닙니다.

기존 `{"query":"검색 문장","top_k":5}` 형식도 지원합니다. 두 형식을 섞으면 422를 반환합니다. 모델 분류·OCR 자체가 구현된 것은 아니며, 현재는 그 결과를 받는 검색 인터페이스입니다. [조항 입력 개발 평가](../CheckIt_Data/test/rag/comparisons/labeled_clauses_v001_20261028/REPORT.md)를 참고하세요.

응답은 `corpus`, `method`, `results`, `warnings`이며 결과마다 조문 원문·메타데이터·cosine 거리를 반환합니다. 현재 기본 인덱스는 근로관계 12개 법령·선택 별표 8개·2026년 최저임금 고시, 총 503개 청크입니다. 설명 생성·위법 판정은 포함하지 않습니다. 고시의 적용 기간은 2026년이며 질문에 명시한 연도와 연간 고시 기간을 대조합니다. 미수집 연도는 `warnings`로 알리고, 일반 법령의 과거 버전은 자동 복원하지 않습니다. 검색 문장은 저장하지 않습니다. 고시·별표에는 자료 유형과 적용 기간 등 해당 자료에 있는 메타데이터도 반환합니다. 비밀유지·경업금지·사회보험·용역·파견·저작권에 대한 종합 판단까지 지원하는 것은 아닙니다.

첫 요청에 모델을 로딩하며 캐시에 없으면 다운로드가 필요합니다. **단일 worker**로 실행하고 발표 전에 한 번 검색해 준비하세요. 동시 검색은 `503 RAG_BUSY`, 세션당 분당 30회 초과는 `429`입니다. 일반 `/health/ready`는 DB만 확인하며 검색 준비 상태는 실제 검색으로 확인합니다.

외부 테스트는 HTTPS 접속 주소와 접근 가능한 네트워크가 별도로 필요합니다. `127.0.0.1`은 외부에서 접속할 수 없습니다. 공개 HTTPS 환경에서는 production·보안 쿠키·명시적인 프론트 Origin 등 기존 인증 설정도 맞춰야 합니다. 이 변경 자체가 서버를 인터넷에 공개하지는 않습니다.

### 반영 확인 결과

2026-10-28 초기 인덱스 반영 시 DB 준비 상태와 인증·CSRF를 포함한 검색 API 8건을 확인했습니다. 이후 라벨+원문 입력 반영 후 조항 4건과 기존 query 1건에서 200·새 corpus·조항 연결 정보를 확인했고, 중복 라벨 입력은 422로 거부했습니다. 최신 백엔드 RAG 테스트 **22개**, Data 단위 테스트 **24개**가 통과했습니다. 이는 연결·동작 검증이며 전체 분석 정확도 평가는 아닙니다.

기존 production HTTPS 보안 설정은 유지했습니다. 루프백 테스트에서는 쿠키 전달을 명시했으며 외부 HTTPS 터널 경로는 별도 검증하지 않았습니다. production·보안 쿠키 설정인 서버를 `http://127.0.0.1` Swagger에서 호출하면 인증에 실패할 수 있으므로 실제 브라우저 테스트는 허용된 HTTPS 주소에서 진행하세요.

## 프론트 연동

다음 두 가지 방법 중 선택합니다.

| 방법 | 사용 안내 |
|---|---|
| 백엔드 레포 클론 후 로컬 실행 | 분석·RAG 외의 구현된 API를 연동할 때 사용합니다. 위 실행 절차에 따라 패키지와 `.env`를 설정하고, `CHECKIT_RAG_ENABLED=false`로 실행합니다. API 기본 주소는 `http://127.0.0.1:8000/api`입니다. |
| 담당자에게 서버 주소 요청 | 백엔드 클론이나 Chroma 설치 없이 전달받은 Cloudflare HTTPS 주소를 사용합니다. API 기본 주소는 `전달받은 주소/api`, Swagger는 `전달받은 주소/docs`입니다. RAG 기능 테스트는 이 방법을 사용합니다. |

담당자 서버는 실행 중일 때만 사용할 수 있습니다. 테스트 전에 주소를 요청하고, 임시 주소가 변경되면 프론트의 연결 설정도 갱신합니다. 현재 제공되는 기능은 아래 구현 상태를 참고하세요.

두 방법 모두 쿠키 전달을 위해 fetch에 `credentials: "include"`를 사용하고, POST 요청에는 최신 CSRF 토큰을 전달합니다. 프론트 접속 주소를 백엔드 허용 Origin에 등록해야 하므로 담당자 서버를 사용할 때는 해당 주소도 공유하세요. 쿠키 인증을 위해 프론트 개발 서버의 `/api` 프록시를 사용하며, 담당자 서버의 보안 쿠키 설정에 맞춰 프론트도 HTTPS로 실행합니다.

로컬 백엔드에서 별도 프론트 서버를 쓰면 백엔드 `.env`에 해당 Origin을 추가하고 재시작합니다.

```dotenv
CHECKIT_ALLOWED_ORIGINS=["http://127.0.0.1:8000","http://127.0.0.1:5173"]
```

주소·포트는 실제 환경에 맞춥니다. `localhost`와 `127.0.0.1`은 혼용하지 마세요. 같은 DB URI를 쓰면 팀원들도 같은 개발 DB에 연결됩니다.

서버 공유와 원격 관리 설정은 [팀 접속·원격 실행 안내](docs/team-server-access.md)를 참고하세요.

## 구현 상태

- **완료:** 이메일·카카오·구글 인증 API, 비회원 세션, 소유권·만료 검사, 기록 조회·회원 귀속, 라벨+조항 원문을 받는 로컬 Chroma 법령 검색 API(추가 설치·설정 필요)
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

## 현재 검색 인덱스의 평가 결과

2026-10-28 Data에서 현재 503개 인덱스를 검증했습니다. 저장·원문 보존·검색 주석·해시·벡터 무결성 15개 검사를 모두 통과했습니다. 기본 API와 같은 dense 검색에서 기존 90개 개발 질의 Hit@5는 **95.6%**, 추가 범위 42개 합성 개발 질의 Hit@5는 **100%**였습니다. 서로 다른 평가셋이므로 두 수치를 직접 비교하거나 합쳐서 실제 서비스 정확도로 표현하지 않습니다.

추가 표현 합성 14개는 Hit@5 64.3%였고, 모호한 표현·복합 문장에 실패가 남습니다. 보충어를 오류 분석 후 설계한 개발셋 결과이며 실제 계약서·전문가 검수·위법 판정에 대한 평가가 아닙니다. 다른 연도 고시와 일반 법령의 과거 버전은 후속 과제입니다. 질의별 결과와 한계는 [Data 평가 보고서](../CheckIt_Data/test/rag/comparisons/employment_basic_v004_improvements_20261028/REPORT.md)를 참고하세요.
