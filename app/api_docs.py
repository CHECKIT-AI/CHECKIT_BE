"""Swagger descriptions and illustrative responses. Contains no runtime credentials."""
from copy import deepcopy

API_DESCRIPTION = """
**모든 POST에는 CSRF 토큰이 필요합니다.** 먼저 `GET /api/auth/csrf`를 실행하고
응답의 `csrf_token` 값만 복사해 각 POST의 `X-CSRF-Token` 칸에 넣으세요.
CSRF 토큰은 10분간 유효합니다. `/auth/guest` 또는 `/auth/login` 실행 후에는
그 응답의 **새 csrf_token**을 사용하세요. 다른 브라우저의 토큰은 사용할 수 없습니다.
`/auth/csrf`를 다시 실행하면 이전 컨텍스트를 교체하므로 가장 최근 토큰을 사용하세요.

"""

TAGS = [
    {"name": "health", "description": "(상태확인) 서버 프로세스와 PostgreSQL 연결 상태를 확인합니다. 인증과 CSRF 입력이 필요 없습니다."},
    {"name": "auth", "description": "(인증) CSRF·비회원 세션·이메일 가입/인증·회원 로그인/로그아웃. POST 전 CSRF 발급이 필요합니다."},
    {"name": "contracts", "description": "(계약서) 쿠키로 확인한 본인 기록만 조회합니다. 다른 사람의 ID를 입력해도 접근할 수 없습니다."},
]

POST_INPUT = """
**공통 필수 헤더:** `X-CSRF-Token`에 현재 브라우저에서 발급받은 CSRF 토큰을 입력합니다.
헤더가 없거나 유효하지 않으면 403입니다. 쿠키와 Origin은 같은 브라우저가 자동 전송합니다.
"""

UUID_EXAMPLE = "550e8400-e29b-41d4-a716-446655440000"
USER_EXAMPLE = {"id": UUID_EXAMPLE, "status": "ACTIVE", "provider": "EMAIL"}


def error_response(code, description, message, recovery="NONE", retryable=False):
    return {"description": description, "content": {"application/json": {"example": {"error": {
        "code": code, "message": message, "recovery_action": recovery, "retryable": retryable,
    }}}}}


ERRORS = {
    400: error_response("INVALID_VERIFICATION_TOKEN", "이메일 인증 토큰이 잘못됐거나 만료·사용·폐기된 경우", "인증 링크가 만료됐거나 사용할 수 없습니다."),
    401: error_response("AUTHENTICATION_REQUIRED", "회원/비회원 쿠키가 없거나 잘못됐거나 만료·폐기된 경우", "인증이 필요하거나 세션이 만료됐습니다.", "LOGIN"),
    403: error_response("CSRF_FAILED", "CSRF 토큰 또는 Origin 검증 실패. CSRF를 다시 발급받고 확인하세요.", "보안 토큰을 새로 발급받고 다시 시도해 주세요."),
    404: error_response("CONTRACT_NOT_FOUND", "없는 계약서·타인 기록·만료·삭제 중 기록을 동일한 404로 처리", "접근 가능한 계약서를 찾을 수 없습니다."),
    413: error_response("REQUEST_TOO_LARGE", "인증 POST 본문이 16,384바이트를 초과한 경우", "요청 크기가 너무 큽니다."),
    422: error_response("INVALID_INPUT", "필수 필드 누락, 잘못된 JSON·UUID·이메일·길이·정수 범위 또는 허용하지 않는 JSON 필드", "요청 필드와 형식을 확인하세요."),
    429: error_response("RATE_LIMITED", "요청 또는 비밀번호 계산 동시 처리 제한. 잠시 후 재시도하세요.", "잠시 후 다시 시도해 주세요.", retryable=True),
    503: error_response("DATABASE_UNAVAILABLE", "DB 연결·권한·쿼리 처리 실패", "데이터베이스 요청을 처리할 수 없습니다.", retryable=True),
}


def docs(summary, description, success=200, example=None, errors=(), response_description="정상 처리"):
    response = {"description": response_description}
    if example is not None:
        response["content"] = {"application/json": {"example": example}}
    return {"summary": summary, "description": description,
            "response_description": response_description,
            "responses": {success: response, **{status: deepcopy(ERRORS[status]) for status in errors}}}


ENDPOINTS = {
    "live": docs("서버 실행 상태 확인", """
FastAPI 서버가 요청에 응답하는지 확인합니다. DB 연결은 검사하지 않습니다.

**입력:** path/query/header/body 모두 필요 없습니다. 로그인도 필요 없습니다.
**사용:** Try it out → Execute. 200과 `{"status":"ok"}`가 나오면 서버가 응답 중입니다.
""", example={"status": "ok"}),
    "ready": docs("DB 연결 및 전용 계정 상태 확인", """
PostgreSQL 연결, `checkit_backend` 전용 계정의 권한 수준과 contracts 테이블의 SELECT 실행 가능 여부를 확인합니다.
테스트 데이터를 생성하지 않습니다. 모든 테이블의 저장 권한이나 전체 기능을 검증하는 API는 아닙니다.

**입력:** path/query/header/body 모두 필요 없습니다. 로그인도 필요 없습니다.
**사용:** Try it out → Execute. 200이면 준비 상태 검사 성공, 503이면 DB 설정/권한 확인이 필요합니다.
""", example={"status": "ok"}, errors=(503,)),
    "csrf": docs("변경 요청용 CSRF 토큰 발급", """
회원가입·로그인·로그아웃·비회원 세션 생성·기록 귀속 등 POST 요청에 사용할 보안 토큰을 발급합니다.

**입력:** 직접 입력할 path/query/header/body가 없습니다. 로그인 전에도 호출할 수 있습니다.

**사용 순서**
1. Try it out → Execute.
2. Response body에서 `csrf_token`의 문자열 값만 복사합니다. 큰따옴표는 복사하지 않습니다.
3. 다음 POST의 `X-CSRF-Token` 입력란에 붙여 넣습니다.

브라우저 컨텍스트 쿠키는 자동 저장됩니다. 토큰은 10분간 유효하며, 재발급 시 이전 컨텍스트는 교체됩니다.
비회원 세션 생성·로그인 후에는 해당 응답의 새 토큰을 사용하세요.
""", example={"csrf_token": "이 칸에는 실행할 때마다 실제 토큰이 발급됩니다"}, errors=(429,)),
    "guest": docs("비회원 이용을 위한 세션 생성", POST_INPUT + """
같은 브라우저의 비회원 계약서 접근을 식별합니다. 유효한 비회원 쿠키가 있으면 기존 세션을 재사용합니다.

**입력:** 필수 CSRF 헤더만 필요합니다. path/query/Request body는 없습니다. `{}`도 입력할 필요 없습니다.

**사용:** `/auth/csrf` 실행 → CSRF 헤더 입력 → Execute.
응답의 `guest_session_id`는 식별자이고 접근 비밀번호가 아닙니다. 이후 API에 직접 넣지 않습니다.
실제 비회원 토큰은 HttpOnly 쿠키로 자동 전달됩니다. 응답의 새 `csrf_token`을 다음 POST에 사용하세요.

비회원 쿠키의 기본 보관은 30일이지만 **계약서 보관은 최초 업로드 후 24시간**입니다.
이미 회원 로그인 중이면 409입니다. 잘못된 회원 쿠키가 남아 있으면 401이므로 로그아웃 후 다시 시도하세요.
""", example={"kind": "GUEST", "guest_session_id": UUID_EXAMPLE, "csrf_token": "응답에서 발급된 새 토큰"},
                  errors=(401, 403, 413, 422, 429, 503)),
    "signup": docs("이메일 회원가입 신청 및 인증 메일 발송 접수", POST_INPUT + """
이메일과 비밀번호로 인증 대기 계정을 만들고 인증 메일 발송을 예약합니다.
**SMTP 및 이메일 확인 화면 주소 설정이 필요합니다. 설정이 없으면 503 EMAIL_NOT_CONFIGURED입니다.**

| Request body 필드 | 필수 | 형식·입력 방법 |
| --- | --- | --- |
| email | 예 | 이메일 문자열, 최대 254자. 앞뒤 공백 제거·소문자로 정규화 |
| password | 예 | 직접 정한 12~128자 문자열. DB 관리자/백엔드 계정 비밀번호가 아닌 서비스 회원용 비밀번호 |

```json
{"email":"","password":""}
```

빈 문자열에 실제 수신 가능한 이메일과 사용할 비밀번호를 채웁니다. path/query 입력은 없습니다.
202는 접수 응답이며 실제 메일 수신·가입 인증·로그인 완료를 뜻하지 않습니다.
기존 계정 여부와 관계없이 같은 접수 메시지를 반환합니다. 기존 계정 비밀번호는 변경하지 않습니다.
메일 인증 링크는 24시간 유효합니다. 인증 후 `/auth/login`을 별도로 호출해야 합니다.
""", success=202, example={"message": "가입 가능한 주소라면 인증 메일이 발송됩니다. 메일을 확인해 주세요."},
                   errors=(403, 413, 422, 429, 503), response_description="회원가입/인증 메일 발송 요청 접수"),
    "resend": docs("이메일 가입 인증 메일 재발송 접수", POST_INPUT + """
가입 신청 후 아직 인증하지 않은 이메일에 새 인증 링크를 발송합니다.
새 링크를 발급하면 해당 계정의 이전 미사용 인증 토큰은 폐기합니다.

**Request body:** `email` 필수. 최대 254자의 이메일 문자열을 넣습니다. path/query 입력은 없습니다.

```json
{"email":""}
```

미가입·이미 인증 완료 계정에도 동일한 202 메시지를 반환하지만 실제 메일은 보내지 않습니다.
SMTP 미설정 시 503 EMAIL_NOT_CONFIGURED입니다. 202는 메일 수신 성공을 보장하지 않습니다.
""", success=202, example={"message": "가입 가능한 주소라면 인증 메일이 발송됩니다. 메일을 확인해 주세요."},
                   errors=(403, 413, 422, 429, 503), response_description="인증 메일 재발송 요청 접수"),
    "confirm": docs("메일의 일회성 토큰으로 가입 인증 완료", POST_INPUT + """
인증 메일의 토큰을 확인해 계정을 ACTIVE로 바꿉니다. **자동 로그인은 하지 않습니다.**

**Request body:** `token` 필수. 메일 링크의 `#token=` 뒤에 있는 **실제 43자 문자열**만 입력합니다.
링크 전체, CSRF 토큰, DB 비밀번호를 넣지 않습니다. path/query 입력은 없습니다.

```json
{"token":""}
```

빈 문자열에 실제 메일 토큰을 채우세요.
미사용·미폐기·24시간 이내 토큰만 허용하며 한 번 사용하면 재사용할 수 없습니다.
잘못된/만료된/사용된/폐기된 토큰은 400입니다. 필드 누락이나 43자가 아닌 입력은 422입니다.
200 응답 후 `/auth/login`을 실행합니다.
""", example={"verified": True, "login_required": True}, errors=(400, 403, 413, 422, 429, 503)),
    "login": docs("이메일 로그인 및 선택한 비회원 기록 저장", POST_INPUT + """
이메일 가입 인증을 완료한 계정으로 로그인합니다. 세션 쿠키를 새로 발급합니다.

| Request body 필드 | 필수 | 형식·입력 방법 |
| --- | --- | --- |
| email | 예 | 가입한 이메일 문자열, 최대 254자 |
| password | 예 | 가입 시 정한 비밀번호 문자열, 최대 128자 |
| claim_contract_id | 아니오 | 로그인하며 저장할 비회원 계약서의 실제 UUID. 일반 로그인은 필드를 삭제하거나 null 입력 |

**일반 로그인 예시**
```json
{"email":"","password":""}
```

**비회원 결과도 저장하는 예시**
```json
{"email":"","password":"","claim_contract_id":null}
```
이메일과 비밀번호를 채우고, 기록도 저장하려면 claim_contract_id의 null을 실제 계약서 UUID 문자열로 바꿉니다.
path/query 입력은 없습니다. 기존 비회원 쿠키는 같은 브라우저가 자동 전송합니다.

**응답:** user는 로그인 계정, csrf_token은 다음 POST에 쓸 새 값입니다.
claim_result가 null이면 귀속을 요청하지 않은 상태입니다. saved=true이면 저장 성공,
saved=false이면 **로그인은 성공했지만 해당 기록 저장은 실패**한 상태입니다.
로그인만으로 모든 비회원 기록을 가져오지 않습니다. 세션 기본 유효 기간은 7일입니다.

잘못된 이메일/비밀번호는 401 INVALID_CREDENTIALS, 비밀번호는 맞지만 가입 미인증이면
403 EMAIL_VERIFICATION_REQUIRED입니다. 로그인 성공 후 `/auth/me`로 확인하세요.
""", example={"user": USER_EXAMPLE, "csrf_token": "로그인 후 발급된 새 토큰", "claim_result": None},
                  errors=(401, 403, 413, 422, 429, 503)),
    "me": docs("현재 로그인한 회원 정보 확인", """
현재 브라우저의 회원 세션 쿠키로 로그인 상태를 확인합니다.

**입력:** path/query/header/body에 직접 넣을 값이 없습니다. `/auth/login` 성공 후 같은 브라우저에서 실행합니다.
회원 쿠키는 자동 전송됩니다. CSRF 헤더가 필요 없습니다.

**응답:** user.id는 회원 UUID, status는 ACTIVE, provider는 가입 제공자입니다.
현재 공개 로그인 API는 이메일 방식만 구현되어 있습니다.
로그인하지 않았거나 세션이 만료·폐기되면 401입니다. 비회원 세션만 있는 경우도 401이 정상입니다.
""", example={"user": USER_EXAMPLE}, errors=(401, 503)),
    "logout": docs("현재 브라우저의 회원 로그아웃", POST_INPUT + """
현재 회원 세션을 DB에서 폐기하고 회원·CSRF 쿠키를 제거합니다. 다른 기기의 회원 세션은 유지합니다.

**입력:** 필수 CSRF 헤더만 필요합니다. path/query/Request body는 없습니다.
로그인 응답에서 받은 최신 CSRF 토큰을 넣고 실행하세요. 유효한 회원 세션이 없어도 CSRF가 맞으면 쿠키를 정리합니다.

**성공:** 204 No Content. Response body가 없는 것이 정상입니다.
이후 `/auth/me`는 401입니다. 다음 POST 전에는 `/auth/csrf`를 다시 실행하세요.
기존 비회원 쿠키와 계약서 데이터는 삭제하지 않습니다.
""", success=204, errors=(403, 413, 422, 503), response_description="로그아웃/쿠키 정리 완료. 응답 본문 없음"),
    "list": docs("내 계약서 기록 목록 조회", """
회원 로그인 또는 비회원 세션 쿠키로 본인이 접근할 수 있는 계약서 목록을 조회합니다.
회원 로그인 중에는 해당 회원의 기록만 조회하며 미귀속 비회원 기록을 합치지 않습니다.

| Query 파라미터 | 필수 | 형식·범위 | 기본값 |
| --- | --- | --- | --- |
| limit | 아니오 | 정수 1~100. 한 번에 받을 개수 | 20 |
| offset | 아니오 | 정수 0~10000. 앞에서 건너뛸 개수 | 0 |

**사용 예:** 첫 20개는 limit=20, offset=0. 다음 20개는 limit=20, offset=20.
path/header/Request body 입력은 없습니다. CSRF 헤더가 필요 없습니다.
먼저 `/auth/guest` 또는 `/auth/login`을 실행해야 합니다.

**응답:** contracts는 기록 배열, limit/offset은 사용한 조회 옵션입니다.
각 기록은 id·계약서 종류·입력 방식·생성/수정 시각·expires_at을 포함합니다.
최신 생성 순이며 회원 expires_at은 null, 비회원은 보관 기한입니다.
만료·삭제 중 기록은 제외합니다. `contracts: []`는 접근 가능한 기록이 없다는 정상 응답입니다.
이 API는 새 계약서를 생성하거나 AI 분석을 실행하지 않습니다.
""", example={"contracts": [], "limit": 20, "offset": 0}, errors=(401, 422, 503)),
    "detail": docs("내 계약서의 원본 정보·텍스트·분석 결과 조회", """
기록 목록에서 선택한 계약서의 저장된 내용을 조회합니다. 회원/비회원 쿠키가 필요합니다.

**Path 파라미터:** `contract_id` 필수. `/contracts` 응답의 `contracts[].id`에 있는 실제 UUID를 입력합니다.
형식 예: `550e8400-e29b-41d4-a716-446655440000`. 이 예시 자체는 실제 기록이 아닙니다.
query/header/Request body 입력은 없습니다. CSRF 헤더가 필요 없습니다.

| 응답 필드 | 의미 |
| --- | --- |
| contract | 계약서 ID·종류·입력 방식·현재 파일 묶음 ID·첫 업로드/만료/생성/수정 시각 |
| files | 현재 파일 묶음의 원본 ID·원래 파일명·형식·바이트 수. 파일 바이너리는 반환하지 않음 |
| pages | 원본 파일별 페이지 번호·사용자 확정 순서·크기/좌표 단위 |
| text | 현재 파일 묶음의 최신 추출/수정 텍스트. 없으면 null |
| current_result | 저장된 분석 결과. 없으면 null |

current_result가 있으면 요약(summary), 점검 항목(items), 상태별 건수(counts), 법령 인용(citations)을 포함합니다.
is_current_generation과 is_current_revision은 결과가 현재 파일 묶음/최신 텍스트 기준인지 표시합니다.
false이면 이전 입력 기준 결과이므로 현재 내용의 새 결과처럼 표시하지 않습니다.

없는 ID·타인 소유·만료·삭제 중 기록은 모두 404입니다. UUID 형식이 아니면 422입니다.
조회만 수행하며 업로드·원본 다운로드·텍스트 수정·새 분석을 실행하지 않습니다.
""", errors=(401, 404, 422, 503)),
    "claim": docs("내 비회원 분석 결과를 로그인 계정에 저장", POST_INPUT + """
비회원으로 만든 **완료된 분석 결과**를 현재 로그인한 회원에게 귀속합니다.
복사본을 만들지 않고 기존 계약서의 소유자를 전환합니다.

**Path 파라미터:** `contract_id` 필수. 저장할 비회원 계약서의 실제 UUID입니다.
`/contracts`에서 확인한 ID를 사용합니다. query/Request body 입력은 없습니다.

**필요한 쿠키:** 현재 회원 로그인 쿠키 + 해당 계약서를 만든 비회원 쿠키. 같은 브라우저가 자동 전송합니다.
Swagger에서 user_id나 guest_session_id를 직접 넣지 않습니다.

**사용 순서:** 비회원으로 완료 결과 생성 → 같은 브라우저에서 로그인 → 최신 CSRF와 계약서 ID 입력 → Execute.
로그인의 claim_contract_id로 이미 저장했다면 별도로 호출할 필요가 없습니다.

성공하면 saved=true이며 회원 소유로 바꾸고 비회원 소유·만료 시각을 해제합니다.
같은 회원이 이미 소유한 기록을 다시 요청해도 성공합니다. 다른 회원의 기록은 가져올 수 없습니다.
처음 귀속할 기록은 유효한 비회원 소유·첫 업로드 후 24시간 이내·삭제 중이 아님·완료 결과 존재가 필요합니다.
회원 인증 실패는 401, 권한 없음·만료·완료 결과 없음 등은 404입니다.
현재 업로드/분석 API는 미구현이므로 Swagger만으로 새 완료 결과를 만들 수는 없습니다.
""", example={"contract_id": UUID_EXAMPLE, "saved": True}, errors=(401, 403, 404, 422, 503)),
}

# Route-specific error meanings that differ from the shared defaults.
ENDPOINTS["guest"]["responses"][409] = error_response(
    "ALREADY_AUTHENTICATED", "회원 로그인 상태에서 비회원 세션 생성을 요청한 경우", "이미 회원으로 로그인되어 있습니다.")
ENDPOINTS["login"]["responses"][401] = error_response(
    "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 일치하지 않는 경우", "이메일 또는 비밀번호를 확인하세요.")
ENDPOINTS["login"]["responses"][403]["description"] += " 비밀번호는 맞지만 이메일 미인증이면 EMAIL_VERIFICATION_REQUIRED입니다."
for name in ("signup", "resend"):
    ENDPOINTS[name]["responses"][503]["description"] += " SMTP 또는 인증 화면 주소 미설정이면 EMAIL_NOT_CONFIGURED입니다."
    content = ENDPOINTS[name]["responses"][503]["content"]["application/json"]
    database_example = content.pop("example")
    content["examples"] = {
        "email_not_configured": {"summary": "메일 발송 설정이 없는 경우", "value": {"error": {
            "code": "EMAIL_NOT_CONFIGURED", "message": "이메일 인증 발송 설정이 필요합니다.",
            "recovery_action": "NONE", "retryable": False,
        }}},
        "database_unavailable": {"summary": "DB 요청 실패", "value": database_example},
    }

ENDPOINTS["signup"]["responses"][422]["description"] += " 비밀번호가 12자 미만이면 PASSWORD_POLICY입니다."
ENDPOINTS["detail"]["responses"][200]["content"] = {"application/json": {"example": {
    "contract": {
        "id": UUID_EXAMPLE, "contract_type": "EMPLOYMENT", "input_kind": "PDF",
        "current_file_generation_id": None, "first_uploaded_at": None, "expires_at": None,
        "created_at": "2026-10-26T00:00:00Z", "updated_at": "2026-10-26T00:00:00Z",
    },
    "files": [], "pages": [], "text": None, "current_result": None,
}}}
