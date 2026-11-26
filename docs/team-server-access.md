# 팀 접속 및 원격 실행

## 현재 팀 개발 규칙

- 공유 개발 DB에는 가상 계약서 또는 충분히 마스킹한 테스트 문서만 저장합니다. 현재 서버의 자동 탐지는 주민번호·휴대전화·이메일 패턴에 한정되며 이름·주소·계좌번호를 모두 차단하지 못합니다. 무료 Gemini 키를 쓰는 분석에도 같은 제한을 적용합니다.
- 프론트 연동만 하는 팀원은 공유 백엔드 API를 사용합니다. `CHECKIT_DATABASE_URL`은 로컬 백엔드를 직접 실행하는 신뢰된 팀원에게만 안전한 경로로 전달합니다. 현재 `checkit_backend` DB 계정은 모든 회원의 행을 직접 조회·변경할 수 있으므로, API의 회원별 소유권 검사와 같은 격리 수준을 제공하지 않습니다.
- 개발용 `/dev/analysis-test`와 `/dev/email-verification`은 팀 내부에서만 사용합니다. 외부 HTTPS 터널을 쓸 경우에도 팀원 인증으로 접근을 제한해야 합니다.
- 계약서를 재분석하면 이전 분석 결과를 새 결과로 교체합니다. 테스트 기록은 담당자가 주기적으로 확인해 불필요한 계약서를 API로 삭제합니다. 공유 DB의 스키마·권한 SQL은 다시 실행하지 않습니다.

## 1. 내 컴퓨터의 서버를 다른 컴퓨터에서 사용

예시 서버 IP는 `192.168.0.10`입니다. 실제 서버 컴퓨터의 Wi-Fi/이더넷 IPv4로 바꿉니다. Mac은 시스템 설정 → 네트워크 → 연결 상세 정보 → TCP/IP, Windows는 `ipconfig`에서 확인합니다.

서버 컴퓨터의 `CheckIt_BE/.env`에 실제 브라우저 주소를 추가합니다.

```dotenv
CHECKIT_ENVIRONMENT=development
CHECKIT_COOKIE_SECURE=false
CHECKIT_ALLOWED_ORIGINS=["http://127.0.0.1:8000","http://localhost:8000","http://192.168.0.10:8000","http://192.168.0.10:5173"]
```

서버 실행:

```bash
cd CheckIt_BE
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Windows PowerShell:

```powershell
cd CheckIt_BE
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

다른 컴퓨터에서 `http://192.168.0.10:8000/docs`를 엽니다. `0.0.0.0`은 서버의 수신 설정이며 접속 URL이 아닙니다. 같은 LAN/Wi-Fi에 연결되어야 하며, OS 방화벽에서 신뢰하는 네트워크의 TCP 8000 수신을 허용해야 합니다. 게스트 Wi-Fi의 기기 간 통신 차단이 있으면 접속되지 않을 수 있습니다. 이 설정만으로 다른 집이나 모바일 데이터에서 접속되는 것은 아닙니다.

`/health/live`는 프로세스, `/health/ready`는 DB 연결을 확인합니다. Swagger에서 CSRF 발급 → 회원 로그인 순으로 확인합니다. 이 프로젝트는 POST의 Origin을 CSRF 검사에도 사용하므로 Swagger 주소도 허용 목록에 필요합니다. `*`로 대체하지 않습니다.

## 2. 프론트 개발 시 주소 주의

프론트 API 기본 주소는 `http://192.168.0.10:8000/api`, fetch 옵션은 `credentials: "include"`로 설정합니다. 실제 API 환경변수 이름은 프론트 프로젝트에서 확인합니다.

현재 인증 쿠키는 `SameSite=Lax`입니다. 팀원 컴퓨터의 `http://localhost:5173` 프론트에서 서버의 `http://192.168.0.10:8000` API를 직접 호출하면 서로 다른 사이트이므로 CORS만 추가해도 쿠키 인증이 실패할 수 있습니다.

개발 시에는 프론트 개발 서버의 `/api` 프록시를 백엔드로 연결하고, 브라우저는 상대 경로 `/api`를 호출하는 구성을 권장합니다. 이때 백엔드 허용 Origin에는 브라우저에서 여는 프론트 주소(예: `http://localhost:5173`)를 추가합니다. 프록시가 해당 Origin을 보존하도록 하고, `/api` 경로를 제거하지 않습니다. `/docs` 직접 테스트는 백엔드 주소에서 별도로 진행합니다.

프론트도 서버 컴퓨터에서 실행해 `http://192.168.0.10:5173`로 접근하면 API와 호스트가 같아 쿠키 연동이 간단합니다. 프론트 개발 서버도 LAN 수신을 허용해야 합니다.

소셜 로그인은 현재 `localhost` 콜백 기준입니다. 다른 컴퓨터가 서버 IP로 접속한 상태에서 localhost 콜백을 사용하면 그 컴퓨터로 돌아갑니다. 공유 로그인은 HTTPS 주소를 정하고 카카오·구글 콘솔의 콜백과 `.env`의 redirect URI 및 완료 주소를 함께 바꿔야 합니다. 현재 URL 검증은 개발 HTTP OAuth도 localhost/127.0.0.1만 허용합니다.

## 3. 팀원 각자가 백엔드를 실행

공용 서버의 API만 사용하는 팀원은 백엔드를 클론하거나 DB 비밀키를 받을 필요가 없습니다. 백엔드 개발을 위해 각자 실행할 때만 다음 작업이 필요합니다.

1. 백엔드 레포를 클론하고 `app/`이 있는 폴더로 이동합니다.
2. Python 3.13으로 가상환경을 만들고 `requirements-lock.txt`를 설치합니다(README 실행 절차 참고).
3. `.env.example`을 `.env`로 복사합니다. Mac/Linux는 `cp .env.example .env`, PowerShell은 `Copy-Item .env.example .env`를 사용합니다.
4. 로컬 백엔드 실행이 필요한 팀원만 담당자에게 안전하게 받은 `CHECKIT_DATABASE_URL`을 입력합니다. 관리자 URI·관리자 암호는 비웁니다. 같은 개발 DB를 쓰면 모든 테스트 데이터가 공유되고, DB URI를 가진 사람은 API를 거치지 않고 전체 행에 접근할 수 있습니다. 초기 SQL은 재실행하지 않습니다.
5. 자기 컴퓨터에서만 쓸 경우 기존 README의 `--host 127.0.0.1`로 실행합니다. 공유할 컴퓨터만 `--host 0.0.0.0`과 해당 Origin 설정을 사용합니다.
6. 별도 프론트가 있으면 그 브라우저 Origin을 추가합니다. 소셜 로그인/SMTP를 테스트할 때만 관련 자격 증명과 주소를 설정합니다.

앱의 Python 소스에 IP나 비밀키를 하드코딩할 필요는 없습니다. `.env`는 커밋하지 않습니다. RAG는 기본 비활성이며, 필요한 팀원은 README의 추가 설치 및 Data 인덱스 준비까지 진행합니다. Git 클론만으로 인덱스는 생기지 않습니다.

## 4. 휴대폰으로 서버 켜기

노트북이 켜져 있고 인터넷에 연결되어 있으며 잠들지 않은 상태라면 원격으로 프로세스를 시작할 수 있습니다. 화면 잠금과 절전은 다릅니다. 꺼져 있거나 절전 상태인 컴퓨터에서 SSH 명령을 실행할 수는 없습니다. Wake-on-LAN은 장비·전원·공유기 지원에 따라 달라지므로 상시 운영의 전제로 삼지 않습니다.

개인 노트북을 사용할 때의 구성:

1. 노트북과 휴대폰에 Tailscale을 설치하고 같은 개인 네트워크에 연결합니다.
2. Mac의 시스템 설정 → 일반 → 공유 → 원격 로그인을 필요한 사용자에게만 허용합니다.
3. 휴대폰의 SSH 클라이언트에서 노트북의 Tailscale IP와 Mac 사용자 계정으로 접속합니다. 이는 일반 SSH를 Tailscale 네트워크로 사용하는 방식입니다.
4. SSH 터미널에서 다음을 실행합니다.

```bash
cd /Users/heochaeyun/Desktop/CheckIt/CheckIt_BE
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

이 명령은 포그라운드 실행입니다. SSH 연결 종료 후에도 유지하려면 사전에 tmux 또는 macOS launchd로 프로세스를 관리하도록 구성합니다. Tailscale로 API에 직접 접근한다면 허용 Origin과 프론트 API 주소도 실제 Tailscale 접속 주소로 맞춥니다. 휴대폰은 켜기/끄기 명령을 보내는 도구이고 서버 연산은 노트북이 수행합니다.

노트북 전원과 무관하게 팀이 계속 사용하려면 별도의 Linux VM/상시 켜진 컴퓨터에 백엔드와 필요한 RAG 데이터를 배치하는 구성이 적합합니다. systemd로 부팅 시 자동 실행·실패 시 재시작을 설정하고, 휴대폰 SSH에서 등록한 서비스에 `sudo systemctl start checkit`, `stop checkit`, `status checkit` 명령을 사용합니다. 이 명령은 `checkit` 서비스를 먼저 등록한 경우에만 동작합니다. VM 자체가 꺼져 있으면 클라우드 관리 화면에서 먼저 켜야 합니다.

공개 배포 시에는 HTTPS 프록시/도메인과 다음 환경변수 및 실제 HTTPS OAuth 콜백을 함께 준비합니다.

```dotenv
CHECKIT_ENVIRONMENT=production
CHECKIT_COOKIE_SECURE=true
CHECKIT_ALLOWED_ORIGINS=["https://실제프론트도메인","https://실제API도메인"]
CHECKIT_CSRF_SECRET=32자_이상의_충분히_무작위인_비밀값
```

프론트와 API는 같은 사이트 또는 동일 Origin의 `/api` 프록시로 제공하는 구성이 현재 쿠키 정책에 맞습니다. OAuth 상태·요청 제한·RAG 실행 상태가 메모리에 있으므로 현재는 단일 worker/단일 인스턴스로 운영합니다. Supabase DB만으로 FastAPI나 로컬 RAG 프로세스가 실행되지는 않습니다.

## 실제 사용자 계약서를 받기 전 출시 조건

현재 공유 개발 DB와 개발용 화면을 실제 계약서 운영에 그대로 사용하지 않습니다. 공개 전에 다음을 완료하고 별도 환경에서 검증합니다.

1. 회원별 DB 격리: 현재 `checkit_backend`의 전 행 허용 RLS 정책을 교체할 설계를 만들고, 인증·계약서·분석의 모든 DB 경로와 권한 검증 SQL을 확인합니다. 기존 공유 DB에 초기·권한 SQL을 재실행하지 않습니다.
2. 개인정보: 프론트 OCR 라이브러리를 빌드에 포함해 버전을 고정하고, 이름·주소·계좌번호를 포함한 마스킹 흐름과 Gemini 전송 조건을 실제 문서로 검증합니다. 무료 등급의 데이터 처리 조건을 확인하고 사용자에게 보관·전송·삭제 정책을 고지합니다.
3. 분석 운영: 프로세스 내 `BackgroundTasks`의 재시작·동시 실행·재시도 한계를 검증하고, 요청 수와 Gemini 사용량·비용 한도를 정합니다. 현재의 회원별 메모리 요청 제한만으로 전체 비용을 제한할 수 없습니다.
4. 데이터 수명: 보관 기간과 삭제 범위를 정하고 계약서·확정 텍스트·분석 결과·백업에서의 삭제 동작을 검증합니다. 현재 계약서 삭제 API는 DB의 해당 기록을 영구 삭제하지만 백업 보관 정책은 별도로 정해야 합니다.

참고: [Uvicorn 실행 설정](https://uvicorn.dev/settings/), [일반 SSH를 Tailscale로 보호](https://tailscale.com/docs/reference/ssh-over-tailscale), [systemd 서비스 설정](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
