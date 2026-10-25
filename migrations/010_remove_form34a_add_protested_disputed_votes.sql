-- ETVS migration 010: remove the dedicated Form 34A feature and add register vote categories.
-- Generic sources/source_documents remain available for provenance.
-- Existing Form 34A-specific records are intentionally dropped by this migration.
BEGIN;
DROP TABLE IF EXISTS form34a_review_events CASCADE;
DROP TABLE IF EXISTS form34a_disputed_vote_decisions CASCADE;
DROP TABLE IF EXISTS form34a_candidate_votes CASCADE;
DROP TABLE IF EXISTS form34a_observations CASCADE;
DELETE FROM etvs_input_scope WHERE input_area='FORM34A_EVIDENCE';
ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS protested_votes INTEGER NOT NULL DEFAULT 0 CHECK(protested_votes>=0);
ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS disputed_votes INTEGER NOT NULL DEFAULT 0 CHECK(disputed_votes>=0);
COMMIT;
