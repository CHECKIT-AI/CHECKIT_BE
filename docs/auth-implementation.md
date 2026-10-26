# 인증·소유권 구현 현황 · 2026-10-26

기존 설계에 맞춰 이메일 인증·로그인, 비회원 세션, 계약서 접근 검사와 계정 귀속을 구현했습니다. DB 테이블·기존 RLS 정책은 변경하지 않았으며 초기 SQL을 실행하지 않았습니다. 아래 경로는 `/api` 기준입니다.

## 구현 API

| 메서드 | 경로 | 동작 |
| --- | --- | --- |
| GET | /auth/csrf | 브라우저 컨텍스트·현재 회원/비회원 쿠키에 결합한 CSRF 토큰 발급 |
| POST | /auth/guest | 비회원 세션 생성 또는 유효한 기존 세션 재사용 |
| POST | /auth/signup | 이메일 회원가입 접수, SMTP 인증 메일 예약. 202 |
| POST | /auth/email-verification/resend | 미인증 계정의 인증 메일 재발송. 이전 미사용 토큰 폐기 |
| POST | /auth/email-verification/confirm | 일회성 이메일 인증. 자동 로그인하지 않음 |
| POST | /auth/login | 이메일 로그인, 새 세션과 CSRF 발급, 선택한 비회원 결과 귀속 |
| GET | /auth/me | 유효한 회원 세션의 ID·상태·제공자 |
| POST | /auth/logout | 현재 회원 세션 폐기, 회원·CSRF 쿠키 제거 |
| GET | /contracts | 현재 회원 또는 비회원 소유의 유효한 기록 목록 |
| GET | /contracts/{id} | 소유권 확인 후 파일 메타데이터·페이지·텍스트·현재 결과·인용 조회 |
| POST | /contracts/{id}/claim | 회원과 기존 비회원 권한 확인 후 완료 결과 귀속 |

계약서 생성·업로드·분석·취소·원본 다운로드·삭제 API는 아직 구현하지 않았습니다. 소유권 검사는 이 API들을 추가할 때도 `app/access.py`의 공통 검사를 거치도록 적용해야 합니다. 카카오·구글 OAuth 경로는 아직 없으며 제공자 앱 설정 후 별도 구현합니다. 서로 다른 제공자의 계정을 연결하지 않습니다.

## 쿠키·세션

- 원문 세션 토큰은 32바이트 난수이고 HttpOnly·SameSite=Lax 쿠키에만 넣습니다. 로그인·비회원 응답 JSON에 세션 토큰은 넣지 않습니다. DB에는 SHA-256 해시만 저장합니다.
- 회원 세션은 기본 7일 고정 만료입니다. 매 요청에서 활성 회원·미폐기 세션·만료를 검사합니다. 로그인 시 현재 브라우저의 기존 회원 세션을 폐기하고 새로 발급합니다.
- 비회원 쿠키는 30일 동안 브라우저 접근 수단을 유지합니다. **계약서 보관 기한은 여전히 최초 업로드 후 24시간**입니다. 쿠키 수명으로 계약서 기한을 늘리지 않습니다. 비회원 세션 행의 만료·자동 정리 정책은 별도입니다.
- 기본 개발 쿠키 이름은 checkit_session / checkit_guest / checkit_csrf입니다. Secure 사용 시 모두 `__Host-` 접두사가 붙고 Domain은 지정하지 않습니다.
- 잘못된 회원 쿠키를 비회원 신원으로 자동 대체하지 않습니다. `/auth/logout`으로 정리한 뒤 새 CSRF를 발급받을 수 있습니다. 로그아웃 후에도 기존 비회원 쿠키는 유지합니다.
- 비밀번호는 scrypt(N=131072,r=8,p=1)와 개별 salt로 저장합니다. 가입 비밀번호는 12~128자이며 다른 해시 형식의 기존 계정은 지원하지 않습니다. 암호 계산은 프로세스당 동시 2개로 제한합니다.

## CSRF·프론트엔드 호출

1. 프론트에서 `GET /api/auth/csrf`를 credentials: include로 호출합니다.
2. 응답의 csrf_token을 메모리에 보관합니다. 서버의 컨텍스트 쿠키는 HttpOnly입니다.
3. POST 요청에 `X-CSRF-Token` 헤더를 넣고 credentials: include를 사용합니다. 서버는 허용 Origin도 검사합니다. curl 등 수동 클라이언트는 Origin 헤더와 쿠키 저장소도 필요합니다.
4. 비회원 분석 전 `/auth/guest`를 호출합니다. 반환된 새 csrf_token으로 이후 요청을 보냅니다.
5. 로그인 성공 시에도 반환된 새 csrf_token으로 교체합니다. 인증 전 CSRF는 로그인 후 사용할 수 없습니다.
6. CSRF가 10분 후 만료되거나 서버가 재시작되면 `/auth/csrf`로 다시 받습니다. 회원 로그인 세션은 DB의 별도 기한을 따릅니다.

예시 공통 호출 함수(프론트엔드 코드):

```javascript
const base = "http://127.0.0.1:8000/api";
let csrfToken;
async function initializeCsrf() {
  const response = await fetch(`${base}/auth/csrf`, { credentials: "include" });
  if (!response.ok) throw new Error("CSRF 초기화 실패");
  csrfToken = (await response.json()).csrf_token;
}
async function post(path, body) {
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });
  if (response.status === 204) return;
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message ?? "요청 실패");
  if (data.csrf_token) csrfToken = data.csrf_token;
  return data;
}
```

프론트가 별도 포트에서 실행된다면 해당 정확한 origin을 CHECKIT_ALLOWED_ORIGINS에 추가합니다. 예: `["http://127.0.0.1:8000","http://localhost:5173"]`. 브라우저의 Origin은 직접 조작하지 않습니다. localhost와 127.0.0.1을 혼용하면 쿠키가 공유되지 않으므로 프론트·API의 호스트 표기를 통일합니다. 인증 응답과 계약서 응답은 Cache-Control: no-store입니다.

## 회원가입 메일 설정

Swagger는 서버 재시작 후 `http://127.0.0.1:8000/docs`에서 사용합니다. 먼저 GET /auth/csrf를 Execute하고, 응답의 csrf_token을 각 POST의 X-CSRF-Token 입력란에 붙여 넣습니다. 브라우저 쿠키는 자동으로 전달됩니다. POST /auth/guest 또는 /auth/login 실행 후에는 해당 응답의 새 csrf_token을 사용합니다. 로그인 전 GET /auth/me의 401은 정상이며, SMTP 미설정 시 signup/resend는 503입니다. 계약서 업로드 API가 아직 없으므로 새 비회원의 기록 목록은 빈 배열일 수 있습니다. Swagger 화면의 호스트 표기를 바꾸지 말고 같은 주소를 계속 사용하세요.

현재 `.env`의 DB 설정은 유지합니다. 실제 메일 가입을 사용할 때만 `.env.example`의 다음 항목을 로컬 `.env`에 추가합니다.

| 설정 | 의미 |
| --- | --- |
| CHECKIT_SMTP_HOST | 사용할 메일 서비스 SMTP 호스트 |
| CHECKIT_SMTP_PORT | STARTTLS 포트. 기본 587 |
| CHECKIT_SMTP_USERNAME | 메일 서비스 인증 사용자명 |
| CHECKIT_SMTP_PASSWORD | 메일 서비스 SMTP 인증 비밀번호·앱 비밀번호 |
| CHECKIT_SMTP_FROM | 발신 인증을 완료한 이메일 주소 |
| CHECKIT_VERIFICATION_PAGE_URL | 프론트엔드 이메일 확인 화면 주소. 쿼리·fragment 없는 고정 주소 |

SMTP 공급자와 인증 화면을 아직 연결하지 않았으므로 실제 이메일 발송 검증은 하지 않았습니다. 설정이 없으면 signup/resend는 공통 EMAIL_NOT_CONFIGURED(503)를 반환합니다. 메일 토큰을 JSON·로그에 노출하는 개발 우회는 없습니다.

메일 링크는 `설정한화면#token=...` 형태입니다. 프론트는 fragment를 읽고 주소에서 제거한 다음, 사용자 확인 후 `/auth/email-verification/confirm`에 `{token}`을 POST해야 합니다. 자동 GET 방문은 인증을 완료하지 않습니다. 프론트 인증 화면은 후속 구현 대상입니다. 인증 성공 후 이메일·비밀번호로 로그인합니다.

가입·재발송 응답은 계정 존재 여부와 무관하게 동일한 202 메시지입니다. 메일 전송은 커밋 후 백그라운드에서 실행하고 실패 시 비밀값 없는 경고만 기록합니다. 프로세스 종료·SMTP 장애 시 미전송될 수 있으므로 재발송을 지원합니다. 영속 메일 큐와 자동 재시도는 아직 없습니다.

## 소유권·계정 귀속

회원의 인증된 user_id 또는 비회원의 검증된 guest_session_id로 조회 조건을 구성합니다. 클라이언트가 보낸 user_id·세션 ID를 신뢰하지 않습니다. 접근 불가·타인 소유·만료·삭제 중 기록은 동일한 CONTRACT_NOT_FOUND(404)로 응답하며 목록에서도 제외합니다. 비회원의 만료된 파일·데이터 자동 삭제는 여전히 후속 구현입니다.

claim은 계약서 행 잠금 후 원래 비회원 소유권·삭제 상태·현재 시각의 만료·완료 결과 존재를 확인합니다. 소유권만 전환하고 원본·결과를 복사하지 않습니다. 기존 DB 트리거가 비회원 소유와 만료 시각을 해제합니다. 동일 회원의 중복 claim은 성공을 반환합니다. 다른 회원에게 이미 귀속된 기록은 넘겨주지 않습니다.

로그인에 claim_contract_id를 보내면 해당 계약서 하나만 귀속을 시도합니다. 로그인 성공과 귀속 실패는 분리하며 claim_result.saved를 확인합니다. 자동으로 다른 비회원 기록 전체를 가져오지 않습니다.

DB 커밋은 HTTP 응답을 보내기 전에 완료합니다. 따라서 세션 DB 저장이 실패했는데 성공 쿠키만 전달되는 상황을 막습니다.

## 실행·검증

기존 서버를 Ctrl+C로 종료한 후 다시 실행하면 새 경로가 반영됩니다.

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/bin/python -m pytest -q
```

로컬 테스트는 실제 DB·SMTP에 연결하지 않습니다. 별도로 추가한 실제 DB 테스트 4개는 기본적으로 건너뜁니다. 기존 스키마와 전용 계정을 사용하는 전체 롤백 테스트이며 초기 SQL·권한 SQL을 실행하지 않습니다.

```bash
CHECKIT_RUN_DB_TESTS=1 .venv/bin/python -m pytest tests/test_auth_database.py -q
```

실제 DB 테스트는 공유 DB와 통신하므로 테스트 가능한 환경에서 명시적으로 실행합니다. 테스트 종료 시 데이터는 롤백됩니다. 실제 이메일 수신·프론트 인증 화면·카카오/구글 로그인은 이 검증에 포함하지 않습니다.

이번 검증 결과: 로컬 보안·API 테스트 27개 통과, 별도 Supabase 통합 테스트 4개 통과. 통합 테스트는 실제 DB에서 회원가입·미인증 로그인 거부·인증 토큰 교체/일회성·로그인/로그아웃·세션 만료·타인 기록 차단·비회원 만료·회원 귀속/중복 요청을 검증했습니다. 메일 발송은 대체 함수로 검증했으며 테스트 데이터는 모두 롤백했습니다. 실제 SMTP 발송은 아직 확인하지 않았습니다.

## 배포 전 설정

현재는 단일 프로세스 개발 실행 기준입니다. 요청 제한은 원본 소켓 IP와 이메일 해시를 기준으로 한 프로세스 메모리 방식입니다. 복수 worker·서버 배포 전 공유 요청 제한 저장소와 신뢰할 프록시의 IP 전달 정책을 구성해야 합니다. 메모리 제한은 재시작 시 초기화됩니다.

운영은 CHECKIT_ENVIRONMENT=production, CHECKIT_COOKIE_SECURE=true, 명시적인 HTTPS origins, 32자 이상 난수 CHECKIT_CSRF_SECRET가 필요합니다. 개발에서 CSRF secret이 비어 있으면 메모리에서 난수를 만들며 재시작 후 새 CSRF를 발급받아야 합니다. 비밀번호·키는 채팅이나 로그에 출력하지 않습니다.

구현 참고: [OWASP 비밀번호 저장](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html), [FastAPI 응답 전 의존성 종료](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/).
