/*
ETVS migration 001

Purpose:
1. Keep TURNOUT as one polling-station voter-count observation shared by all six contests.
2. Version registered-voter observations as source evidence.
3. Make ballot accounting contest/position-specific.
4. Record the ETVS ballot/tally mapping and a configurable observation sequence.
5. Require a source document for every source observation/submission.

IMPORTANT:
- A spoilt ballot is not a voter turnout. A replacement ballot is issued to the
  same voter; the cancelled spoilt paper must therefore remain separately
  recorded and must not be added to turnout.
- For a contest, the accounting identity used by ETVS is:
      valid_votes + rejected_votes = turnout
  with spoilt_ballots tracked separately.
  This deliberately avoids treating a cancelled spoilt ballot as another voter.
*/

BEGIN;

/* -------------------------------------------------------------------------- */
/* 1. Registered-voter observations                                            */
/* -------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS registered_voter_observations (
    registered_voter_observation_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL,
    polling_station_id TEXT NOT NULL,
    observation_version INTEGER NOT NULL DEFAULT 1,
    registered_voters INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT NOT NULL,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_registered_voters_election
        FOREIGN KEY (election_id) REFERENCES elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_registered_voters_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_registered_voters_source_document
        FOREIGN KEY (source_document_id) REFERENCES source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT registered_voters_non_negative CHECK (registered_voters >= 0),
    CONSTRAINT registered_voters_version_positive CHECK (observation_version > 0),
    CONSTRAINT unique_registered_voter_observation_version
        UNIQUE (election_id, polling_station_id, observation_version)
);

CREATE INDEX IF NOT EXISTS idx_registered_voter_latest
    ON registered_voter_observations(election_id, polling_station_id, observation_version DESC);

/* -------------------------------------------------------------------------- */
/* 2. Contest-specific ballot accounting                                      */
/* -------------------------------------------------------------------------- */

ALTER TABLE ballot_accounting_observations
    ADD COLUMN IF NOT EXISTS position_id TEXT;

ALTER TABLE ballot_accounting_observations
    ADD CONSTRAINT fk_ballot_accounting_position
    FOREIGN KEY (position_id) REFERENCES positions(position_id)
    ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE ballot_accounting_observations
    DROP CONSTRAINT IF EXISTS unique_ballot_accounting_observation_version;

ALTER TABLE ballot_accounting_observations
    ADD CONSTRAINT unique_ballot_accounting_position_version
    UNIQUE (election_id, polling_station_id, position_id, observation_version);

CREATE INDEX IF NOT EXISTS idx_ballot_accounting_position_latest
    ON ballot_accounting_observations(
        election_id, polling_station_id, position_id, observation_version DESC
    );

/* Existing rows from the pre-position schema must be explicitly classified.
   The migration refuses to silently guess their contest. */
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ballot_accounting_observations
        WHERE position_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'Migration stopped: existing ballot_accounting_observations have no position_id. Classify each row before continuing.';
    END IF;
END $$;

ALTER TABLE ballot_accounting_observations
    ALTER COLUMN position_id SET NOT NULL;

/* -------------------------------------------------------------------------- */
/* 3. Source provenance is mandatory for source observations                   */
/* -------------------------------------------------------------------------- */

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM turnout_observations WHERE source_document_id IS NULL)
       OR EXISTS (SELECT 1 FROM ballot_accounting_observations WHERE source_document_id IS NULL)
       OR EXISTS (SELECT 1 FROM result_submissions WHERE source_document_id IS NULL)
    THEN
        RAISE EXCEPTION
            'Migration stopped: every turnout, ballot-accounting and result submission must have a source_document_id.';
    END IF;
END $$;

ALTER TABLE turnout_observations
    ALTER COLUMN source_document_id SET NOT NULL;

ALTER TABLE ballot_accounting_observations
    ALTER COLUMN source_document_id SET NOT NULL;

ALTER TABLE result_submissions
    ALTER COLUMN source_document_id SET NOT NULL;

/* -------------------------------------------------------------------------- */
/* 4. Position metadata                                                       */
/* -------------------------------------------------------------------------- */

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS ballot_code TEXT,
    ADD COLUMN IF NOT EXISTS observation_sequence INTEGER;

/*
ETVS ingestion sequence requested for the project:
  1 MCA
  2 MP
  3 WOMEN_REP
  4 SENATOR
  5 GOVERNOR
  6 PRESIDENT

This is an ETVS source-observation/tally-ingestion workflow. It is deliberately
stored as data rather than presented as a legal counting-order assertion.
*/

UPDATE positions SET
    ballot_code = CASE position_id
        WHEN 'POS-MCA' THEN 'WARD-MCA'
        WHEN 'POS-MP' THEN 'CONST-MP'
        WHEN 'POS-WOMEN-REP' THEN 'COUNTY-WR'
        WHEN 'POS-SENATOR' THEN 'COUNTY-SNT'
        WHEN 'POS-GOVERNOR' THEN 'COUNTY-GVN'
        WHEN 'POS-PRESIDENT' THEN 'NATIONAL-PRES'
        ELSE ballot_code
    END,
    observation_sequence = CASE position_id
        WHEN 'POS-MCA' THEN 1
        WHEN 'POS-MP' THEN 2
        WHEN 'POS-WOMEN-REP' THEN 3
        WHEN 'POS-SENATOR' THEN 4
        WHEN 'POS-GOVERNOR' THEN 5
        WHEN 'POS-PRESIDENT' THEN 6
        ELSE observation_sequence
    END;

ALTER TABLE positions
    ADD CONSTRAINT positions_observation_sequence_unique
    UNIQUE (observation_sequence);

/* -------------------------------------------------------------------------- */
/* 5. Useful integrity indexes                                                 */
/* -------------------------------------------------------------------------- */

CREATE INDEX IF NOT EXISTS idx_turnout_observed_at
    ON turnout_observations(election_id, polling_station_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_result_versions_position
    ON result_submissions(election_id, polling_station_id, position_id, result_version DESC);

COMMIT;
