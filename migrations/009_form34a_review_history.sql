-- ETVS Migration 009: Form 34A review attribution and append-only review events.
--
-- The reviewer name is an operator-entered attribution for the local workflow,
-- not authenticated identity. A later server deployment must add access control.

ALTER TABLE form34a_observations
    ADD COLUMN IF NOT EXISTS reviewed_by TEXT,
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS review_notes TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname='form34a_review_metadata_check'
          AND conrelid='form34a_observations'::regclass
    ) THEN
        ALTER TABLE form34a_observations
            ADD CONSTRAINT form34a_review_metadata_check CHECK (
                (review_status='REVIEWED'
                 AND reviewed_by IS NOT NULL
                 AND length(trim(reviewed_by))>0
                 AND reviewed_at IS NOT NULL)
                OR
                (review_status<>'REVIEWED' AND reviewed_at IS NULL)
            );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS form34a_review_events (
    form34a_review_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form34a_observation_id BIGINT NOT NULL,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    previous_review_status TEXT NOT NULL
        CHECK(previous_review_status IN ('UNREVIEWED','IN_REVIEW','REVIEWED','NEEDS_CORRECTION','CONFLICTING_COPY')),
    new_review_status TEXT NOT NULL CHECK(new_review_status='REVIEWED'),
    reviewer_name TEXT NOT NULL CHECK(length(trim(reviewer_name))>0),
    review_notes TEXT,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_form34a_review_event_observation
        FOREIGN KEY(form34a_observation_id,election_id)
        REFERENCES form34a_observations(form34a_observation_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_form34a_review_events_observation
    ON form34a_review_events(form34a_observation_id,reviewed_at DESC);

COMMENT ON TABLE form34a_review_events IS
'Append-only review history for Form 34A extraction. Reviewer names are self-reported until authentication is introduced.';
