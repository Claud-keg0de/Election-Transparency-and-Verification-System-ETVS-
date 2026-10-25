-- ETVS Migration 008: Form 34A evidence and position-specific turnout.
--
-- Historical station-wide turnout rows are retained with position_id NULL.
-- New observations must be scoped to a position so the six ballot streams are
-- not accidentally treated as one electorate or forced to share one count.

ALTER TABLE turnout_observations
    ADD COLUMN IF NOT EXISTS position_id TEXT
    REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE turnout_observations
    DROP CONSTRAINT IF EXISTS unique_turnout_observation_version;

CREATE UNIQUE INDEX IF NOT EXISTS uq_turnout_station_position_version
    ON turnout_observations(election_id,polling_station_id,position_id,observation_version)
    WHERE position_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_turnout_legacy_station_version
    ON turnout_observations(election_id,polling_station_id,observation_version)
    WHERE position_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_turnout_latest_by_position
    ON turnout_observations(election_id,polling_station_id,position_id,observation_version DESC);

-- Form 34A does not carry a distinct spoilt-ballot count. NULL now means that
-- this particular source did not report it; it must not be coerced to zero.
ALTER TABLE ballot_accounting_observations
    ALTER COLUMN spoilt_ballots DROP NOT NULL;

-- A station can have separate turnout streams for president, governor,
-- senator, women representative, MP and MCA. The collection interval is
-- enforced independently inside each station/position stream.
CREATE OR REPLACE FUNCTION etvs_validate_turnout_interval()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_interval INTEGER;
    v_previous TIMESTAMPTZ;
BEGIN
    SELECT turnout_reporting_interval_minutes
      INTO v_interval
      FROM polling_stations
     WHERE polling_station_id = NEW.polling_station_id
       AND election_id = NEW.election_id;

    IF v_interval IS NULL THEN
        RAISE EXCEPTION
            'Polling station % does not exist for election %',
            NEW.polling_station_id, NEW.election_id;
    END IF;

    SELECT observed_at
      INTO v_previous
      FROM turnout_observations
     WHERE election_id = NEW.election_id
       AND polling_station_id = NEW.polling_station_id
       AND position_id IS NOT DISTINCT FROM NEW.position_id
     ORDER BY observation_version DESC
     LIMIT 1;

    IF v_previous IS NOT NULL
       AND NEW.observed_at < v_previous + make_interval(mins => v_interval) THEN
        RAISE EXCEPTION
            'Turnout interval violation for station %, position %: minimum % minutes; previous %, new %',
            NEW.polling_station_id, COALESCE(NEW.position_id,'LEGACY-STATION-WIDE'),
            v_interval, v_previous, NEW.observed_at;
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION etvs_validate_turnout_interval() IS
'ETVS collection policy: successive turnout observations must respect the configured interval within the same polling-station and electoral-position stream.';

-- Form-specific evidence is stored independently from the current normalized
-- input tables so conflicting or incomplete published figures remain auditable.
CREATE TABLE IF NOT EXISTS form34a_observations (
    form34a_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    observation_version INTEGER NOT NULL CHECK(observation_version > 0),
    printed_form_serial TEXT,
    printed_station_code TEXT,
    printed_station_name TEXT,
    printed_ward_name TEXT,
    printed_constituency_name TEXT,
    printed_county_name TEXT,
    registered_voters_reported INTEGER CHECK(registered_voters_reported IS NULL OR registered_voters_reported >= 0),
    registered_voters_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(registered_voters_status IN ('PRESENT','BLANK','ILLEGIBLE','NOT_CAPTURED')),
    candidate_table_valid_total_reported INTEGER CHECK(candidate_table_valid_total_reported IS NULL OR candidate_table_valid_total_reported >= 0),
    candidate_table_valid_total_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(candidate_table_valid_total_status IN ('PRESENT','BLANK','ILLEGIBLE','NOT_CAPTURED')),
    rejected_ballots_reported INTEGER CHECK(rejected_ballots_reported IS NULL OR rejected_ballots_reported >= 0),
    rejected_ballots_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(rejected_ballots_status IN ('PRESENT','BLANK','ILLEGIBLE','NOT_CAPTURED')),
    rejection_objected_to_reported INTEGER CHECK(rejection_objected_to_reported IS NULL OR rejection_objected_to_reported >= 0),
    rejection_objected_to_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(rejection_objected_to_status IN ('PRESENT','BLANK','ILLEGIBLE','NOT_CAPTURED')),
    disputed_votes_reported INTEGER CHECK(disputed_votes_reported IS NULL OR disputed_votes_reported >= 0),
    disputed_votes_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(disputed_votes_status IN ('PRESENT','BLANK','ILLEGIBLE','NOT_CAPTURED')),
    counts_valid_total_reported INTEGER CHECK(counts_valid_total_reported IS NULL OR counts_valid_total_reported >= 0),
    counts_valid_total_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(counts_valid_total_status IN ('PRESENT','BLANK','ILLEGIBLE','NOT_CAPTURED')),
    presiding_officer_signature_status TEXT NOT NULL DEFAULT 'NOT_REVIEWED'
        CHECK(presiding_officer_signature_status IN ('SIGNED','NOT_SIGNED','ILLEGIBLE','NOT_REVIEWED')),
    deputy_presiding_officer_signature_status TEXT NOT NULL DEFAULT 'NOT_REVIEWED'
        CHECK(deputy_presiding_officer_signature_status IN ('SIGNED','NOT_SIGNED','ILLEGIBLE','NOT_REVIEWED')),
    disputed_detail_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(disputed_detail_status IN ('COMPLETE','PARTIAL','NOT_CAPTURED','NOT_APPLICABLE')),
    extraction_method TEXT NOT NULL DEFAULT 'MANUAL'
        CHECK(extraction_method IN ('MANUAL','OCR_ASSISTED','OCR','OTHER')),
    review_status TEXT NOT NULL DEFAULT 'UNREVIEWED'
        CHECK(review_status IN ('UNREVIEWED','IN_REVIEW','REVIEWED','NEEDS_CORRECTION','CONFLICTING_COPY')),
    source_page INTEGER CHECK(source_page IS NULL OR source_page > 0),
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_form34a_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT uq_form34a_station_version UNIQUE(election_id,polling_station_id,observation_version),
    CONSTRAINT uq_form34a_observation_election UNIQUE(form34a_observation_id,election_id),
    CONSTRAINT form34a_registered_capture CHECK(
        (registered_voters_status='PRESENT' AND registered_voters_reported IS NOT NULL) OR
        (registered_voters_status<>'PRESENT' AND registered_voters_reported IS NULL)),
    CONSTRAINT form34a_candidate_total_capture CHECK(
        (candidate_table_valid_total_status='PRESENT' AND candidate_table_valid_total_reported IS NOT NULL) OR
        (candidate_table_valid_total_status<>'PRESENT' AND candidate_table_valid_total_reported IS NULL)),
    CONSTRAINT form34a_rejected_capture CHECK(
        (rejected_ballots_status='PRESENT' AND rejected_ballots_reported IS NOT NULL) OR
        (rejected_ballots_status<>'PRESENT' AND rejected_ballots_reported IS NULL)),
    CONSTRAINT form34a_rejection_objected_capture CHECK(
        (rejection_objected_to_status='PRESENT' AND rejection_objected_to_reported IS NOT NULL) OR
        (rejection_objected_to_status<>'PRESENT' AND rejection_objected_to_reported IS NULL)),
    CONSTRAINT form34a_disputed_capture CHECK(
        (disputed_votes_status='PRESENT' AND disputed_votes_reported IS NOT NULL) OR
        (disputed_votes_status<>'PRESENT' AND disputed_votes_reported IS NULL)),
    CONSTRAINT form34a_counts_valid_capture CHECK(
        (counts_valid_total_status='PRESENT' AND counts_valid_total_reported IS NOT NULL) OR
        (counts_valid_total_status<>'PRESENT' AND counts_valid_total_reported IS NULL))
);

CREATE TABLE IF NOT EXISTS form34a_candidate_votes (
    form34a_candidate_vote_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form34a_observation_id BIGINT NOT NULL,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    row_number INTEGER NOT NULL CHECK(row_number > 0),
    candidate_id TEXT,
    candidate_name_printed TEXT NOT NULL DEFAULT '',
    votes_reported INTEGER CHECK(votes_reported IS NULL OR votes_reported >= 0),
    votes_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(votes_status IN ('PRESENT','BLANK','ILLEGIBLE','NOT_CAPTURED')),
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_form34a_candidate_observation
        FOREIGN KEY(form34a_observation_id,election_id)
        REFERENCES form34a_observations(form34a_observation_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_form34a_candidate_election
        FOREIGN KEY(candidate_id,election_id)
        REFERENCES candidates(candidate_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT uq_form34a_candidate_row UNIQUE(form34a_observation_id,row_number),
    CONSTRAINT form34a_candidate_vote_capture CHECK(
        (votes_status='PRESENT' AND votes_reported IS NOT NULL) OR
        (votes_status<>'PRESENT' AND votes_reported IS NULL))
);

CREATE TABLE IF NOT EXISTS form34a_disputed_vote_decisions (
    form34a_disputed_decision_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form34a_observation_id BIGINT NOT NULL,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    row_number INTEGER NOT NULL CHECK(row_number > 0),
    ballot_serial_number TEXT,
    serial_capture_status TEXT NOT NULL DEFAULT 'NOT_CAPTURED'
        CHECK(serial_capture_status IN ('PRESENT','ILLEGIBLE','NOT_CAPTURED')),
    assigned_candidate_id TEXT,
    assigned_candidate_name_printed TEXT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_form34a_disputed_observation
        FOREIGN KEY(form34a_observation_id,election_id)
        REFERENCES form34a_observations(form34a_observation_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_form34a_disputed_candidate
        FOREIGN KEY(assigned_candidate_id,election_id)
        REFERENCES candidates(candidate_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT uq_form34a_disputed_row UNIQUE(form34a_observation_id,row_number),
    CONSTRAINT form34a_disputed_serial_capture CHECK(
        (serial_capture_status='PRESENT' AND ballot_serial_number IS NOT NULL AND length(trim(ballot_serial_number))>0) OR
        (serial_capture_status<>'PRESENT' AND ballot_serial_number IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_form34a_station_latest
    ON form34a_observations(election_id,polling_station_id,observation_version DESC);
CREATE INDEX IF NOT EXISTS idx_form34a_source_document
    ON form34a_observations(source_document_id);
CREATE INDEX IF NOT EXISTS idx_form34a_candidate_lookup
    ON form34a_candidate_votes(form34a_observation_id,row_number);
CREATE INDEX IF NOT EXISTS idx_form34a_disputed_lookup
    ON form34a_disputed_vote_decisions(form34a_observation_id,row_number);

INSERT INTO etvs_input_scope(input_area,enabled,description) VALUES
('FORM34A_EVIDENCE',TRUE,'Preserve uploaded Form 34A evidence and reviewed field-level observations.'),
('POSITION_TURNOUT_OBSERVATION',TRUE,'Record an independent turnout observation for each polling station and electoral position.')
ON CONFLICT(input_area) DO UPDATE SET enabled=EXCLUDED.enabled,description=EXCLUDED.description;

UPDATE etvs_input_scope
   SET description='Versioned turnout/voters-cast observations recorded separately for each polling-station and electoral-position stream.'
 WHERE input_area='TURNOUT_OBSERVATION';

COMMENT ON TABLE form34a_observations IS
'Versioned extraction of a Form 34A source document; reported values and capture states remain distinct from normalized contest inputs and audit findings.';
COMMENT ON TABLE form34a_candidate_votes IS
'One row per candidate line transcribed from Form 34A; printed name and nullable canonical candidate mapping are both retained.';
COMMENT ON TABLE form34a_disputed_vote_decisions IS
'Disputed-ballot decision rows transcribed from Form 34A, including serial and assigned-candidate evidence where legible.';
