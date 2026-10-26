-- CheckIt initial schema. Run ONCE in a new Supabase project's SQL Editor.
-- PostgreSQL 14+. Uses a separate schema, not Supabase's auth schema.
-- No users, passwords, real contracts, or sample personal data are inserted.
BEGIN;
SET LOCAL timezone = 'UTC';

CREATE SCHEMA checkit;
REVOKE ALL ON SCHEMA checkit FROM PUBLIC;

CREATE TABLE checkit.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'ACTIVE')),
    email_verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE checkit.auth_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL UNIQUE REFERENCES checkit.users(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('EMAIL', 'KAKAO', 'GOOGLE')),
    provider_subject text NOT NULL CHECK (btrim(provider_subject) <> ''),
    email text,
    password_hash text,
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_subject),
    UNIQUE (id, user_id),
    CONSTRAINT identity_credentials CHECK (
        (provider = 'EMAIL' AND email IS NOT NULL AND btrim(email) <> ''
         AND email = lower(btrim(email)) AND provider_subject = email
         AND password_hash IS NOT NULL AND btrim(password_hash) <> '')
        OR (provider IN ('KAKAO', 'GOOGLE') AND password_hash IS NULL)
    )
);

CREATE TABLE checkit.auth_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES checkit.users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE CHECK (btrim(token_hash) <> ''),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at > created_at)
);

CREATE TABLE checkit.email_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES checkit.users(id) ON DELETE CASCADE,
    identity_id uuid NOT NULL,
    purpose text NOT NULL DEFAULT 'VERIFY_EMAIL' CHECK (purpose = 'VERIFY_EMAIL'),
    target_email text NOT NULL CHECK (btrim(target_email) <> ''),
    token_hash text NOT NULL UNIQUE CHECK (btrim(token_hash) <> ''),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (identity_id, user_id)
        REFERENCES checkit.auth_identities(id, user_id) ON DELETE CASCADE,
    CHECK (expires_at > created_at)
);

CREATE TABLE checkit.guest_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash text NOT NULL UNIQUE CHECK (btrim(token_hash) <> ''),
    revoked_at timestamptz,
    last_seen_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE checkit.contracts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES checkit.users(id),
    guest_session_id uuid REFERENCES checkit.guest_sessions(id),
    contract_type text NOT NULL CHECK (btrim(contract_type) <> ''),
    input_kind text NOT NULL CHECK (input_kind IN ('PDF', 'IMAGES')),
    current_file_generation_id uuid,
    first_uploaded_at timestamptz,
    expires_at timestamptz,
    deletion_state text NOT NULL DEFAULT 'AVAILABLE'
        CHECK (deletion_state IN ('AVAILABLE', 'DELETING')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT one_contract_owner CHECK (num_nonnulls(user_id, guest_session_id) = 1),
    CONSTRAINT contract_expiration CHECK (
        (user_id IS NOT NULL AND expires_at IS NULL)
        OR (guest_session_id IS NOT NULL AND (
            (first_uploaded_at IS NULL AND expires_at IS NULL)
            OR (first_uploaded_at IS NOT NULL AND expires_at IS NOT NULL
                AND expires_at = first_uploaded_at + interval '24 hours')
        ))
    )
);

-- One submitted/reuploaded set of files. This replaces unvalidated generation IDs.
CREATE TABLE checkit.file_generations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NOT NULL REFERENCES checkit.contracts(id) ON DELETE CASCADE,
    input_kind text NOT NULL CHECK (input_kind IN ('PDF', 'IMAGES')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, contract_id)
);
ALTER TABLE checkit.contracts ADD CONSTRAINT current_generation_belongs_to_contract
    FOREIGN KEY (current_file_generation_id, id)
    REFERENCES checkit.file_generations(id, contract_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE checkit.file_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NOT NULL REFERENCES checkit.contracts(id) ON DELETE CASCADE,
    generation_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('ORIGINAL', 'PREVIEW', 'OCR_IMAGE')),
    storage_key text NOT NULL UNIQUE CHECK (
        btrim(storage_key) <> '' AND storage_key !~ '^/'
        AND storage_key !~ '(^|/)\.\.(/|$)' AND position(chr(92) in storage_key) = 0
    ),
    original_filename text,
    media_type text NOT NULL CHECK (media_type IN (
        'application/pdf', 'image/jpeg', 'image/png', 'image/heic'
    )),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    source_asset_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, contract_id, generation_id),
    FOREIGN KEY (generation_id, contract_id)
        REFERENCES checkit.file_generations(id, contract_id) ON DELETE CASCADE,
    FOREIGN KEY (source_asset_id, contract_id, generation_id)
        REFERENCES checkit.file_assets(id, contract_id, generation_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK ((role = 'ORIGINAL' AND source_asset_id IS NULL AND size_bytes <= 20000000)
        OR (role <> 'ORIGINAL' AND source_asset_id IS NOT NULL))
);

CREATE TABLE checkit.document_pages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NOT NULL REFERENCES checkit.contracts(id) ON DELETE CASCADE,
    generation_id uuid NOT NULL,
    file_asset_id uuid NOT NULL,
    source_page_number integer NOT NULL CHECK (source_page_number BETWEEN 1 AND 10),
    page_order integer NOT NULL CHECK (page_order BETWEEN 1 AND 10),
    width numeric CHECK (width > 0),
    height numeric CHECK (height > 0),
    coordinate_unit text CHECK (coordinate_unit IN ('PIXEL', 'POINT', 'NORMALIZED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (file_asset_id, contract_id, generation_id)
        REFERENCES checkit.file_assets(id, contract_id, generation_id) ON DELETE CASCADE,
    UNIQUE (generation_id, page_order) DEFERRABLE INITIALLY IMMEDIATE,
    UNIQUE (file_asset_id, source_page_number),
    CHECK ((width IS NULL AND height IS NULL AND coordinate_unit IS NULL)
        OR (width IS NOT NULL AND height IS NOT NULL AND coordinate_unit IS NOT NULL))
);

CREATE TABLE checkit.text_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NOT NULL REFERENCES checkit.contracts(id) ON DELETE CASCADE,
    file_generation_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision >= 1),
    kind text NOT NULL CHECK (kind IN ('EXTRACTED', 'USER_EDITED')),
    content text NOT NULL CHECK (btrim(content) <> ''),
    blocks jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(blocks) = 'array'),
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (file_generation_id, contract_id)
        REFERENCES checkit.file_generations(id, contract_id) ON DELETE CASCADE,
    UNIQUE (contract_id, revision),
    UNIQUE (id, contract_id, file_generation_id)
);

CREATE TABLE checkit.analysis_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NOT NULL REFERENCES checkit.contracts(id) ON DELETE CASCADE,
    request_id uuid NOT NULL UNIQUE,
    kind text NOT NULL CHECK (kind IN ('EXTRACTION', 'ANALYSIS')),
    file_generation_id uuid NOT NULL,
    input_revision_id uuid,
    status text NOT NULL DEFAULT 'QUEUED' CHECK (status IN (
        'QUEUED', 'RUNNING', 'CANCEL_REQUESTED', 'CANCELLED', 'SUCCEEDED', 'FAILED'
    )),
    stage text CHECK (stage IN ('EXTRACT', 'CLASSIFY', 'RETRIEVE', 'EVALUATE', 'EXPLAIN')),
    error_code text,
    recovery_action text CHECK (recovery_action IN ('REUPLOAD', 'RETRY', 'LOGIN', 'NONE')),
    cancel_requested_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (file_generation_id, contract_id)
        REFERENCES checkit.file_generations(id, contract_id) ON DELETE CASCADE,
    FOREIGN KEY (input_revision_id, contract_id, file_generation_id)
        REFERENCES checkit.text_revisions(id, contract_id, file_generation_id),
    CHECK ((kind = 'EXTRACTION' AND input_revision_id IS NULL)
        OR (kind = 'ANALYSIS' AND input_revision_id IS NOT NULL)),
    CHECK ((status IN ('CANCELLED', 'SUCCEEDED', 'FAILED')) = (finished_at IS NOT NULL)),
    UNIQUE (id, contract_id, file_generation_id, input_revision_id)
);

CREATE TABLE checkit.analysis_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NOT NULL UNIQUE REFERENCES checkit.contracts(id) ON DELETE CASCADE,
    job_id uuid NOT NULL UNIQUE,
    file_generation_id uuid NOT NULL,
    input_revision_id uuid NOT NULL,
    summary text NOT NULL CHECK (btrim(summary) <> ''),
    model_versions jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(model_versions) = 'object'),
    prompt_version text,
    corpus_version text NOT NULL CHECK (btrim(corpus_version) <> ''),
    rule_version text,
    completed_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (job_id, contract_id, file_generation_id, input_revision_id)
        REFERENCES checkit.analysis_jobs(id, contract_id, file_generation_id, input_revision_id),
    FOREIGN KEY (input_revision_id, contract_id, file_generation_id)
        REFERENCES checkit.text_revisions(id, contract_id, file_generation_id)
);

CREATE TABLE checkit.check_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id uuid NOT NULL REFERENCES checkit.analysis_results(id) ON DELETE CASCADE,
    check_code text NOT NULL CHECK (btrim(check_code) <> ''),
    labels jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(labels) = 'array'),
    status text NOT NULL CHECK (status IN (
        'CAUTION', 'MISSING_SUSPECTED', 'NEEDS_CONFIRMATION', 'PRESENT'
    )),
    quoted_text text,
    explanation text NOT NULL CHECK (btrim(explanation) <> ''),
    required_information jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(required_information) = 'array'),
    source_locations jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(source_locations) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE checkit.law_citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    check_item_id uuid NOT NULL REFERENCES checkit.check_items(id) ON DELETE CASCADE,
    law_id text NOT NULL,
    law_name text NOT NULL CHECK (btrim(law_name) <> ''),
    article_id text NOT NULL,
    article_number text NOT NULL,
    chunk_id text NOT NULL,
    content text NOT NULL CHECK (btrim(content) <> ''),
    effective_date date,
    source_url text NOT NULL CHECK (source_url LIKE 'https://%'),
    corpus_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (check_item_id, corpus_version, chunk_id)
);

CREATE INDEX contracts_member_list ON checkit.contracts(user_id, created_at DESC)
    WHERE user_id IS NOT NULL;
CREATE INDEX contracts_guest_list ON checkit.contracts(guest_session_id, created_at DESC)
    WHERE guest_session_id IS NOT NULL;
CREATE INDEX contracts_expiry ON checkit.contracts(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX sessions_by_user ON checkit.auth_sessions(user_id);
CREATE INDEX email_tokens_by_user ON checkit.email_tokens(user_id);
CREATE INDEX files_by_generation ON checkit.file_assets(generation_id);
CREATE INDEX revisions_by_generation ON checkit.text_revisions(file_generation_id);
CREATE INDEX jobs_by_contract ON checkit.analysis_jobs(contract_id, created_at DESC);
CREATE UNIQUE INDEX one_active_analysis_per_contract ON checkit.analysis_jobs(contract_id)
    WHERE kind = 'ANALYSIS' AND status IN ('QUEUED', 'RUNNING', 'CANCEL_REQUESTED');
CREATE INDEX items_by_result ON checkit.check_items(result_id);
CREATE INDEX citations_by_item ON checkit.law_citations(check_item_id);

CREATE FUNCTION checkit.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END;
$$;

-- Preserve the first upload's deadline across retries, cancellation and reuploads.
CREATE FUNCTION checkit.enforce_contract_retention() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.first_uploaded_at IS NOT NULL
           AND NEW.first_uploaded_at IS DISTINCT FROM OLD.first_uploaded_at THEN
            RAISE EXCEPTION 'first_uploaded_at is immutable' USING ERRCODE = '23514';
        END IF;
        IF OLD.user_id IS NOT NULL AND NEW.user_id IS DISTINCT FROM OLD.user_id THEN
            RAISE EXCEPTION 'member ownership cannot be reassigned' USING ERRCODE = '23514';
        END IF;
        IF OLD.guest_session_id IS NOT NULL AND NEW.user_id IS NULL
           AND NEW.guest_session_id IS DISTINCT FROM OLD.guest_session_id THEN
            RAISE EXCEPTION 'guest ownership cannot be reassigned' USING ERRCODE = '23514';
        END IF;
        IF OLD.guest_session_id IS NOT NULL AND NEW.user_id IS NOT NULL
           AND (OLD.deletion_state <> 'AVAILABLE' OR OLD.expires_at <= now()) THEN
            RAISE EXCEPTION 'expired/deleting guest contract cannot be claimed'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.user_id IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM checkit.users WHERE id = NEW.user_id AND status = 'ACTIVE') THEN
            RAISE EXCEPTION 'contract owner must be active' USING ERRCODE = '23514';
        END IF;
        NEW.expires_at := NULL;
    ELSIF NEW.first_uploaded_at IS NOT NULL THEN
        NEW.expires_at := NEW.first_uploaded_at + interval '24 hours';
    ELSE
        NEW.expires_at := NULL;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER enforce_contract_retention BEFORE INSERT OR UPDATE ON checkit.contracts
    FOR EACH ROW EXECUTE FUNCTION checkit.enforce_contract_retention();

-- Serialize original-file count/total-size checks within one upload generation.
CREATE FUNCTION checkit.validate_original_file() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE upload_kind text; file_count integer; total_size bigint;
BEGIN
    SELECT input_kind INTO upload_kind FROM checkit.file_generations
        WHERE id = NEW.generation_id AND contract_id = NEW.contract_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'upload generation does not belong to contract' USING ERRCODE = '23503';
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.contract_id, NEW.generation_id)
        IS DISTINCT FROM (OLD.contract_id, OLD.generation_id) THEN
        RAISE EXCEPTION 'file generation is immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.role = 'ORIGINAL' THEN
        IF (upload_kind = 'PDF' AND NEW.media_type <> 'application/pdf')
           OR (upload_kind = 'IMAGES' AND NEW.media_type = 'application/pdf') THEN
            RAISE EXCEPTION 'mixed file types are not allowed' USING ERRCODE = '23514';
        END IF;
        SELECT count(*), coalesce(sum(size_bytes), 0) INTO file_count, total_size
            FROM checkit.file_assets WHERE generation_id = NEW.generation_id
            AND role = 'ORIGINAL' AND id <> NEW.id;
        IF (upload_kind = 'PDF' AND file_count >= 1)
           OR file_count >= 10 OR total_size + NEW.size_bytes > 100000000 THEN
            RAISE EXCEPTION 'file count or total size limit exceeded' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_original_file BEFORE INSERT OR UPDATE ON checkit.file_assets
    FOR EACH ROW EXECUTE FUNCTION checkit.validate_original_file();

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'users', 'auth_identities', 'contracts', 'analysis_jobs'
    ] LOOP
        EXECUTE format('CREATE TRIGGER touch_updated_at BEFORE UPDATE ON checkit.%I '
            'FOR EACH ROW EXECUTE FUNCTION checkit.touch_updated_at()', table_name);
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY[
        'users', 'auth_identities', 'auth_sessions', 'email_tokens', 'guest_sessions',
        'contracts', 'file_generations', 'file_assets', 'document_pages',
        'text_revisions', 'analysis_jobs', 'analysis_results', 'check_items', 'law_citations'
    ] LOOP
        EXECUTE format('ALTER TABLE checkit.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON TABLE checkit.%I FROM PUBLIC', table_name);
    END LOOP;
END;
$$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA checkit FROM PUBLIC;

COMMENT ON SCHEMA checkit IS 'CheckIt application data; FastAPI direct PostgreSQL connection only';
COMMENT ON TABLE checkit.users IS '제공자별 독립 회원 계정';
COMMENT ON TABLE checkit.auth_identities IS '계정당 로그인 수단 한 개. 계정 연결 기능 없음';
COMMENT ON TABLE checkit.auth_sessions IS '회원 로그인 세션. 비밀값은 해시로 저장';
COMMENT ON TABLE checkit.email_tokens IS '이메일 가입 인증 전용. 비밀번호 재설정 제외';
COMMENT ON TABLE checkit.guest_sessions IS '비회원 브라우저 접근 식별';
COMMENT ON TABLE checkit.contracts IS '계약서 소유권·종류·첫 업로드 후 24시간 보관 정책';
COMMENT ON TABLE checkit.file_generations IS '최초 제출·전체 재업로드별 파일 묶음';
COMMENT ON TABLE checkit.file_assets IS '서버 폴더 파일의 저장 키·형식·용량';
COMMENT ON TABLE checkit.document_pages IS 'PDF 또는 사진의 페이지 순서·원본 연결';
COMMENT ON TABLE checkit.text_revisions IS 'OCR 원문 및 사용자 수정본의 내부 입력 버전';
COMMENT ON TABLE checkit.analysis_jobs IS '요청 실행·취소·오류 추적. 별도 상태 조회 API를 뜻하지 않음';
COMMENT ON TABLE checkit.analysis_results IS '계약서별 현재 분석 결과 한 건';
COMMENT ON TABLE checkit.check_items IS '리포트 점검 항목·설명·원본 위치';
COMMENT ON TABLE checkit.law_citations IS '실제 인용한 법령 원문·버전·출처 스냅샷';

COMMIT;

-- Expected: 14 rows, all with row_security = true.
SELECT tablename, rowsecurity AS row_security
FROM pg_tables WHERE schemaname = 'checkit' ORDER BY tablename;
