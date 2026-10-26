"""Swagger descriptions and illustrative responses. Contains no runtime credentials."""
from copy import deepcopy

API_DESCRIPTION = """
모든 POST는 `X-CSRF-Token`이 필요합니다. `GET /api/auth/csrf` 응답 값을 입력하세요.
토큰은 10분 유효하며 재발급·비회원 세션 생성·로그인 후에는 최신 값을 사용하세요.
"""

TAGS = [
    {"name": "health", "description": "(상태확인) 서버·DB 연결 확인"},
    {"name": "auth", "description": "(인증) 가입·로그인·비회원 세션"},
    {"name": "contracts", "description": "(계약서) 내 기록 조회·회원 귀속"},
]



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
    "live": docs('서버 상태 확인', """
서버 실행 여부를 확인합니다.

입력 없음. 성공: 200, status=ok.
""", example={"status": "ok"}),
    "ready": docs('DB 연결 확인', """
전용 DB 계정의 연결·조회 가능 여부를 확인합니다.

입력 없음. 성공: 200. 실패: 503.
""", example={"status": "ok"}, errors=(503,)),
    "csrf": docs('CSRF 토큰 발급', """
POST 요청에 사용할 보안 토큰을 발급합니다.

입력 없음. 응답의 csrf_token을 X-CSRF-Token 헤더에 입력하세요.
""", example={"csrf_token": "이 칸에는 실행할 때마다 실제 토큰이 발급됩니다"}, errors=(429,)),
    "guest": docs('비회원 세션 생성', """
비회원 세션을 생성하거나 기존 세션을 재사용합니다.

입력: CSRF 헤더만 필요. 본문 없음.
응답: 비회원 ID·새 csrf_token. 쿠키는 자동 저장됩니다.
""", example={"kind": "GUEST", "guest_session_id": UUID_EXAMPLE, "csrf_token": "응답에서 발급된 새 토큰"},
                  errors=(401, 403, 413, 422, 429, 503)),
    "signup": docs('이메일 회원가입', """
가입과 인증 메일 발송을 접수합니다. SMTP 설정 필요.

입력: CSRF 헤더 + 이메일·비밀번호(12~128자).
```json
{"email":"","password":""}
```
202는 접수 완료입니다. 메일 인증 후 별도 로그인하세요.
""", success=202, example={"message": "가입 가능한 주소라면 인증 메일이 발송됩니다. 메일을 확인해 주세요."},
                   errors=(403, 413, 422, 429, 503), response_description="회원가입/인증 메일 발송 요청 접수"),
    "resend": docs('인증 메일 재발송', """
미인증 계정에 새 링크를 발송하고 이전 링크를 폐기합니다. SMTP 설정 필요.

입력: CSRF 헤더 + 이메일.
```json
{"email":""}
```
계정 존재 여부와 무관하게 202를 반환합니다.
""", success=202, example={"message": "가입 가능한 주소라면 인증 메일이 발송됩니다. 메일을 확인해 주세요."},
                   errors=(403, 413, 422, 429, 503), response_description="인증 메일 재발송 요청 접수"),
    "confirm": docs('이메일 인증 완료', """
메일의 일회성 토큰으로 가입을 확정합니다. 자동 로그인하지 않습니다.

입력: CSRF 헤더 + 메일 링크의 #token= 뒤 43자 문자열.
```json
{"token":""}
```
토큰은 발급 후 24시간 이내 한 번만 사용 가능합니다.
""", example={"verified": True, "login_required": True}, errors=(400, 403, 413, 422, 429, 503)),
    "login": docs('이메일 로그인', """
이메일 인증을 완료한 회원으로 로그인합니다.

입력: CSRF 헤더 + 가입한 이메일·비밀번호.
```json
{"email":"","password":"","claim_contract_id":null}
```
claim_contract_id는 선택입니다. 비회원 결과도 저장하려면 실제 UUID를 입력하세요.
응답: 회원 정보·새 csrf_token·claim_result. saved=false여도 로그인은 성공입니다.
""", example={"user": USER_EXAMPLE, "csrf_token": "로그인 후 발급된 새 토큰", "claim_result": None},
                  errors=(401, 403, 413, 422, 429, 503)),
    "me": docs('내 로그인 정보', """
현재 회원의 ID·상태·가입 제공자를 조회합니다.

입력 없음. 회원 쿠키 자동 전달. 미로그인/비회원은 401.
""", example={"user": USER_EXAMPLE}, errors=(401, 503)),
    "logout": docs('로그아웃', """
현재 회원 세션과 회원·CSRF 쿠키를 정리합니다. 계약서는 삭제하지 않습니다.

입력: CSRF 헤더만 필요. 본문 없음.
응답: 204, 본문 없음. 다음 POST 전 CSRF를 다시 발급하세요.
""", success=204, errors=(403, 413, 422, 503), response_description="로그아웃/쿠키 정리 완료. 응답 본문 없음"),
    "list": docs('내 계약서 목록', """
회원/비회원 본인의 유효한 기록을 최신순으로 조회합니다.

입력: limit(선택, 1~100, 기본 20), offset(선택, 0~10000, 기본 0).
회원/비회원 쿠키 필요. 본문 없음. 응답은 contracts 배열이며 기록이 없으면 빈 배열입니다.
""", example={"contracts": [], "limit": 20, "offset": 0}, errors=(401, 422, 503)),
    "detail": docs('계약서 상세 조회', """
본인 계약서의 파일 정보·페이지·텍스트·저장 결과를 조회합니다.

입력: 목록에서 얻은 contract_id(UUID). 회원/비회원 쿠키 필요. 본문 없음.
응답: contract, files, pages, text, current_result. 없는 텍스트/결과는 null.
is_current_generation/is_current_revision이 false면 이전 입력 기준 결과입니다.
""", errors=(401, 404, 422, 503)),
    "claim": docs('비회원 기록을 회원 계정에 저장', """
비회원의 완료 결과를 현재 회원 계정에 귀속합니다.

입력: contract_id(UUID) + CSRF 헤더. 본문 없음.
회원 쿠키와 원래 비회원 쿠키가 필요하며, 최초 업로드 후 24시간 이내여야 합니다.
응답: saved=true. 같은 회원의 중복 요청은 성공합니다.
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
