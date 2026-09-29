-- ETVS Migration 006: enforce station turnout reporting intervals
--
-- Turnout is an observed station-wide value. Each polling station has an
-- ETVS-configured minimum interval between successive observations.
-- This is a project data-collection/audit policy, not a claim about a
-- universal IEBC reporting interval.

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
     ORDER BY observation_version DESC
     LIMIT 1;

    IF v_previous IS NOT NULL
       AND NEW.observed_at < v_previous + make_interval(mins => v_interval) THEN
        RAISE EXCEPTION
            'Turnout observation interval violation for station %: minimum interval is % minutes; previous observation was at %, new observation is at %',
            NEW.polling_station_id, v_interval, v_previous, NEW.observed_at;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_turnout_interval
    ON turnout_observations;

CREATE TRIGGER trg_validate_turnout_interval
BEFORE INSERT ON turnout_observations
FOR EACH ROW
EXECUTE FUNCTION etvs_validate_turnout_interval();

COMMENT ON FUNCTION etvs_validate_turnout_interval() IS
'ETVS input contract: successive station turnout observations must respect the station-specific configured minimum interval.';
