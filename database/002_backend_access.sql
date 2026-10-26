-- Applied ONLY by scripts/provision_backend.py, in its owner transaction.
-- Does not rerun 001 or alter checkit_reader. No BYPASSRLS or schema ownership.
GRANT USAGE ON SCHEMA checkit TO checkit_backend;
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users','auth_identities','auth_sessions','email_tokens','guest_sessions',
        'contracts','file_generations','file_assets','document_pages',
        'text_revisions','analysis_jobs','analysis_results','check_items','law_citations'
    ] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='checkit' AND c.relname=t AND c.relrowsecurity) THEN
            RAISE EXCEPTION 'Required RLS table missing: %', t;
        END IF;
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON checkit.%I TO checkit_backend', t);
        EXECUTE format('DROP POLICY IF EXISTS checkit_backend_access ON checkit.%I', t);
        EXECUTE format('CREATE POLICY checkit_backend_access ON checkit.%I '
            'FOR ALL TO checkit_backend USING (true) WITH CHECK (true)', t);
    END LOOP;
END;
$$;
