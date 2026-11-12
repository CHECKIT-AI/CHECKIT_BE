-- Apply once to an existing CheckIt database as the schema owner.
-- Existing results keep NULL: their document presence was not assessed separately.
BEGIN;
ALTER TABLE checkit.check_items
    ADD COLUMN IF NOT EXISTS document_presence text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'checkit.check_items'::regclass
          AND conname = 'check_items_document_presence_check'
    ) THEN
        ALTER TABLE checkit.check_items
            ADD CONSTRAINT check_items_document_presence_check
            CHECK (document_presence IN ('PRESENT', 'ABSENT', 'UNCLEAR'));
    END IF;
END
$$;
COMMIT;
