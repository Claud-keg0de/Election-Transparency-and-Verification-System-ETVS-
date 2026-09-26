/*
ETVS migration 001

- Turnout remains ONE polling-station voter-count observation shared by all six contests.
- Registered-voter observations can be versioned with time/source.
- Ballot accounting becomes contest/position-specific.
- Legacy ballot rows are not assigned to a contest automatically.
- Spoilt ballots are tracked separately and are NEVER added to turnout: a replacement
  ballot belongs to the same voter.
- For each contest ETVS reconciles valid + rejected ballots to station turnout;
  spoilt ballots remain a separate audit variable.
*/
BEGIN;

CREATE TABLE IF NOT EXISTS registered_voter_observations (
    registered_voter_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL,
    polling_station_id TEXT NOT NULL,
    observation_version INTEGER NOT NULL DEFAULT 1,
    registered_voters INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (election_id) REFERENCES elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (source_document_id) REFERENCES source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT registered_voters_non_negative CHECK (registered_voters >= 0),
    CONSTRAINT registered_voters_version_positive CHECK (observation_version > 0),
    UNIQUE (election_id, polling_station_id, observation_version)
);

CREATE INDEX IF NOT EXISTS idx_registered_voter_latest
ON registered_voter_observations(election_id, polling_station_id, observation_version DESC);

ALTER TABLE ballot_accounting_observations
    ADD COLUMN IF NOT EXISTS position_id TEXT;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_ballot_accounting_position') THEN
        ALTER TABLE ballot_accounting_observations
        ADD CONSTRAINT fk_ballot_accounting_position
        FOREIGN KEY (position_id) REFERENCES positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

ALTER TABLE ballot_accounting_observations
    DROP CONSTRAINT IF EXISTS unique_ballot_accounting_observation_version;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'unique_ballot_accounting_position_version') THEN
        ALTER TABLE ballot_accounting_observations
        ADD CONSTRAINT unique_ballot_accounting_position_version
        UNIQUE (election_id, polling_station_id, position_id, observation_version);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ballot_accounting_position_latest
ON ballot_accounting_observations(election_id, polling_station_id, position_id, observation_version DESC);

ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS ballot_code TEXT,
    ADD COLUMN IF NOT EXISTS observation_sequence INTEGER;

UPDATE positions SET
    ballot_code = CASE position_id
        WHEN 'POS-MCA' THEN 'WARD-MCA'
        WHEN 'POS-MP' THEN 'CONST-MP'
        WHEN 'POS-WOMEN-REP' THEN 'COUNTY-WR'
        WHEN 'POS-SENATOR' THEN 'COUNTY-SNT'
        WHEN 'POS-GOVERNOR' THEN 'COUNTY-GVN'
        WHEN 'POS-PRESIDENT' THEN 'NATIONAL-PRES'
        ELSE ballot_code END,
    observation_sequence = CASE position_id
        WHEN 'POS-MCA' THEN 1
        WHEN 'POS-MP' THEN 2
        WHEN 'POS-WOMEN-REP' THEN 3
        WHEN 'POS-SENATOR' THEN 4
        WHEN 'POS-GOVERNOR' THEN 5
        WHEN 'POS-PRESIDENT' THEN 6
        ELSE observation_sequence END;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'positions_observation_sequence_unique') THEN
        ALTER TABLE positions ADD CONSTRAINT positions_observation_sequence_unique UNIQUE (observation_sequence);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_turnout_source_document ON turnout_observations(source_document_id);
CREATE INDEX IF NOT EXISTS idx_ballot_source_document ON ballot_accounting_observations(source_document_id);
CREATE INDEX IF NOT EXISTS idx_result_source_document ON result_submissions(source_document_id);
CREATE INDEX IF NOT EXISTS idx_turnout_observed_at ON turnout_observations(election_id, polling_station_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_result_versions_position ON result_submissions(election_id, polling_station_id, position_id, result_version DESC);

COMMIT;
