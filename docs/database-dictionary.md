# DB 테이블·속성·도메인 설명서

작성일: 2026-10-21. [DB 구조 초안](database-design.md)을 설명하고 필드 후보를 구체화한 검토용 문서입니다. 아래 타입·허용 값·NULL 조건은 제안이며 실제 DDL을 생성하거나 모든 정책을 확정한 것은 아닙니다. 새로 이름을 붙인 속성도 포함합니다.

> 범위 변경: 비밀번호 재설정·회원 탈퇴는 사용자 후속 요청으로 첫 버전에서 제외됐습니다. 아래 재설정 토큰·탈퇴 관련 설명은 이전 검토 범위이며 구현 필수 사항이 아닙니다. 개별 기록 삭제·비회원 만료는 유지합니다. 2026-10-26 계정 연결을 제외하고 제공자별 독립 계정으로 변경했습니다.
## 저장 위치 이해하기

- 사용자 계약서를 법령 검색용 Chroma 컬렉션에 넣지 않는다는 것은 계약서를 저장하지 않는다는 뜻이 아닙니다. 계약서 파일은 서버 폴더에, 추출·수정 텍스트와 결과는 PostgreSQL에 저장합니다. Chroma에는 검색용 법령 데이터를 보관합니다.
- 파일 선택 시 사용자의 원래 파일 경로만 기억하는 방식이 아닙니다. 업로드된 파일의 내용을 서버가 받아 서버 관리 폴더에 별도 저장합니다. 사용자가 기기의 원래 파일을 삭제해도 업로드된 사본은 서버 정책에 따라 남습니다.
- 예시: 설정된 루트가 `/Users/heochaeyun/Desktop/CheckIt/CheckIt_BE/storage/uploads`이고 `storage_key`가 `contracts/<계약서ID>/<파일ID>.pdf`라면 백엔드는 이 둘을 결합한 서버 파일을 읽습니다. 실제 경로는 아직 미확정입니다.
- 키를 안다고 파일을 다운로드할 수 있어서는 안 됩니다. 백엔드는 소유권·만료·삭제 상태를 확인한 뒤 파일을 제공합니다.
- 실제 파일을 DB의 `bytea` 같은 타입으로 저장하는 것이 ‘바이너리 저장’입니다. 이번 설계에서는 파일 바이트를 폴더에, 위치와 관리 정보를 DB에 두는 방식을 선택했습니다.

## 용어·표 읽는 방법

| 용어 | 의미 |
| --- | --- |
| 테이블 | 같은 종류의 정보를 모으는 표. `contracts`의 행 하나는 계약서 한 건 |
| 속성·컬럼 | 행이 가진 항목. `expires_at`은 보관 만료 시각 |
| 도메인 | 컬럼에 허용되는 값의 집합·의미·범위. `page_order`는 ‘정수’뿐 아니라 ‘1~10’이라는 범위를 가짐 |
| 업무 도메인 | 인증·계약서·분석 같은 업무 영역. 컬럼의 값 도메인과 구분 |
| PK | 행을 식별하는 기본 키 |
| FK | 다른 테이블 행을 참조하는 외래 키. ID가 실제로 존재하는지 연결 |
| NULL | 아직 없거나 해당하지 않는 값. 0·빈 문자열과 다름 |
| UNIQUE | 중복을 허용하지 않는 값 또는 조합 |

이 문서의 도메인은 데이터 타입과 업무 제약을 설명합니다. PostgreSQL의 `CREATE DOMAIN` 사용자 정의 타입을 반드시 만들겠다는 뜻은 아닙니다.

| 타입 후보 | 의미 |
| --- | --- |
| `uuid` | 무작위 식별자 등에 사용하는 UUID. 식별자는 접근 권한 증명이 아님 |
| `text` | 길이가 가변적인 문자열 |
| `integer` / `bigint` | 정수 / 더 넓은 범위의 정수. 파일 바이트 수에는 bigint 후보 |
| `timestamptz` | 절대 시점을 저장하는 시간대 대응 날짜·시각. UTC로 관리하고 화면은 한국 시간으로 표시하는 방향 |
| `date` | 시각 없이 날짜만 저장. 법령 시행일 등 |
| `jsonb` | 구조화된 객체·배열. 애플리케이션에서 객체 내부 형식도 검증해야 함 |
| `numeric` | 정확한 소수 값. 정규화 좌표 등에 사용 가능 |

각 테이블은 `id uuid PK`, `created_at timestamptz`를 공통으로 갖는 안입니다. 변경하는 테이블에는 `updated_at timestamptz`를 추가합니다. 아래 표에서는 공통 컬럼을 반복하지 않습니다. 상태·종류 코드는 text와 CHECK 제약으로 시작할 수 있으며 실제 ENUM 타입 사용 여부는 미정입니다.

## 1. users — 회원 계정

업무 영역: 회원. 이메일·카카오·구글 각각에 독립된 서비스 계정 ID를 부여합니다. 같은 사람이 다른 제공자로 가입해도 기록을 공유하지 않습니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `status` | text | `PENDING`, `ACTIVE`, `DELETING` | 가입 인증 대기·정상 이용·탈퇴 정리 중. DELETING은 복구 가능한 탈퇴 유예가 아님 |
| `email_verified_at` | timestamptz | 미인증·이메일 수단 없음이면 NULL | 서비스 이메일 가입 인증 완료 시각. 소셜 가입은 제공자 인증과 별도 취급 |

소셜 로그인으로 생성한 계정은 소셜 인증으로 활성화할 수 있습니다. 소셜 계정에 이메일 수단을 추가하는 기능은 제공하지 않습니다. 소셜 응답의 이메일을 무조건 본인 인증된 주소로 취급하지 않습니다.

## 2. auth_identities — 로그인 수단

업무 영역: 인증. 서비스 계정 하나에 로그인 수단 하나만 대응합니다. 이메일·카카오·구글은 서로 다른 user_id이며 기록도 따로 관리합니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `user_id` | uuid FK | users.id, 필수·UNIQUE 후보 | 어느 독립 계정의 로그인 수단인지 |
| `provider` | text | `EMAIL`, `KAKAO`, `GOOGLE` | 인증 방식 |
| `provider_subject` | text | 필수, 제공자와 묶어 UNIQUE | 소셜의 고유 사용자 식별자. EMAIL은 서비스에서 정규화한 이메일 식별자 사용 제안 |
| `email` | text | 소셜에서 제공하지 않으면 NULL | 수단에 연결된 이메일. 같다는 이유만으로 계정 병합하지 않음 |
| `password_hash` | text | EMAIL은 필수, 소셜은 NULL | 비밀번호 검증용 해시. 원문 비밀번호 저장 금지 |
| `verified_at` | timestamptz | 아직 연결·인증 전이면 NULL | 이 로그인 수단이 실제 확인된 시각 |

`user_id` UNIQUE로 계정당 로그인 수단 하나를 표현하고, `(provider, provider_subject)` UNIQUE로 같은 제공자의 중복 가입을 방지하는 안입니다. 제공자 구분 없는 이메일 전역 UNIQUE는 두지 않습니다. 계정 연결·병합·연결 해제는 제공하지 않습니다. 이메일 변경도 현재 확정 범위가 아닙니다.

## 3. auth_sessions — 회원 로그인 세션

업무 영역: 인증. 로그인 후 요청이 어느 사용자에게서 왔는지 확인하는 용도입니다. 아래는 서버 저장 세션을 선택했을 때의 후보이며 JWT 방식 등은 아직 미확정입니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `user_id` | uuid FK | users.id, 필수 | 로그인한 계정 |
| `token_hash` | text | 필수, UNIQUE | 브라우저에 전달한 무작위 세션 비밀값의 검증용 해시 |
| `expires_at` | timestamptz | 필수, 수명은 미정 | 로그인 만료 시각. 계약서 24시간 보관과 별개 |
| `revoked_at` | timestamptz | 사용 가능하면 NULL | 로그아웃·탈퇴 등으로 강제 폐기한 시각 |

## 4. email_tokens — 이메일 일회성 인증

업무 영역: 인증. 가입 인증과 비밀번호 재설정 링크를 구분합니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `user_id` | uuid FK | users.id, 필수 | 해당 계정 |
| `identity_id` | uuid FK | auth_identities.id, 필수 후보 | 인증·재설정할 이메일 로그인 수단 |
| `purpose` | text | `VERIFY_EMAIL`, `RESET_PASSWORD` | 토큰 사용 목적. 다른 목적으로 재사용하지 않음 |
| `target_email` | text | 필수 | 발급 당시 대상 주소. 이후 주소 변경 시 이전 링크의 인증 방지 |
| `token_hash` | text | 필수, UNIQUE | 링크 비밀값의 해시. 링크 원문을 DB에 저장하지 않음 |
| `expires_at` | timestamptz | 필수, 유효 시간 미정 | 사용 가능한 마지막 시각 |
| `used_at` | timestamptz | 사용 전 NULL | 일회성 사용 완료 시각 |
| `revoked_at` | timestamptz | 폐기 전 NULL | 재발송 등으로 폐기한 시각. 재발송 정책은 미정 |

## 5. guest_sessions — 비회원 브라우저 식별

업무 영역: 비회원 접근. 한 브라우저에서 여러 계약서를 관리할 수 있습니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `token_hash` | text | 필수, UNIQUE | 브라우저가 가진 비밀값을 서버에서 검증하기 위한 해시 |
| `revoked_at` | timestamptz | 유효하면 NULL | 비회원 접근 수단 폐기 시각 |
| `last_seen_at` | timestamptz | 선택 | 마지막 접근 시각. 계약서 만료를 연장하는 데 사용하지 않음 |

브라우저 저장 방식은 미정입니다. UUID만으로 소유권을 증명하지 않습니다. 모든 계약서가 만료·귀속된 세션 등 불필요한 세션의 정리 기준은 구현 시 정하며 무기한 보관하지 않습니다.

## 6. contracts — 계약서 한 건

업무 영역: 계약서·소유권·보관. 파일이나 분석 실행 한 번과 구분되는 중심 데이터입니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `user_id` | uuid FK | 회원 소유면 필수, 비회원이면 NULL | 기록을 소유한 회원 |
| `guest_session_id` | uuid FK | 비회원이면 필수, 회원이면 NULL | 기록을 소유한 비회원 브라우저 |
| `contract_type` | text | 현재 `EMPLOYMENT` 등 지원 코드, 필수 | 사용자가 직접 선택한 계약서 종류. 추가 종류는 미정 |
| `input_kind` | text | `PDF`, `IMAGES` | 제출 방식. 혼합 불가 |
| `current_file_generation_id` | uuid | 파일 준비 전 NULL 가능 | 현재 제출 파일 묶음의 버전. 전체 재업로드 시 새 값 |
| `first_uploaded_at` | timestamptz | 첫 파일 업로드 전 NULL | 보관 시간 기준. 정확한 업로드 이벤트 미정 |
| `expires_at` | timestamptz | 업로드된 비회원은 필수, 회원은 NULL | 비회원은 first_uploaded_at+24시간 |
| `deletion_state` | text | `AVAILABLE`, `DELETING` | 접근 가능 또는 삭제 정리 중. 작업 성공·실패 상태와 별개 |

`user_id`와 `guest_session_id`는 정확히 하나만 존재해야 합니다. 계정 저장 시 같은 계약서의 user_id를 채우고 guest_session_id·expires_at을 비웁니다. first_uploaded_at은 이력으로 유지합니다.

계약서 유형 자동 판별 결과는 사용자 선택 contract_type을 덮어쓰지 않습니다. 근로계약 세부 속성은 분석 결과의 구조화된 내용으로 관리하는 후보이며 필드·판정 기준은 미정입니다.

## 7. file_assets — 저장된 실제 파일 정보

업무 영역: 파일 저장. 파일 하나마다 한 행입니다. 원본과 변환된 미리보기도 구별합니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `contract_id` | uuid FK | contracts.id, 필수 | 소속 계약서 |
| `generation_id` | uuid | 필수 | 어느 제출 파일 묶음인지. 계약서의 현재 세대와 비교 |
| `role` | text | `ORIGINAL`, `PREVIEW`, `OCR_IMAGE` 후보 | 원본·미리보기·OCR용 변환 파일 |
| `storage_key` | text | 서버 생성 상대 키, UNIQUE | 저장 루트를 기준으로 파일 위치를 찾는 내부 키 |
| `original_filename` | text | 원본 파일에 사용, 파생 파일은 NULL 가능 | 사용자가 올린 이름. 저장 경로로 신뢰하지 않음 |
| `media_type` | text | 내용 검사 결과의 지원 형식 | 예: application/pdf, image/jpeg, image/png, image/heic |
| `size_bytes` | bigint | 0 초과. 원본은 파일당 20MB 제한 | 실제 파일 크기. MB의 바이트 환산 기준 미정 |
| `source_asset_id` | uuid FK | 파생 파일은 원본 ID, 원본은 NULL | 변환 이미지의 출처 파일 |

사진 여러 장은 ORIGINAL 행 여러 개, PDF는 ORIGINAL 행 한 개입니다. 100MB 합계와 10장 제한은 현재 제출 원본에 적용하며 내부 미리보기 용량을 사용자 업로드 용량으로 합산하지 않습니다. 변환물의 서버 자원 제한은 별도로 설계합니다.

## 8. document_pages — 페이지 연결·순서

업무 영역: 원본 문서 구성. 현재 제출물의 논리 페이지를 나타내며 파일 교체 시 이전 텍스트·결과 연결을 고려해 정리해야 합니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `contract_id` | uuid FK | contracts.id, 필수 | 소속 계약서 |
| `file_asset_id` | uuid FK | 같은 계약서의 원본 file_assets.id | 어떤 파일에 들어 있는 페이지인지 |
| `source_page_number` | integer | 1 이상, PDF 실제 페이지 수 이하 | 원본 파일 안의 페이지 번호. 한 장짜리 사진은 1 |
| `page_order` | integer | 1~10, 계약서 내 UNIQUE | 사용자가 확정한 표시·분석 순서 |
| `width` / `height` | numeric | 추출 전 NULL 가능, 있으면 양수 | 좌표의 기준이 되는 페이지 크기 |
| `coordinate_unit` | text | `PIXEL`, `POINT` 등 후보 | width·height와 원본 영역 좌표 단위. 도구마다 다른 단위를 혼용하지 않음 |

PDF 한 파일이 3페이지면 같은 file_asset_id를 참조하는 페이지 행 3개가 생깁니다. 사진 3장이면 각기 다른 file_asset_id를 참조합니다.

## 9. text_revisions — OCR 원문·사용자 수정본

업무 영역: 텍스트 확인·버전. 사용자가 수정한 입력과 기존 결과의 입력을 구별합니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `contract_id` | uuid FK | contracts.id, 필수 | 소속 계약서 |
| `file_generation_id` | uuid | 필수 | 어떤 파일 묶음에서 나온 텍스트인지 |
| `revision` | integer | 1 이상, 계약서 내 UNIQUE | 내부 텍스트 버전 번호 |
| `kind` | text | `EXTRACTED`, `USER_EDITED` | 기계 추출 원문인지 사용자 수정본인지 |
| `content` | text | 비어 있는 추출 실패를 정상 입력으로 허용하지 않음 | 계약서 전체 텍스트 |
| `blocks` | jsonb | 배열, 상세 스키마 미정 | 블록 ID·문장 범위·페이지·영역·인식 신뢰도·수정 표시 등 |
| `confirmed_at` | timestamptz | 확인 전 NULL | 사용자가 분석 입력으로 확정한 시각 |

수정은 새 버전을 만들거나 확인 전 편집 초안으로 관리하는 방식 중 선택해야 합니다. 분석에 사용한 확정 버전은 실행 중 변경하지 않습니다. UI에 과거 수정 이력을 제공한다는 뜻은 아닙니다.

## 10. analysis_jobs — 추출·분석 작업

업무 영역: 비동기 작업. 실행 한 번마다 한 행이며, 완료된 결과와는 별개입니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `contract_id` | uuid FK | contracts.id, 필수 | 작업 대상 계약서 |
| `kind` | text | `EXTRACTION`, `ANALYSIS` | 텍스트 추출 또는 계약 내용 분석 |
| `input_revision_id` | uuid FK | ANALYSIS는 필수, EXTRACTION은 NULL | 실제로 분석한 확정 텍스트 |
| `file_generation_id` | uuid | 필수 | 실행 시 고정한 파일 묶음 버전 |
| `status` | text | QUEUED/RUNNING/CANCEL_REQUESTED/CANCELLED/SUCCEEDED/FAILED | 대기·실행·취소 요청·취소 완료·성공·실패 |
| `stage` | text | OCR/CLASSIFY/RETRIEVE/EXPLAIN 등 후보 | 실행 중 세부 단계. 상태와 구분 |
| `error_code` | text | 오류 없으면 NULL | PDF_LOCKED, FILE_UNREADABLE, UPSTREAM_TIMEOUT 등 예시 |
| `recovery_action` | text | REUPLOAD/RETRY/LOGIN/NONE 등 후보, 오류 없으면 NULL | 오류에 맞게 화면에 표시할 다음 행동 |
| `cancel_requested_at` | timestamptz | 요청 전 NULL | 사용자가 취소를 확인한 시각 |
| `started_at` | timestamptz | 실행 전 NULL | 작업자가 실제 실행한 시각 |
| `finished_at` | timestamptz | 종료 전 NULL | 성공·실패·취소 완료 시각 |

재시도 횟수·최대 시간·작업자 heartbeat·중복 실행 방지 키는 작업 실행 구조 설계 후 추가합니다. 텍스트 확인 대기는 RUNNING 작업으로 두지 않습니다. 상세 오류 로그는 이 표의 사용자 안내용 코드와 별도이며 계약서·비밀값의 불필요한 기록을 피합니다.

## 11. analysis_results — 현재 분석 결과

업무 영역: 리포트. 계약서당 현재 결과 한 행입니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `contract_id` | uuid FK | contracts.id, UNIQUE | 계약서당 현재 결과 한 건 |
| `job_id` | uuid FK | 성공한 ANALYSIS 작업, UNIQUE | 결과를 생성한 실행 |
| `input_revision_id` | uuid FK | 해당 계약서의 확정 텍스트 | 결과가 참조하는 실제 입력 |
| `summary` | text | 필수 | 사용자에게 보여줄 전체 요약 |
| `model_versions` | jsonb | 객체, 상세 스키마 미정 | 분류·임베딩·생성 모델의 ID·버전·커밋 |
| `prompt_version` | text | 생성에 사용하지 않았다면 NULL 가능 | 설명 생성 프롬프트 버전 |
| `corpus_version` | text | 검색 corpus 식별자 | 어떤 법령 인덱스를 사용했는지 |
| `rule_version` | text | 규칙 미사용 시 NULL 가능 | 점검 기준·후처리 버전 후보 |
| `completed_at` | timestamptz | 필수 | 결과가 확정된 시각 |

상태별 건수는 check_items에서 계산할 수 있어 독립 저장을 필수로 하지 않습니다. 재분석 성공 시 결과·항목·인용을 함께 교체하고, 실패·취소면 기존 결과를 유지합니다.

## 12. check_items — 점검 항목

업무 영역: 리포트 상세. 한 결과에 여러 항목이 있으며, 계약 조항 한 개와 반드시 1:1은 아닙니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `result_id` | uuid FK | analysis_results.id, 필수 | 어느 결과의 항목인지 |
| `check_code` | text | 지원 점검 규칙의 코드 | 예: WAGE_PAYMENT_DATE. 규칙 목록 미확정 |
| `labels` | jsonb | 10개 라벨 코드의 배열 | 한 항목의 관련 주제. 다중 라벨 허용 |
| `status` | text | CAUTION/MISSING_SUSPECTED/NEEDS_CONFIRMATION/PRESENT 후보 | 주의 필요·누락 의심·추가 확인 필요·기재 확인. 전체 명칭·우선순위 미확정 |
| `quoted_text` | text | 누락 항목 등 문장이 없으면 NULL | 분석 입력에서 가져온 계약 문장. 사용자 수정본일 수 있음 |
| `explanation` | text | 필수 | 주의·확인이 필요한 이유 |
| `required_information` | jsonb | 배열, 없으면 빈 배열 | 판단을 위해 별도로 확인할 정보. 분석 전 질문을 요구하는 용도가 아님 |
| `source_locations` | jsonb | 배열, 연결 불가면 빈 배열 | 원본 파일·페이지·영역 좌표·수정 표시. 여러 페이지에 걸칠 수 있음 |

‘기재 확인’은 적법성을 보장하지 않습니다. 좌표를 찾지 못한 누락 항목·추가 문장에는 원본 강조를 임의로 만들지 않습니다. labels 배열만으로 누락을 판정하지 않습니다.

## 13. law_citations — 사용한 법령 근거

업무 영역: 인용·재현성. 법령 전체 DB가 아니라 특정 결과에서 실제 사용한 근거를 보존합니다.

| 속성 | 타입 후보 | 도메인·NULL 조건 | 의미·역할 |
| --- | --- | --- | --- |
| `check_item_id` | uuid FK | check_items.id, 필수 | 이 근거를 사용하는 점검 항목 |
| `law_id` | text | 출처가 제공한 법령 식별자 | 법령을 찾기 위한 외부 ID. service UUID와 다름 |
| `law_name` | text | 필수 | 법령명 |
| `article_id` | text | 검색 corpus의 조문 식별자 | 해당 버전의 조문 식별 |
| `article_number` | text | 필수 | 제20조·제2조의2 등 표시용 번호. 정수 하나로 제한하지 않음 |
| `chunk_id` | text | 인용한 검색 청크 ID | Chroma 검색 결과와 연결하는 식별자 |
| `content` | text | 필수 | 실제 사용한 조문 원문 스냅샷 |
| `effective_date` | date | 검증된 시행일, 원천 미확인이면 NULL 허용 후 표시 | 법령 적용 시점 확인 자료 |
| `source_url` | text | 검증된 공식 출처 URL | 원문 확인 링크 |
| `corpus_version` | text | 필수 | 법령·청크 인덱스 버전 |

law_id·article_id·chunk_id는 Chroma에 대한 PostgreSQL FK가 아닙니다. 서로 다른 저장소이므로 서비스 코드에서 형식을 맞추고 인용 시 원문·버전을 함께 저장합니다. 법령 인덱스가 바뀌어도 과거 결과의 인용 원문이 자동으로 바뀌지 않게 합니다.

## 연결 예시

1. 비회원이 PDF 1개·3페이지를 올리면 contracts 1행, 원본 file_assets 1행, document_pages 3행이 생깁니다.
2. 추출 작업은 analysis_jobs에 기록하고 추출 텍스트는 text_revisions에 둡니다.
3. 사용자가 확인·수정한 버전을 입력으로 분석 작업을 생성합니다.
4. 분석 성공 시 analysis_results 1행과 여러 check_items·law_citations를 저장합니다.
5. 로그인하고 기록 저장을 완료하면 같은 contracts 행의 소유자와 만료 정책만 전환합니다.

이 구조는 설명을 위한 초안입니다. 인증 방식·작업 실행 방식 선택 후 필요 없는 테이블은 줄이거나 필드를 조정할 수 있습니다.

## 자료

- [PostgreSQL UUID](https://www.postgresql.org/docs/current/datatype-uuid.html)
- [PostgreSQL 날짜·시각 타입](https://www.postgresql.org/docs/current/datatype-datetime.html)
- [PostgreSQL JSON 타입](https://www.postgresql.org/docs/current/datatype-json.html)
