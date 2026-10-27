# 카카오·구글 로그인 초기 설정

OAuth 시작·콜백 API와 개발용 테스트 화면을 구현했습니다. 개발자 앱의 키·시크릿·Redirect URI를 설정한 뒤 실제 로그인할 수 있습니다. 실제 제공자 로그인 성공은 사용자 계정으로 확인해야 합니다. DB 초기 SQL·계정 생성 스크립트는 다시 실행하지 않습니다.

## 빠른 테스트

```bash
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

서버가 켜져 있다면 종료 후 재시작합니다. [개발용 로그인 화면](http://localhost:8000/api/auth/oauth/test)을 열고 카카오/구글 로그인 버튼을 누릅니다. 동의 완료 후 테스트 화면의 회원 정보에서 `provider: KAKAO` 또는 `GOOGLE`을 확인하세요. 세션 쿠키는 자동 전달됩니다. 처음 로그인한 제공자 계정은 DB에 실제 회원으로 생성됩니다.

프론트가 아직 없어도 테스트 가능합니다. CHECKIT_OAUTH_FRONTEND_COMPLETE_URL이 비어 있으면 개발 모드에서 `/api/auth/oauth/complete`를 사용합니다. 구글 테스트 사용자 제한·카카오 앱 멤버 제한이 적용되는 경우 해당 콘솔에서 테스트 계정을 허용해야 합니다.

이 테스트 화면은 개발 모드에서만 제공하며 운영에서는 404입니다.

## 1. 등록할 주소

개발 시 백엔드는 `http://localhost:8000`을 기준으로 합니다.

| 구분 | 개발자 콘솔에 등록할 Redirect URI |
| --- | --- |
| 카카오 | `http://localhost:8000/api/auth/oauth/kakao/callback` |
| 구글 | `http://localhost:8000/api/auth/oauth/google/callback` |

주소·포트·경로·끝의 슬래시까지 요청과 등록 값이 일치해야 합니다. `.env`의 Redirect URI도 같은 값이어야 합니다. 콜백은 프론트 화면이 아니라 백엔드 주소입니다. 프론트 로그인 완료 화면은 별도이며 현재 주소 미정입니다.

테스트할 때 Swagger·API도 `http://localhost:8000/docs`로 열어 호스트를 통일합니다. 다른 팀원도 같은 URI를 사용하면 각자 실행 중인 로컬 서버로 돌아옵니다. 배포 주소는 결정 후 콘솔과 서버 설정에 별도 반영합니다.

## 2. 카카오 개발자 앱 등록

1. [Kakao Developers](https://developers.kakao.com/)에 카카오계정으로 로그인하고 개발자 가입을 완료합니다.
2. 앱 관리에서 앱을 생성합니다. 이름은 `CheckIt 개발` 등 식별 가능한 이름을 사용하고 소유자 정보를 입력합니다.
3. **카카오 로그인 → 사용 설정**에서 상태를 ON으로 설정합니다.
4. **앱 → 플랫폼 키 → REST API 키**에서 사용할 REST API 키를 확인하고 위 카카오 Redirect URI를 등록합니다.
5. 같은 REST API 키 설정의 **클라이언트 시크릿**을 확인합니다. 공식 문서 기준 새 REST API 키는 시크릿 기능이 기본 활성화되므로 활성 상태를 유지하고 백엔드 `.env`에 저장합니다.
6. 일반 REST 사용자 정보 조회 방식으로 먼저 연결할 계획입니다. OpenID Connect는 이 단계에서 켜지 않아도 됩니다. 닉네임·사진·이메일은 현재 서비스 식별의 필수 항목으로 요구하지 않습니다. 추후 사용 목적이 생길 때 동의항목을 검토합니다.

| 환경변수 | 넣을 값 |
| --- | --- |
| CHECKIT_KAKAO_REST_API_KEY | 앱의 REST API 키. JavaScript 키·네이티브 키·어드민 키가 아님 |
| CHECKIT_KAKAO_CLIENT_SECRET | 위 REST API 키에 연결된 클라이언트 시크릿 |
| CHECKIT_KAKAO_REDIRECT_URI | 표의 카카오 콜백 주소 |

팀원 테스트 범위·앱 유형별 사용 제한이 있다면 콘솔에서 멤버/테스트 계정 설정을 확인합니다. 카카오는 최소 정보 요청으로 고유 사용자 ID만 조회하며 이메일 없이 독립 계정을 생성합니다.

## 3. 구글 개발자 앱 등록

1. [Google Cloud Console](https://console.cloud.google.com/)에 로그인하고 개발용 프로젝트를 생성하거나 팀의 기존 프로젝트를 선택합니다.
2. **Google Auth Platform**을 열고 초기 설정을 진행합니다. 앱 이름은 `CheckIt`, 지원 이메일·개발자 연락처는 팀이 확인할 수 있는 주소를 사용합니다.
3. **Audience(대상)**는 일반 Google 계정으로 개발할 경우 External(외부)로 설정합니다. 조직 내부 전용인 경우에만 해당 조직의 Internal 조건을 검토합니다.
4. 콘솔에서 테스트 사용자 목록을 사용하는 경우, 로그인 테스트에 쓸 본인·팀원 Google 계정을 추가합니다. 앱 공개·검증 신청은 이번 로컬 초기 설정 단계에서 진행하지 않습니다.
5. **Data Access(데이터 액세스)**에서는 로그인에 사용할 기본 범위 `openid`, `email`, `profile`을 확인합니다. Drive·Gmail 등 추가 API 권한은 요청하지 않습니다.
6. **Clients(클라이언트) → Create client**에서 앱 유형을 **Web application(웹 애플리케이션)**으로 선택합니다. 이름 예: `CheckIt Local Backend`.
7. **Authorized redirect URIs(승인된 리디렉션 URI)**에 위 구글 콜백 주소를 추가합니다. 서버 인가 코드 방식이므로 JavaScript SDK용 Origin 등록과 혼동하지 않습니다. 프론트 주소는 아직 미정이며, Google JS SDK를 사용할 경우 Origin은 추후 별도 설정합니다.
8. 생성된 Client ID와 Client Secret을 백엔드 `.env`에 저장합니다. 서비스 계정 키가 아니라 OAuth 웹 클라이언트 정보가 필요합니다.

| 환경변수 | 넣을 값 |
| --- | --- |
| CHECKIT_GOOGLE_CLIENT_ID | 웹 애플리케이션 OAuth Client ID |
| CHECKIT_GOOGLE_CLIENT_SECRET | 해당 클라이언트의 Client Secret |
| CHECKIT_GOOGLE_REDIRECT_URI | 표의 구글 콜백 주소 |

## 4. 백엔드 `.env`

기존 DB 설정은 유지하고 다음 항목을 채웁니다. 키·시크릿은 채팅이나 GitHub에 공유하지 않습니다.

```dotenv
CHECKIT_KAKAO_REST_API_KEY=
CHECKIT_KAKAO_CLIENT_SECRET=
CHECKIT_KAKAO_REDIRECT_URI=http://localhost:8000/api/auth/oauth/kakao/callback

CHECKIT_GOOGLE_CLIENT_ID=
CHECKIT_GOOGLE_CLIENT_SECRET=
CHECKIT_GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/oauth/google/callback

# 프론트 주소·완료 페이지 확정 후 입력. 지금은 빈 값 유지.
CHECKIT_OAUTH_FRONTEND_COMPLETE_URL=
```

기본 개발 설정의 허용 Origin에는 localhost:8000이 이미 포함되어 있습니다. 프론트 주소 확정 후 CHECKIT_ALLOWED_ORIGINS에도 정확한 프론트 Origin을 추가합니다. 설정 변경 후 서버를 재시작합니다.

키 준비 여부는 다음 명령으로 확인할 수 있습니다. 값은 출력하지 않으며, 실제 제공자 접속·인증 유효성을 검증하지 않습니다.

```bash
.venv/bin/python -m scripts.check_oauth_config
```

## 5. 구현된 경로와 프론트 연결

| 메서드 | 경로 | 입력 | 응답 |
| --- | --- | --- | --- |
| POST | `/api/auth/oauth/{provider}/start` | provider=kakao/google, CSRF 헤더, `{ "return_path": "/", "claim_contract_id": null }` | `{ "authorization_url": "..." }` |
| GET | `/api/auth/oauth/{provider}/callback` | 제공자가 전달하는 code/state 또는 error | 완료 화면으로 303 이동 |

프론트는 start 응답의 authorization_url로 **브라우저를 이동**합니다. 콜백을 직접 fetch하지 않습니다. 완료 화면은 fragment의 oauth_status=success/error, error_code, 선택적인 claim_status=saved/failed와 return_path를 읽고 주소에서 제거합니다. 원시 OAuth 코드·제공자 토큰·세션 토큰은 완료 URL에 넣지 않습니다.

성공 후 GET /api/auth/me로 회원 정보, GET /api/auth/csrf로 새 CSRF를 받습니다. return_path는 내부 상대 경로만 허용하며 실제 프론트 이동은 프론트에서 처리합니다. claim_contract_id로 선택한 비회원 완료 결과만 귀속하고, 저장에 실패해도 로그인 성공은 유지합니다.

구글은 PKCE(S256)와 서명·issuer·audience·발급/만료 시각·nonce·azp를 검증합니다. 카카오는 인가 코드를 액세스 토큰으로 교환하고 공식 사용자 정보 API에서 고유 ID를 확인합니다. 이메일이 같아도 EMAIL/KAKAO/GOOGLE 계정은 별도입니다. 제공자 액세스/리프레시 토큰은 DB에 보관하지 않습니다.

## 6. 현재 실행 조건

OAuth state는 서버 메모리의 한정된 저장소에 10분 보관하고 브라우저·제공자·현재 로그인/비회원 쿠키에 결합합니다. 콜백에서 한 번만 소비합니다. 새 로그인을 시작하면 이전 브라우저 OAuth 쿠키를 교체하므로 여러 로그인 창을 동시에 진행하지 마세요.

**현재는 단일 프로세스 실행 기준입니다.** worker 여러 개·여러 서버를 쓰기 전에는 DB/Redis 등 공유 OAuth 컨텍스트 저장소가 필요합니다. 서버 재시작·리로드 시 진행 중 로그인은 다시 시작해야 합니다. 로그인 완료 세션은 DB에 보관하므로 별도 만료 정책을 따릅니다. 운영에서는 고정 HTTPS 완료 주소 설정이 필요합니다.

앱 미들웨어는 콜백의 쿼리 문자열을 Uvicorn 접근 로그에서 제외합니다. 배포 시 프록시·게이트웨이 로그에도 콜백 code/state를 남기지 않도록 설정해야 합니다.

대표 오류: INVALID_OAUTH_STATE(만료·재사용·다른 브라우저/호스트), OAUTH_DENIED(취소/거절), OAUTH_EXCHANGE_FAILED(인가 코드 교환 실패), OAUTH_IDENTITY_INVALID(ID 검증 실패), DATABASE_UNAVAILABLE(DB 실패). 오류는 완료 화면 fragment의 제한된 코드로 전달합니다.

공식 문서: [카카오 로그인 설정](https://developers.kakao.com/docs/ko/kakaologin/prerequisite), [카카오 REST API](https://developers.kakao.com/docs/ko/kakaologin/rest-api), [Google 동의 화면](https://developers.google.com/workspace/guides/configure-oauth-consent), [Google 웹 서버 OAuth](https://developers.google.com/identity/protocols/oauth2/web-server).
