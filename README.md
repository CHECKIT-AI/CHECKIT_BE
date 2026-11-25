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

| 경로 | 역할 |
| --- | --- |
| `app/main.py`, `app/config.py` | 서버 진입점과 환경변수 |
| `app/auth.py`, `app/oauth.py`, `app/access.py`, `app/security.py` | 회원 인증·인가·요청 보호 |
| `app/contracts.py`, `app/analysis*.py` | 계약서 기록과 분석 작업 |
| `app/classifier.py`, `app/rag.py` | 분류 모델과 Data 검색 연결 |
| `database/` | 기준 스키마·권한·검증 SQL |
| `scripts/`, `tests/` | 관리·검증 도구와 자동 테스트 |
| `docs/`, `evaluation/` | 상세 안내·설계 및 평가 기록 |

## 평가

2026-11-17 개발용 전체 API 평가는 **가상 계약서 4건을 각각 2회** 실행했습니다. FastAPI `TestClient`로 회원가입부터 계약서 저장·분석·삭제까지 호출했고, 개발 DB·고정 분류 모델·`employment_basic_v004` RAG·Gemini를 사용했습니다. 브라우저 OCR과 외부 HTTP 서버 지연은 포함하지 않았습니다.

| 지표 | 첫 실행 | 재실행 |
| --- | ---: | ---: |
| 분석 작업 성공 | 4/4 | 4/4 |
| 필수 근로조건 8항목 기재 여부와 잠정 정답 일치 | 29/32 (90.6%) | 32/32 (100%) |

미제출 별첨을 참조하는 3항목의 판단이 실행 간 달라졌습니다. 정답은 전문가 검수 전이며 이 수치를 실제 계약서의 법률 판단 정확도로 해석할 수 없습니다. 측정 조건·오류 사례는 [전체 API 평가 기록](evaluation/required-terms/round2/report-2026-11-17.md), 분류·검색의 개별 평가는 [Data README](../CheckIt_Data/README.md)에 있습니다.

## 현재 구현 범위

회원 인증, 확인·마스킹한 계약서 텍스트 저장·조회·삭제, 조항 분류, 법령 검색, 규칙·Gemini 분석 작업 및 개발용 브라우저 OCR 테스트 화면이 있습니다. 정식 프론트엔드 OCR 연결·검증과 분석 취소는 완료되지 않았습니다. API 사용법과 선택 기능 설정은 [상세 안내](docs/README-details.md)에 보존했습니다.
