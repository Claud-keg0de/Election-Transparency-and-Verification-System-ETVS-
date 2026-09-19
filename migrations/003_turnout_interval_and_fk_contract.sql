BEGIN;

-- ETVS station-specific turnout reporting interval.
ALTER TABLE polling_stations
    ADD COLUMN IF NOT EXISTS turnout_reporting_interval_minutes INTEGER;

UPDATE polling_stations
SET turnout_reporting_interval_minutes = 30
WHERE turnout_reporting_interval_minutes IS NULL;

ALTER TABLE polling_stations
    ALTER COLUMN turnout_reporting_interval_minutes SET DEFAULT 30;

ALTER TABLE polling_stations
    ALTER COLUMN turnout_reporting_interval_minutes SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'polling_station_turnout_interval_positive'
    ) THEN
        ALTER TABLE polling_stations
            ADD CONSTRAINT polling_station_turnout_interval_positive
            CHECK (turnout_reporting_interval_minutes BETWEEN 1 AND 1440);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_polling_station_turnout_interval
    ON polling_stations(election_id, polling_station_id, turnout_reporting_interval_minutes);

-- Restore the authoritative foreign-key names used by verify_project.py.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_ballot_position') THEN
        ALTER TABLE ballot_accounting_observations
            ADD CONSTRAINT fk_ballot_position
            FOREIGN KEY (position_id) REFERENCES positions(position_id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_ballot_turnout_observation') THEN
        ALTER TABLE ballot_accounting_observations
            ADD CONSTRAINT fk_ballot_turnout_observation
            FOREIGN KEY (turnout_observation_id)
            REFERENCES turnout_observations(turnout_observation_id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_ballot_security_observation_station_election') THEN
        ALTER TABLE ballot_security_observations
            ADD CONSTRAINT fk_ballot_security_observation_station_election
            FOREIGN KEY (polling_station_id, election_id)
            REFERENCES polling_stations(polling_station_id, election_id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_ballot_security_observation_specification') THEN
        ALTER TABLE ballot_security_observations
            ADD CONSTRAINT fk_ballot_security_observation_specification
            FOREIGN KEY (ballot_specification_id)
            REFERENCES ballot_specifications(ballot_specification_id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_ballot_security_observation_batch') THEN
        ALTER TABLE ballot_security_observations
            ADD CONSTRAINT fk_ballot_security_observation_batch
            FOREIGN KEY (ballot_batch_id)
            REFERENCES ballot_stock_batches(ballot_batch_id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

COMMIT;
