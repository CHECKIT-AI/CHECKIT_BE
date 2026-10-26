# Supabase에 초기 테이블 생성

1. 만든 Supabase 프로젝트에서 **SQL Editor → New query**를 선택합니다.
2. `001_initial_schema.sql` 전체를 복사해서 붙여넣고 **Run**을 누릅니다.
3. 결과에 테이블 이름 14개와 `row_security = true`가 표시되는지 확인합니다.
4. **Table Editor**에서 스키마를 `checkit`으로 선택합니다. `public`에는 이번 테이블이 없습니다.

새 프로젝트에 한 번만 실행하는 SQL입니다. 이미 성공했다면 다시 실행하지 않습니다.
오류가 나면 오류 문구를 확인한 뒤 처리합니다. 데이터나 프로젝트를 삭제할 필요는 없습니다.

## 구성

- 로그인: users, auth_identities, auth_sessions, email_tokens, guest_sessions
- 계약서·원본: contracts, file_generations, file_assets, document_pages
- 추출·분석: text_revisions, analysis_jobs, analysis_results, check_items, law_citations

`file_generations`는 최초 제출과 전체 재업로드의 파일 묶음을 구분합니다. 기존 13개 테이블 초안에서 이 테이블을 추가해 총 14개입니다.

Data API를 끈 상태에서 사용합니다. 모든 테이블에 RLS를 켜고 공개 접근 권한을 제거했습니다.
FastAPI 연결 계정의 권한과 팀원 열람 권한은 이후 별도로 설정합니다. Supabase SQL Editor에서는 소유자 권한으로 조회할 수 있습니다.

현재 단계는 DB 구조 생성입니다. API, 로그인 처리, 파일 업로드, 24시간 만료 데이터 삭제 작업은 아직 구현되지 않았습니다.
만료 시각은 DB에 기록되지만, 시각이 지났다고 파일이 자동 삭제되지는 않습니다.
사용자별 동시 분석 제한, 텍스트 확인 여부, 결과 교체 트랜잭션은 API 구현 시 함께 적용해야 합니다.
원본 파일은 서버 폴더에 저장하고 DB에는 내부 저장 키를 보관합니다. 공유 DB만으로 로컬 원본 파일이 팀원에게 공개되지는 않습니다.
용량 한도는 파일당 20,000,000바이트, 전체 100,000,000바이트입니다.

`verify_schema.sql`은 개발용 검증 SQL입니다. 테스트 데이터는 롤백하며 초기 생성 때 붙여넣을 필요가 없습니다.
