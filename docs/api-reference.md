# 회원 전용 백엔드 API 명세

> 2026-11-08 현재 실제 구현 기준입니다. 계약서 업로드·OCR·AI 분석·취소·원본 다운로드·삭제 API는 아직 구현되지 않았습니다.

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
| 내 계약서 목록 | GET | `/api/contracts` | Query: `limit=20&offset=0` | `200` · `{"contracts":ContractSummary[],"limit":20,"offset":0}` |
| 계약서 상세 조회 | GET | `/api/contracts/{contract_id}` | Path: `contract_id` UUID | `200` · `ContractDetailResponse` |
| 관련 법령 검색 | POST | `/api/rag/search` | 일반 검색 또는 조항 검색 입력 | `200` · 검색 corpus·결과·경고 |

`provider`는 `kakao` 또는 `google`입니다. 소셜 로그인 콜백은 프론트에서 직접 호출하지 않고 제공자가 브라우저를 이동시킵니다.

RAG 검색은 다음 두 입력 중 하나만 사용합니다.

```json
{"query":"검색 문장","top_k":5}
```

```json
{"clause_id":"clause_007","labels":["임금"],"text":"해당 조항 원문","top_k":5}
```

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

