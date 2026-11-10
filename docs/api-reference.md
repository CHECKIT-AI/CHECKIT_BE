# 회원 전용 백엔드 API 명세

> 브라우저에서 확인·마스킹한 계약서 텍스트의 저장과 분석 job이 구현되어 있습니다. 서버 원본 업로드·OCR·원본 다운로드·삭제 API는 없습니다. [확정 설계](contract-risk-detection-design.md)를 참고하세요.

**Base URL:** `http://localhost:8000`

**POST 공통 헤더:** `X-CSRF-Token: <토큰>`

**인증:** HttpOnly 쿠키 · 프론트 요청에 `credentials: "include"`

계약서 조회와 RAG 검색은 유효한 회원 세션이 필요합니다. 로그인하지 않은 사용자를 위한 임시 세션이나 기록 저장·귀속 API는 제공하지 않습니다.

## API 명세

| API명 | 메서드 | 경로 | 입력 | 성공 응답 |
| --- | --- | --- | --- | --- |
| 서버 상태 확인 | GET | `/health/live` | 없음 | `200` · `{"status":"ok"}` |
| DB 연결 확인 | GET | `/health/ready` | 없음 | `200` · `{"status":"ok"}` |
| CSRF 토큰 발급 | GET | `/api/auth/csrf` | 없음 | `200` · `{"csrf_token":"string"}` |
| 이메일 회원가입 | POST | `/api/auth/signup` | `{"email":"","password":""}` | `202` · `{"message":"string"}` |
| 인증 메일 재발송 | POST | `/api/auth/email-verification/resend` | `{"email":""}` | `202` · `{"message":"string"}` |
| 이메일 인증 완료 | POST | `/api/auth/email-verification/confirm` | `{"token":""}` | `200` · `{"verified":true,"login_required":true}` |
| 이메일 로그인 | POST | `/api/auth/login` | `{"email":"","password":""}` | `200` · `{"user":User,"csrf_token":"string"}` |
| 소셜 로그인 시작 | POST | `/api/auth/oauth/{provider}/start` | `{"return_path":"/"}` | `200` · `{"authorization_url":"string"}` |
| 소셜 로그인 콜백 | GET | `/api/auth/oauth/{provider}/callback` | 제공자의 `code`, `state` 또는 오류 | `303` · 로그인 완료 화면으로 이동 |
| 내 로그인 정보 | GET | `/api/auth/me` | 없음 | `200` · `{"user":User}` |
| 로그아웃 | POST | `/api/auth/logout` | 본문 없음 | `204` · 본문 없음 |
| 마스킹 계약서 저장 | POST | `/api/contracts` | `input_kind`, 순서 있는 `pages`, 확인 플래그 2개 | `201` · `{"contract_id":"UUID","revision_id":"UUID"}` |
| 내 계약서 목록 | GET | `/api/contracts` | Query: `limit=20&offset=0` | `200` · `{"contracts":ContractSummary[],"limit":20,"offset":0}` |
| 계약서 상세 조회 | GET | `/api/contracts/{contract_id}` | Path: `contract_id` UUID | `200` · `ContractDetailResponse` |
| 계약 조항 분류 | POST | `/api/classifier/predict` | `{"text":"계약 조항"}` | `200` · 예측 라벨·점수·임계값·모델 버전 |
| 관련 법령 검색 | POST | `/api/rag/search` | 일반 검색, 명시적 라벨 조항 또는 자동 분류 조항 | `200` · 검색 corpus·결과·경고 |
| 근로계약서 분석 시작 | POST | `/api/analysis/contracts/{contract_id}/jobs` | 필수: `privacy_confirmed=true`, `gemini_notice_acknowledged=true`; 선택: 적용 조건·`top_k` | `202` · `{"job_id":"UUID","status":"QUEUED"}` |
| 분석 상태·결과 조회 | GET | `/api/analysis/contracts/{contract_id}/jobs/{job_id}` | 경로 UUID | `200` · 상태·단계·오류 코드·완료 결과 |

`provider`는 `kakao` 또는 `google`입니다. 소셜 로그인 콜백은 프론트에서 직접 호출하지 않고 제공자가 브라우저를 이동시킵니다.

RAG 검색은 다음 세 입력 중 하나만 사용합니다.

```json
{"query":"검색 문장","top_k":5}
```

```json
{"clause_id":"clause_007","labels":["임금"],"text":"해당 조항 원문","top_k":5}
```

```json
{"clause_id":"clause_007","text":"분류 후 검색할 조항 원문","top_k":5}
```

마지막 형식은 고정 revision의 분류 모델을 먼저 호출하고 예측 라벨로 검색합니다. 빈 라벨은 `[]`로 유지하며 원문 검색만 수행하고 라벨 우선순위는 적용하지 않습니다.

브라우저에서 PDF·사진의 추출·OCR·수정·마스킹을 마친 다음 아래 JSON만 `POST /api/contracts`로 전송합니다. 원본 파일은 보내지 않습니다. 페이지는 1부터 연속이며 최대 10개입니다. 확인 플래그는 사용자가 실제로 확인하고 Gemini 전송 안내를 본 뒤에만 true로 설정합니다. 서버는 명백한 주민등록번호·휴대전화·이메일을 발견하면 `422 PERSONAL_DATA_DETECTED`로 거부하지만, 모든 개인정보 제거를 보장하지는 않습니다.

```json
{"input_kind":"PDF","pages":[{"page":1,"text":"제1조(임금)\n시급 12,000원"}],"privacy_confirmed":true,"gemini_notice_acknowledged":true}
```

분석 시작은 회원 소유 `EMPLOYMENT` 계약서의 현재 세대에 최신 **확정 마스킹 텍스트 revision**이 있어야 합니다. POST에는 쿠키·Origin·CSRF와 두 확인 플래그가 필요합니다. `effective_date`는 `YYYY-MM-DD`, `employee_count`는 1~100000, `weekly_hours`는 0보다 크고 168 이하, `top_k`는 1~10입니다. 문서에서 확인되지 않은 적용 조건은 보내지 않고 미상으로 처리합니다. 최대 원문 30000자·조항 100개·조항당 2000자·문제 후보 50개입니다.

상태는 `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`입니다. 완료 결과는 `analysis_results`와 `check_items`, 인용된 경우 `law_citations`에 저장됩니다. `rule_candidate.category`는 `MISSING`, `LEGAL_RISK`, `DISADVANTAGE` 중 하나이며, 원문 위치·확인 필요 정보도 포함합니다. 파일 없는 텍스트 계약의 상세 응답은 `files`·`pages`가 빈 배열이고 페이지 범위는 `text.blocks`의 `{page,start,end}`로 표현합니다. `status=FAILED`일 때 `error_code`만 반환하며 외부 모델 응답 전문은 반환하지 않습니다. 주요 오류: `409 ANALYSIS_INPUT_UNAVAILABLE`, `409 ANALYSIS_CONFLICT`, `422 ANALYSIS_INPUT_LIMIT`, `422 PERSONAL_DATA_DETECTED`, `503 ANALYSIS_UNAVAILABLE`.

분석 job은 후보마다 RAG를 검색한 뒤 계약서 전체 조항과 중복 제거한 법령 청크를 보통 한 번의 Gemini 요청에 묶습니다. 각 후보는 고유 `candidate_id`와 관련 법령 ID를 갖고, Gemini 응답의 후보 누락·중복·교차 인용은 저장 전에 거부합니다. 입력·출력 한도 초과 때만 후보를 나눠 다시 호출합니다. 기존의 후보별 Gemini 호출 방식은 더 이상 사용하지 않습니다.

## 입력 제한

| 필드 | 형식 |
| --- | --- |
| `email` | 문자열, 최대 254자 |
| 회원가입 `password` | 문자열, 12~128자 |
| 로그인 `password` | 문자열, 1~128자 |
| 이메일 인증 `token` | 문자열, 43자 |
| `return_path` | 선택, 서비스 내부 상대 경로, 최대 256자 |
| `limit` | 정수 1~100, 기본 20 |
| `offset` | 정수 0~10000, 기본 0 |
| `top_k` | 정수 1~10, 기본 5 |
| 분류·조항 검색 `text` | 공백이 아닌 문자열, 최대 2000자. 분류 모델 입력은 최대 256토큰으로 절단 |

## 응답 타입

```ts
type User = {
  id: string;
  status: "ACTIVE";
  provider: "EMAIL" | "KAKAO" | "GOOGLE";
};

type ContractSummary = {
  id: string;
  contract_type: string;
  input_kind: "PDF" | "IMAGES";
  created_at: string;
  updated_at: string;
};

type Contract = ContractSummary & {
  current_file_generation_id: string | null;
  first_uploaded_at: string | null;
};

type File = {
  id: string;
  original_filename: string | null;
  media_type: string;
  size_bytes: number;
};

type Page = {
  id: string;
  file_asset_id: string;
  source_page_number: number;
  page_order: number;
  width: number | null;
  height: number | null;
  coordinate_unit: "PIXEL" | "POINT" | "NORMALIZED" | null;
};

type TextRevision = {
  id: string;
  revision: number;
  kind: "EXTRACTED" | "USER_EDITED";
  content: string;
  blocks: unknown[];
  confirmed_at: string | null;
};

type CheckStatus =
  | "CAUTION"
  | "MISSING_SUSPECTED"
  | "NEEDS_CONFIRMATION"
  | "PRESENT";

type CheckItem = {
  id: string;
  check_code: string;
  labels: unknown[];
  status: CheckStatus;
  quoted_text: string | null;
  explanation: string;
  required_information: unknown[];
  source_locations: unknown[];
  rule_candidate: Record<string, unknown>;
};

type Citation = {
  id: string;
  check_item_id: string;
  law_id: string;
  law_name: string;
  article_id: string;
  article_number: string;
  chunk_id: string;
  content: string;
  effective_date: string | null;
  source_url: string;
  corpus_version: string;
};

type AnalysisResult = {
  id: string;
  input_revision_id: string;
  file_generation_id: string;
  summary: string;
  completed_at: string;
  items: CheckItem[];
  counts: Record<CheckStatus, number>;
  citations: Citation[];
  is_current_generation: boolean;
  is_current_revision: boolean;
};

type ContractDetailResponse = {
  contract: Contract;
  files: File[];
  pages: Page[];
  text: TextRevision | null;
  current_result: AnalysisResult | null;
};
```

## 공통 오류 응답

```ts
type ErrorResponse = {
  error: {
    code: string;
    message: string;
    recovery_action: "REUPLOAD" | "RETRY" | "LOGIN" | "NONE";
    retryable: boolean;
  };
};
```

# OCR 우회 계약서 분석

`POST /api/analysis/contracts/text`는 OCR이 완료되었다고 가정한 페이지별 텍스트를 입력받아 조항 분리, 기존 멀티라벨 분류, `employment_basic_v004` 법령 검색을 순서대로 수행한다. 실제 LLM 판단은 호출하지 않고 조항별 `llm_context`를 반환한다.

```json
{
  "contract_id": "contract-001",
  "pages": [{"page": 1, "text": "제1조(임금)\n임금은 매월 25일 지급한다."}],
  "top_k": 5
}
```

응답의 `input_mode`는 `OCR_BYPASS_TEXT`, 완료 단계는 `OCR_SKIPPED`부터 `RETRIEVAL_COMPLETE`까지 기록된다. `llm_context`에는 조항 원문, 페이지, 분류 라벨, 관련 법령 후보가 포함된다. 필수 조항 누락은 단일 조항 검색으로 판단하지 않고 `document_context.missing_required_review_needed`를 확인하여 계약서 전체 단위 후속 판단에서 처리한다.

