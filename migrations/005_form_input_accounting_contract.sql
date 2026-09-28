-- ETVS Migration 005: form-driven source entry and contest accounting contract

-- Human source entry is limited to polling-station details, station turnout,
-- contest-specific candidate results and contest-specific ballot accounting.
--
-- Accounting identity:
--   turnout = valid_votes + rejected_votes
--   valid_votes = SUM(latest candidate votes for the contest)
--   spoilt_ballots are tracked separately and are NEVER part of turnout.

ALTER TABLE turnout_observations
    ADD COLUMN IF NOT EXISTS input_hash TEXT,
    ADD COLUMN IF NOT EXISTS hash_algorithm TEXT NOT NULL DEFAULT 'BLAKE3-256';

ALTER TABLE ballot_accounting_observations
    ADD COLUMN IF NOT EXISTS input_hash TEXT,
    ADD COLUMN IF NOT EXISTS hash_algorithm TEXT NOT NULL DEFAULT 'BLAKE3-256';

ALTER TABLE turnout_observations
    DROP CONSTRAINT IF EXISTS turnout_input_hash_format;

ALTER TABLE turnout_observations
    ADD CONSTRAINT turnout_input_hash_format
    CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$');

ALTER TABLE turnout_observations
    DROP CONSTRAINT IF EXISTS turnout_hash_algorithm_check;

ALTER TABLE turnout_observations
    ADD CONSTRAINT turnout_hash_algorithm_check
    CHECK (hash_algorithm = 'BLAKE3-256');

ALTER TABLE ballot_accounting_observations
    DROP CONSTRAINT IF EXISTS ballot_input_hash_format;

ALTER TABLE ballot_accounting_observations
    ADD CONSTRAINT ballot_input_hash_format
    CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$');

ALTER TABLE ballot_accounting_observations
    DROP CONSTRAINT IF EXISTS ballot_hash_algorithm_check;

ALTER TABLE ballot_accounting_observations
    ADD CONSTRAINT ballot_hash_algorithm_check
    CHECK (hash_algorithm = 'BLAKE3-256');

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ballot_accounting_observations
        WHERE position_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot enforce form contract: ballot_accounting_observations contains rows with NULL position_id';
    END IF;

    ALTER TABLE ballot_accounting_observations
        ALTER COLUMN position_id SET NOT NULL;
END $$;

CREATE OR REPLACE FUNCTION etvs_validate_contest_accounting()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_election_id TEXT;
    v_station_id TEXT;
    v_position_id TEXT;
    v_turnout INTEGER;
    v_valid INTEGER;
    v_rejected INTEGER;
    v_candidate_total INTEGER;
    v_result_count INTEGER;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_election_id := OLD.election_id;
        v_station_id := OLD.polling_station_id;
        v_position_id := OLD.position_id;
    ELSE
        v_election_id := NEW.election_id;
        v_station_id := NEW.polling_station_id;
        v_position_id := NEW.position_id;
    END IF;

    IF v_position_id IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT t.voters_turnout
      INTO v_turnout
      FROM turnout_observations t
     WHERE t.election_id = v_election_id
       AND t.polling_station_id = v_station_id
     ORDER BY t.observation_version DESC
     LIMIT 1;

    SELECT b.valid_votes, b.rejected_votes
      INTO v_valid, v_rejected
      FROM ballot_accounting_observations b
     WHERE b.election_id = v_election_id
       AND b.polling_station_id = v_station_id
       AND b.position_id = v_position_id
     ORDER BY b.observation_version DESC
     LIMIT 1;

    IF v_turnout IS NULL OR v_valid IS NULL OR v_rejected IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT COUNT(*), COALESCE(SUM(r.votes), 0)
      INTO v_result_count, v_candidate_total
      FROM (
          SELECT DISTINCT ON (candidate_id) candidate_id, votes
            FROM result_submissions
           WHERE election_id = v_election_id
             AND polling_station_id = v_station_id
             AND position_id = v_position_id
           ORDER BY candidate_id, result_version DESC
      ) r;

    IF v_result_count = 0 THEN
        RAISE EXCEPTION
            'Contest accounting requires candidate results: station %, position %',
            v_station_id, v_position_id;
    END IF;

    IF v_valid <> v_candidate_total THEN
        RAISE EXCEPTION
            'Invalid contest accounting for station %, position %: valid_votes (%) must equal total candidate votes (%)',
            v_station_id, v_position_id, v_valid, v_candidate_total;
    END IF;

    IF v_turnout <> v_valid + v_rejected THEN
        RAISE EXCEPTION
            'Invalid contest accounting for station %, position %: turnout (%) must equal valid_votes (%) + rejected_votes (%)',
            v_station_id, v_position_id, v_turnout, v_valid, v_rejected;
    END IF;

    -- Spoilt ballots are deliberately absent from both identities.
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_contest_accounting_results
    ON result_submissions;

CREATE CONSTRAINT TRIGGER trg_validate_contest_accounting_results
AFTER INSERT OR UPDATE OR DELETE ON result_submissions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION etvs_validate_contest_accounting();

DROP TRIGGER IF EXISTS trg_validate_contest_accounting_ballots
    ON ballot_accounting_observations;

CREATE CONSTRAINT TRIGGER trg_validate_contest_accounting_ballots
AFTER INSERT OR UPDATE OR DELETE ON ballot_accounting_observations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION etvs_validate_contest_accounting();

COMMENT ON FUNCTION etvs_validate_contest_accounting() IS
'ETVS form-entry contract: turnout = valid + rejected; valid = latest candidate-vote total; spoilt ballots are never counted as cast.';
