-- Local validation only. Test records are rolled back.
-- Expected: two rows after applying 004_analysis_context.sql.
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema='checkit' AND (
    (table_name='analysis_jobs' AND column_name='analysis_context')
    OR (table_name='check_items' AND column_name='rule_candidate'));
BEGIN;
DO $$
DECLARE
    contract_id uuid; generation_id uuid;
    member_id uuid; other_member_id uuid;
BEGIN
    INSERT INTO checkit.users(status) VALUES ('ACTIVE') RETURNING id INTO member_id;
    INSERT INTO checkit.users(status) VALUES ('ACTIVE') RETURNING id INTO other_member_id;
    INSERT INTO checkit.auth_identities(user_id, provider, provider_subject, email, password_hash)
        VALUES (member_id, 'EMAIL', 'test@example.invalid', 'test@example.invalid', 'test-hash');
    INSERT INTO checkit.auth_identities(user_id, provider, provider_subject, email)
        VALUES (other_member_id, 'GOOGLE', 'test-google-subject', 'test@example.invalid');
    INSERT INTO checkit.contracts(user_id, contract_type, input_kind, first_uploaded_at)
        VALUES (member_id, 'EMPLOYMENT', 'PDF', now()) RETURNING id INTO contract_id;
    BEGIN
        UPDATE checkit.contracts SET first_uploaded_at = now() + interval '1 hour' WHERE id = contract_id;
        RAISE EXCEPTION 'expected immutable first upload';
    EXCEPTION WHEN check_violation THEN NULL; END;
    INSERT INTO checkit.file_generations(contract_id, input_kind)
        VALUES (contract_id, 'PDF') RETURNING id INTO generation_id;
    UPDATE checkit.contracts SET current_file_generation_id = generation_id WHERE id = contract_id;
    INSERT INTO checkit.file_assets(contract_id, generation_id, role, storage_key, media_type, size_bytes)
        VALUES (contract_id, generation_id, 'ORIGINAL', 'test/original.pdf', 'application/pdf', 1024);
    BEGIN
        INSERT INTO checkit.file_assets(contract_id, generation_id, role, storage_key, media_type, size_bytes)
            VALUES (contract_id, generation_id, 'ORIGINAL', 'test/second.pdf', 'application/pdf', 1024);
        RAISE EXCEPTION 'expected one PDF limit';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        INSERT INTO checkit.file_assets(contract_id, generation_id, role, storage_key, media_type, size_bytes)
            VALUES (contract_id, generation_id, 'ORIGINAL', 'test/mixed.png', 'image/png', 1024);
        RAISE EXCEPTION 'expected mixed submission rejection';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        UPDATE checkit.contracts SET user_id = other_member_id WHERE id = contract_id;
        RAISE EXCEPTION 'expected immutable owner';
    EXCEPTION WHEN check_violation THEN NULL; END;
    SET CONSTRAINTS ALL IMMEDIATE;
END;
$$;
ROLLBACK;
