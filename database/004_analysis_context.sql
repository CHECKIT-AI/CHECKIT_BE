-- Apply once to an existing database, using its owner/admin migration connection.
-- Do not rerun the initial schema or backend role provisioning.
BEGIN;
ALTER TABLE checkit.analysis_jobs
    ADD COLUMN IF NOT EXISTS analysis_context jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE checkit.check_items
    ADD COLUMN IF NOT EXISTS rule_candidate jsonb NOT NULL DEFAULT '{}'::jsonb;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'checkit.analysis_jobs'::regclass
          AND conname = 'analysis_jobs_analysis_context_object'
    ) THEN
        ALTER TABLE checkit.analysis_jobs
            ADD CONSTRAINT analysis_jobs_analysis_context_object
            CHECK (jsonb_typeof(analysis_context) = 'object');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'checkit.check_items'::regclass
          AND conname = 'check_items_rule_candidate_object'
    ) THEN
        ALTER TABLE checkit.check_items
            ADD CONSTRAINT check_items_rule_candidate_object
            CHECK (jsonb_typeof(rule_candidate) = 'object');
    END IF;
END;
$$;
COMMIT;
