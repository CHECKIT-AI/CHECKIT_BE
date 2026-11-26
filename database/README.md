# Supabase에 초기 테이블 생성

1. 만든 Supabase 프로젝트에서 **SQL Editor → New query**를 선택합니다.
2. `001_initial_schema.sql` 전체를 복사해서 붙여넣고 **Run**을 누릅니다.
3. 결과에 테이블 이름 13개와 `row_security = true`가 표시되는지 확인합니다.
4. **Table Editor**에서 스키마를 `checkit`으로 선택합니다. `public`에는 이번 테이블이 없습니다.

새 프로젝트에 한 번만 실행하는 SQL입니다. 이미 성공했다면 다시 실행하지 않습니다.
오류가 나면 오류 문구를 확인한 뒤 처리합니다. 데이터나 프로젝트를 삭제할 필요는 없습니다.

## 구성

- 로그인: users, auth_identities, auth_sessions, email_tokens
- 계약서·원본: contracts, file_generations, file_assets, document_pages
- 추출·분석: text_revisions, analysis_jobs, analysis_results, check_items, law_citations

`file_generations`는 최초 제출과 전체 재업로드의 파일 묶음을 구분합니다. 전체 테이블은 13개입니다.

Data API를 끈 상태에서 사용합니다. 모든 테이블에 RLS를 켜고 공개 접근 권한을 제거했습니다.
FastAPI 연결 계정의 권한과 팀원 열람 권한은 이후 별도로 설정합니다. Supabase SQL Editor에서는 소유자 권한으로 조회할 수 있습니다.

기존 DB에 근로계약서 분석 job을 추가할 때는 소유자 연결에서 `004_analysis_context.sql`을 한 번 적용합니다. 초기 스키마와 권한 프로비저닝 SQL을 다시 실행하지 않습니다. 이 마이그레이션은 `analysis_jobs.analysis_context`와 `check_items.rule_candidate` JSON 객체 필드를 추가하며 기존 RLS·역할 권한을 유지합니다.

기존 DB에서 계약서 기재 여부를 별도 저장하려면 소유자 연결에서 `005_document_presence.sql`을 한 번 적용합니다. 기존 결과의 `document_presence`는 `NULL`이며, 새 분석 결과부터 `PRESENT`·`ABSENT`·`UNCLEAR` 중 하나로 저장됩니다. 테이블 권한과 RLS는 유지됩니다.

현재 API는 브라우저에서 확인·마스킹한 페이지 텍스트를 저장하고 계약서 기록을 삭제할 수 있습니다. 원본 파일 업로드·서버 OCR·원본 다운로드 API는 없습니다. 저장된 확정 텍스트의 분석 job은 사용자별 동시 실행을 제한하고 최신 결과를 트랜잭션으로 교체합니다.
공유 개발 DB에는 가상·마스킹 테스트 데이터만 사용합니다. 현재 `checkit_backend`의 전 행 허용 RLS는 DB 직접 접속자를 회원별로 격리하지 않으므로 URI를 로컬 백엔드 실행자에게만 전달합니다. 실제 사용자 계약서를 받기 전에 권한 정책을 별도로 강화·검증해야 합니다.

`verify_schema.sql`은 개발용 검증 SQL입니다. 테스트 데이터는 롤백하며 초기 생성 때 붙여넣을 필요가 없습니다.
