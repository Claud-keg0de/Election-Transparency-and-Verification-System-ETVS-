-- ETVS migration 004: anonymous ballot units and counterfoil accountability
-- Applies the canonical ballot-security model without replacing its normalized
-- ballot specifications, security features, or security observations.

CREATE TABLE IF NOT EXISTS registered_voter_observations (
    registered_voter_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    observation_version INTEGER NOT NULL DEFAULT 1,
    registered_voters INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT REFERENCES source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_registered_voter_observation_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT registered_voter_observation_version_positive CHECK (observation_version > 0),
    CONSTRAINT registered_voter_observation_non_negative CHECK (registered_voters >= 0),
    CONSTRAINT unique_registered_voter_observation_version
        UNIQUE (election_id, polling_station_id, observation_version)
);

CREATE INDEX IF NOT EXISTS idx_registered_voter_observations_latest
    ON registered_voter_observations(election_id, polling_station_id, observation_version DESC);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'unique_ballot_batch_context'
    ) THEN
        ALTER TABLE ballot_stock_batches
            ADD CONSTRAINT unique_ballot_batch_context
            UNIQUE (ballot_batch_id, election_id, polling_station_id, position_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS ballot_units (
    ballot_unit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    position_id TEXT NOT NULL REFERENCES positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    ballot_batch_id BIGINT NOT NULL,
    ballot_serial_number TEXT NOT NULL,
    counterfoil_serial_number TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ALLOCATED',
    issued_at TIMESTAMPTZ,
    cast_at TIMESTAMPTZ,
    source_document_id BIGINT REFERENCES source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_ballot_unit_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_ballot_unit_batch_context
        FOREIGN KEY (ballot_batch_id, election_id, polling_station_id, position_id)
        REFERENCES ballot_stock_batches(ballot_batch_id, election_id, polling_station_id, position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ballot_unit_serials_present
        CHECK (length(trim(ballot_serial_number)) > 0
            AND length(trim(counterfoil_serial_number)) > 0),
    CONSTRAINT ballot_unit_counterfoil_match
        CHECK (ballot_serial_number = counterfoil_serial_number),
    CONSTRAINT ballot_unit_status_check
        CHECK (status IN (
            'ALLOCATED','ISSUED','CAST','COUNTED',
            'UNUSED','REJECTED','SPOILT','CANCELLED'
        )),
    CONSTRAINT unique_ballot_unit_serial
        UNIQUE (election_id, position_id, ballot_serial_number),
    CONSTRAINT unique_ballot_unit_counterfoil
        UNIQUE (election_id, position_id, counterfoil_serial_number)
);

CREATE INDEX IF NOT EXISTS idx_ballot_units_station_position
    ON ballot_units(election_id, polling_station_id, position_id);
