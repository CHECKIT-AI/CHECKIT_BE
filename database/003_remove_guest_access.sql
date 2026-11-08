-- Destructive owner-only migration for an existing CheckIt database.
-- Review the affected row count before applying. Do not run through the web role.
BEGIN;

LOCK TABLE checkit.contracts IN ACCESS EXCLUSIVE MODE;

-- Guest-owned contracts and all dependent records are removed by ON DELETE CASCADE.
DELETE FROM checkit.contracts WHERE user_id IS NULL;

DROP TRIGGER IF EXISTS enforce_contract_retention ON checkit.contracts;
DROP FUNCTION IF EXISTS checkit.enforce_contract_retention();
DROP INDEX IF EXISTS checkit.contracts_guest_list;
DROP INDEX IF EXISTS checkit.contracts_expiry;

ALTER TABLE checkit.contracts
    DROP CONSTRAINT IF EXISTS one_contract_owner,
    DROP CONSTRAINT IF EXISTS contract_expiration,
    ALTER COLUMN user_id SET NOT NULL,
    DROP COLUMN guest_session_id,
    DROP COLUMN expires_at;

DROP TABLE checkit.guest_sessions;

CREATE FUNCTION checkit.enforce_contract_owner() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.first_uploaded_at IS NOT NULL
           AND NEW.first_uploaded_at IS DISTINCT FROM OLD.first_uploaded_at THEN
            RAISE EXCEPTION 'first_uploaded_at is immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
            RAISE EXCEPTION 'member ownership cannot be reassigned' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM checkit.users WHERE id = NEW.user_id AND status = 'ACTIVE') THEN
        RAISE EXCEPTION 'contract owner must be active' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER enforce_contract_owner BEFORE INSERT OR UPDATE ON checkit.contracts
    FOR EACH ROW EXECUTE FUNCTION checkit.enforce_contract_owner();

COMMENT ON TABLE checkit.contracts IS '회원 소유 계약서와 종류';
REVOKE ALL ON FUNCTION checkit.enforce_contract_owner() FROM PUBLIC;

COMMIT;
