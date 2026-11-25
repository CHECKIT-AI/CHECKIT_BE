# CheckIt Backend

근로계약서 회원 인증·기록·분석 API입니다. ASGI 진입점은 `app.main:app`입니다.

## 실행 방법

Python 3.13이 필요합니다. 모든 명령은 이 저장소 루트에서 실행합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
cp .env.example .env
```

`.env`에 서버용 `checkit_backend` PostgreSQL 연결 URI(`CHECKIT_DATABASE_URL`)를 입력합니다. 기존 DB에 초기 SQL을 다시 실행하지 마세요. 기본 실행에는 분류·RAG·Gemini 기능이 필요하지 않으며, 이를 사용하려면 [상세 설정](docs/README-details.md#계약-조항-분류-모델-연결)을 따릅니다.

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

[Swagger](http://127.0.0.1:8000/docs) · [DB 준비 상태](http://127.0.0.1:8000/health/ready) · 기본 테스트: `.venv/bin/python -m pytest -q` (실제 DB 통합 테스트 제외).

## 파일 구조

```text
CheckIt_BE/
├── app/
│   ├── main.py          # 서버·CORS·헬스 체크
│   ├── api_docs.py      # Swagger 설명
│   ├── auth.py          # 회원 인증 API
│   ├── oauth.py         # 소셜 로그인 API
│   ├── contracts.py     # 계약서 기록 API
│   ├── analysis.py      # 계약서 조항 분석 API
│   ├── analysis_jobs.py # 분석 작업·결과 저장
│   ├── classifier.py    # 조항 분류 모델 연결
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

## 평가

2026-11-17 개발용 전체 API 평가는 **가상 계약서 4건을 각각 2회** 실행했습니다. FastAPI `TestClient`로 회원가입부터 계약서 저장·분석·삭제까지 호출했고, 개발 DB·고정 분류 모델·`employment_basic_v004` RAG·Gemini를 사용했습니다. 브라우저 OCR과 외부 HTTP 서버 지연은 포함하지 않았습니다.

| 지표 | 첫 실행 | 재실행 |
| --- | ---: | ---: |
| 분석 작업 성공 | 4/4 | 4/4 |
| 필수 근로조건 8항목 기재 여부와 잠정 정답 일치 | 29/32 (90.6%) | 32/32 (100%) |

미제출 별첨을 참조하는 3항목의 판단이 실행 간 달라졌습니다. 정답은 전문가 검수 전이며 이 수치를 실제 계약서의 법률 판단 정확도로 해석할 수 없습니다. 측정 조건·오류 사례는 [전체 API 평가 기록](evaluation/required-terms/round2/report-2026-11-17.md), 분류·검색의 개별 평가는 [Data README](../CheckIt_Data/README.md)에 있습니다.

## 현재 구현 범위

회원 인증, 확인·마스킹한 계약서 텍스트 저장·조회·삭제, 조항 분류, 법령 검색, 규칙·Gemini 분석 작업 및 개발용 브라우저 OCR 테스트 화면이 있습니다. 정식 프론트엔드 OCR 연결·검증과 분석 취소는 완료되지 않았습니다. API 사용법과 선택 기능 설정은 [상세 안내](docs/README-details.md)에 보존했습니다.
