# AI 패키지 함수 입력·출력 명세안

2026-10-21. 설치 가능한 AI 패키지를 백엔드 측 분석 실행 코드에서 호출하는 규격입니다. 아래 함수·모델명은 신규 설계안이며 실제 함수 구현이나 패키지 생성은 수행하지 않았습니다. `checkit_ai`는 예시 패키지명입니다.

> 최신 변경: 화면 종료 후 분석 지속·진행 상태 재접근은 첫 버전에서 제외했습니다. 추출·분석 HTTP 요청이 완료 결과를 직접 반환합니다. 아래 내부 작업 ID·취소·상태 정보는 서버 실행 제어를 위한 후보이며 별도 상태 조회 API를 뜻하지 않습니다. 작업 실행 방식·연결 종료 처리는 단순화안에 맞춰 후속 조정합니다.
## 1. 책임 경계

화면 동작 API 통합에 따라 백엔드는 업로드 요청 안에서 extract_text를 호출하고, 분석 요청 안에서 사용자 수정본 저장·확정 후 analyze_contract를 호출합니다. 공개 HTTP API가 줄어도 AI 함수 경계·입력 버전 검증은 유지합니다. 클라이언트가 confirmed_at이나 임의 확정 ID를 제출해 검증을 건너뛰지 않도록, 백엔드가 저장·확정한 AnalysisInput을 구성합니다.

| 백엔드 책임 | AI 패키지 책임 |
| --- | --- |
| 업로드 검사·소유권·보관 기한·파일 키 관리 | OCR·정보 추출·조항 분리·분류·법령 검색·설명 생성 |
| 사용자 수정·확정 텍스트 관리 | 받은 입력 버전만 사용해 분석 |
| 작업 접수·진행 상태·취소·동시 실행 제어 | 진행 이벤트와 취소 확인 지점 제공 |
| 결과 스키마·인용·위치 검증 후 DB 저장 | 구조화된 결과와 실제 검색 근거 반환 |
| 삭제·최신 결과 교체·비회원 계정 저장 | 사용자 계정 DB를 직접 수정하지 않음 |

회원 비밀번호·세션·사용자 이메일을 AI 입력에 넣지 않습니다. 파일 경로는 백엔드가 storage_key를 검증한 뒤 서버 내부 경로로 해석해 전달합니다. 사용자 제공 임의 경로·URL을 AI가 다운로드하거나 열도록 하지 않습니다.

## 2. 공개 호출 인터페이스

아래는 함수 형태를 설명하기 위한 시그니처이며 실행 코드는 아닙니다. 동기 함수를 작업자에서 실행하는 기본안입니다.

```python
extract_text(request: ExtractionInput, *, context: RunContext) -> ExtractionOutput
analyze_contract(request: AnalysisInput, *, context: RunContext) -> AnalysisOutput
```

내부 단계를 독립 평가·교체할 수 있도록 아래 함수도 분리합니다. 백엔드는 보통 위 두 함수를 호출하고, 내부 함수들을 직접 순서대로 호출할 필요는 없습니다.

```python
split_clauses(document: ConfirmedDocument) -> list[Clause]
classify_clauses(clauses: list[Clause]) -> ClassificationOutput
extract_facts(document: ConfirmedDocument, clauses: list[Clause]) -> list[Fact]
search_laws(request: LawSearchInput) -> LawSearchOutput
evaluate_checks(request: CheckEvaluationInput) -> list[CheckItem]
```

`evaluate_checks`는 적용 조건·세부 값·검색 근거를 종합해 판단·설명합니다. 분류 라벨이나 검색 점수만으로 위법·누락을 결정하지 않습니다. 학습·법령 수집·인덱스 생성은 이 호출 과정에 넣지 않습니다.

## 3. 공통 실행 컨텍스트·식별자

| 필드 | 타입·내용 |
| --- | --- |
| `schema_version` | 문자열. 초기 `1.0` 후보, 백엔드·AI 호환 규격 |
| `contract_id`, `job_id` | UUID 문자열. 실행·입력·결과 매칭용, 권한 증명이 아님 |
| `file_generation_id` | 파일 묶음 버전 ID |
| `revision_id` | 분석할 확정 텍스트 ID. 추출 입력에는 없음 |
| `context.report_progress(stage)` | 단계 이벤트 전달 콜백. 임의의 완료 백분율 생성 금지 |
| `context.check_cancelled()` | 취소·삭제·만료 여부 확인 후 중단시키는 콜백 |

RunContext는 JSON 데이터가 아니라 프로세스 내부 콜백 인터페이스입니다. 백엔드 작업 실행기가 구현합니다. 외부 OCR·LLM 요청을 즉시 중단할 수 없으면 완료 후 다시 취소를 확인하고 결과 저장을 차단합니다. 별도 프로세스 사용 시 전달 방법은 작업자 설계에서 정합니다.

## 4. OCR·텍스트 추출

### ExtractionInput

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| 공통 식별자 | 문자열 | schema_version·contract_id·job_id·file_generation_id |
| `input_kind` | PDF 또는 IMAGES | 혼합 불가 |
| `files` | FileInput 배열 | 검증된 원본 파일 목록 |
| `pages` | PageInput 배열 | 확정된 페이지 순서 |

FileInput: `file_id`, 서버 내부 `local_path`, 실제 검사한 `media_type`. PageInput: `page_id`, `file_id`, `source_page_number`(1부터), `page_order`(1~10). PDF는 파일 1개·페이지 여러 개, 사진은 파일별 페이지 1개입니다.

### ExtractionOutput

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| 공통 식별자 | 문자열 | 입력 식별자를 그대로 반환 |
| `content` | 문자열 | 페이지 순서대로 구성한 전체 텍스트 |
| `pages` | 배열 | 페이지 ID·순서·추출 방법·인식 상태 |
| `blocks` | TextBlock 배열 | 문장/문단과 원본 좌표 연결 |
| `review_candidates` | 배열 | 임금·시간 등 핵심 값 후보와 불확실 블록 ID |
| `warnings` | 배열 | 비치명적 문제. 코드·대상 페이지·설명 |
| `versions` | 객체 | OCR 도구·모델·텍스트 처리 버전 |

- PDF는 필요에 따라 내장 텍스트 또는 OCR로 추출하되 같은 출력 규격을 사용합니다. native text에는 OCR confidence를 꾸며 넣지 않고 null로 둡니다.
- 페이지 전체를 읽지 못하면 분석 가능한 정상 문서처럼 조용히 통과시키지 않습니다. `DOCUMENT_UNREADABLE`로 실패하고 문제 페이지 ID를 함께 반환하며 계약서 전체 재업로드를 안내합니다.
- 개인정보 자동 마스킹을 완료했다고 표시하지 않습니다. 사용자 수정 단계에는 수치·날짜를 보존한 텍스트를 반환합니다.

### TextBlock·원본 영역

| 필드 | 내용 |
| --- | --- |
| `block_id`, `page_id` | 입력 버전 내 안정적인 식별자 |
| `start`, `end` | 해당 버전 content의 Unicode 코드포인트 인덱스 `[start,end)` |
| `text` | `content[start:end]`와 일치하는 블록 문장 |
| `regions` | 원본 페이지 기준 0~1 정규화 polygon 배열. 회전·변환을 원본 방향으로 역매핑 |
| `recognition_confidence` | 0~1 또는 null. OCR 엔진의 신호이며 정확도 확률로 단정하지 않음 |
| `is_user_edited` | 추출본은 false, 수정본은 수정 여부 |

한글·이모지 인덱스가 다른 JavaScript 문자열 슬라이싱을 피하려면 프론트엔드는 블록 ID·text를 기준으로 편집하고, 전체 content와 offset은 서버에서 재계산합니다. 백엔드는 수정된 content와 blocks의 불일치를 거부합니다. 사용자 추가 문장처럼 위치를 연결할 수 없으면 regions는 빈 배열입니다.

## 5. 확인·수정 후 계약 내용 분석

### AnalysisInput

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| 공통 식별자 | 문자열 | schema_version·contract_id·job_id·file_generation_id·revision_id |
| `contract_type` | 문자열 | 사용자가 선택한 계약서 종류 |
| `content`, `blocks`, `pages` | 추출 규격과 동일 | 사용자가 확인·수정한 버전. 원본 OCR을 다시 읽어 대체하지 않음 |
| `confirmed_at` | ISO 날짜·시각 | 입력 확정 여부 |
| `analysis_config_id` | 문자열 | 서버가 선택한 지원 점검 규칙·모델·corpus 설정 버전 |

사용자에게 사업장 규모 등을 추가 질문하는 단계는 넣지 않습니다. 정보가 없으면 추정으로 채우지 않고 항목별 추가 확인으로 반환합니다.

### 분석 내부 중간 규격

| 객체·함수 | 입력·출력 내용 |
| --- | --- |
| Clause / split_clauses | clause_id·text·상위 제목·block_id·page_id·원본 위치·수정 여부 |
| ClassificationOutput | clause_id별 복수 labels, 라벨별 점수·임계값 버전·분류 모델 버전. 낮은 확신은 표시 |
| Fact / extract_facts | 임금액·지급일·근무시간 등 field_code, 원문 값·파싱 값·단위·clause/block 근거·미확인 이유 |
| LawSearchInput | query_text, label_hints, corpus_id, top_k. 검색 방법·모델은 서버 설정 |
| LawSearchOutput | hits 배열·검색 설정·버전·지원 범위 경고 |
| CheckEvaluationInput | 원본 연결이 있는 조항·분류·세부 값·검색 근거·점검 규칙 버전 |

- 라벨은 임금·근로시간·휴일·휴가·근무 장소 및 업무·계약기간·계약 종료·손해배상 및 위약금·기타 근로조건·그 외에 대응하는 안정 코드와 `labels.json` 버전을 사용합니다. 코드와 한국어 표시명·모델 출력 순서 매핑을 고정합니다.
- 임금 라벨이 있다고 금액·지급일 등이 모두 채워진 것으로 취급하지 않습니다. 금액·시간 파싱에서는 실제 숫자를 학습용 가명 값으로 치환하지 않습니다.
- label_hints는 검색 우선순위 신호입니다. 오분류로 관련 법령이 제외되지 않도록 fallback 검색을 둡니다. 현재 검색 코드에 라벨 필터가 이미 구현돼 있다고 가정하지 않습니다.

### LawHit와 현재 RAG 연결

LawHit 필드: `citation_id`, `rank`, `chunk_id`, `article_id`, `law_id`, `law_name`, `article_number`, `content`, `source_url`, `law_version_id`, `snapshot_effective_date`, `article_effective_date`, `corpus_id`, `score_type`, `score`.

- 현재 `LawRetriever.search(text, top_k)`는 `rank`, `chunk_id`, `content`, `metadata`, dense 방식이면 `cosine_distance`를 반환합니다. AI 패키지 어댑터에서 위 LawHit 규격으로 변환합니다.
- `metadata.article_no` → article_number, metadata의 법령·조문 ID·출처·시행일 필드를 대응시킵니다. snapshot 시행일과 개별 조문 시행일을 구분하고 없으면 null로 보존합니다.
- dense score_type은 COSINE_DISTANCE로 낮을수록 가깝습니다. 다른 검색 방법은 점수 종류를 구분하고 확률로 반환하지 않습니다.
- 모델 로드·인덱스 준비는 런타임 초기화 때 하고 매 함수 호출마다 재학습·인덱싱하지 않습니다. 현재 retriever는 last_candidates 등 상태를 변경하므로 동시 호출 시 인스턴스 공유 정책을 정해야 합니다.

### AnalysisOutput

| 필드 | 의미 |
| --- | --- |
| 공통 식별자 | 입력 식별자·revision_id 그대로 반환 |
| `summary` | 검토 결과 요약. 근거 없는 적법·안전 보장 금지 |
| `items` | CheckItem 배열 |
| `citations` | 실제 사용된 LawHit 원문 스냅샷 배열 |
| `employment_attributes` | 기간제·단시간 등 자동 파악 속성, 근거·미확인 이유. 하나의 유형으로 강제하지 않음 |
| `limitations` | 미지원 법령·정보 부족 등 분석 범위 제한 |
| `versions` | 패키지·모델·프롬프트·라벨·전처리·규칙·corpus 버전 |

CheckItem 필드: `item_id`, `check_code`, `labels`, `status`, `quoted_text`, `explanation`, `required_information`, `source_locations`, `citation_ids`.

- status 후보는 CAUTION/MISSING_SUSPECTED/NEEDS_CONFIRMATION/PRESENT이며 기존 설계의 한글 상태와 매핑합니다. 상태 판정 규칙과 지원 check_code 목록은 별도 검수가 필요합니다.
- citation_ids는 반환된 citations 안의 항목만 참조합니다. 설명 생성 단계가 새 법령 원문·URL을 임의 작성하지 않도록 검증합니다. 판단 근거를 찾지 못하면 빈 인용과 추가 확인 이유를 반환합니다.
- quoted_text는 해당 입력 버전과 연결하고, 수정된 문장에는 수정본임을 표시합니다. 누락 항목은 인용 문장·좌표가 없을 수 있습니다.
- counts는 백엔드가 items로부터 계산해 불일치를 막습니다. 초기 집계는 점검 항목 단위로 제안하며 최종 규칙은 미확정입니다.

## 6. 실패·진행·취소

AI 함수는 성공 구조를 반환하거나 구조화된 `AIError`를 발생시키는 계약입니다. 오류 필드: code, stage, retryable, recovery_action, 사용자 안내용 message, 관련 page_ids. 계정 정보·파일 절대 경로·원문 전체·비밀값은 오류 응답에 넣지 않습니다.

| 오류 코드 예시 | 행동 | 비고 |
| --- | --- | --- |
| DOCUMENT_UNREADABLE / FILE_CORRUPT | REUPLOAD | 페이지 ID를 안내하되 전체 계약서 재업로드 |
| OCR_UPSTREAM_TIMEOUT / MODEL_SERVICE_UNAVAILABLE | RETRY | 같은 입력으로 재시도 가능한 일시 장애 |
| MODEL_NOT_READY / INDEX_NOT_READY | NONE | 서버 설정 문제. 사용자 재업로드로 해결된다고 안내하지 않음 |
| UNSUPPORTED_DOCUMENT_TYPE | REUPLOAD 또는 종류 재선택 | 구체적인 UI는 종류 불일치 정책 확정 후 매핑 |
| CANCELLED | NONE | 사용자 취소. 기술적 실패와 구분 |

PDF_LOCKED·용량 초과·소유권·만료는 가능한 한 백엔드의 사전 검사에서 처리합니다. AI가 같은 오류를 발견하면 동일한 공개 오류 코드로 변환합니다. 정보 부족은 함수 예외로 전체 분석을 실패시키지 않고 CheckItem의 추가 확인 상태로 표현합니다.

진행 단계는 EXTRACT/CLASSIFY/RETRIEVE/EVALUATE/EXPLAIN 후보입니다. 출력 저장 직전 백엔드는 취소·삭제·만료·입력 버전을 다시 검사합니다. AI 함수가 정상 반환해도 무조건 현재 결과로 게시하지 않습니다.

## 7. 연결 전 확인할 항목

1. OCR·분류·설명 기능은 현재 로컬 RAG와 달리 구현 완료를 확인하지 못했습니다. 이 문서는 목표 인터페이스입니다.
2. 기본·하이브리드 등 기존 검색 결과의 score 필드 어댑터 매핑을 실제 산출물로 확인합니다.
3. JSON schema/Pydantic 모델과 AI 패키지 간 호환성 테스트는 구현 단계에서 작성합니다.
4. 실제 법률 점검 규칙·지원 법령 범위·인용 검증은 검색 API 규격만 정한다고 완료되지 않습니다.
