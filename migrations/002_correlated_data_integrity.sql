BEGIN;

-- ETVS audit runs are only meaningful when the complete correlated data chain
-- exists for every polling station in the selected election scope.
--
-- This trigger deliberately checks completeness before audit_runs can be
-- created. Mathematical inconsistencies (for example turnout > registered
-- voters) are still handled by the audit rules; this guard only prevents
-- incomplete/null/cross-contest records from entering the audit engine.

CREATE OR REPLACE FUNCTION etvs_validate_audit_run_data()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    station_count INTEGER;
    complete_station_count INTEGER;
    missing_station TEXT;
    missing_position TEXT;
BEGIN
    SELECT COUNT(*)
      INTO station_count
      FROM polling_stations ps
     WHERE ps.election_id = NEW.election_id
       AND (
            NEW.scope_level IS NULL
            OR (NEW.scope_level = 'COUNTY' AND EXISTS (
                SELECT 1
                  FROM registration_centres rc
                  JOIN wards w ON w.ward_id = rc.ward_id
                  JOIN constituencies c ON c.constituency_id = w.constituency_id
                 WHERE rc.registration_centre_id = ps.registration_centre_id
                   AND c.county_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'CONSTITUENCY' AND EXISTS (
                SELECT 1
                  FROM registration_centres rc
                  JOIN wards w ON w.ward_id = rc.ward_id
                 WHERE rc.registration_centre_id = ps.registration_centre_id
                   AND w.constituency_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'WARD' AND EXISTS (
                SELECT 1
                  FROM registration_centres rc
                 WHERE rc.registration_centre_id = ps.registration_centre_id
                   AND rc.ward_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'POLLING_STATION' AND ps.polling_station_id = NEW.scope_id)
       );

    IF station_count = 0 THEN
        RAISE EXCEPTION
            'ETVS audit blocked: scope contains no polling stations for election %',
            NEW.election_id;
    END IF;

    SELECT ps.polling_station_id
      INTO missing_station
      FROM polling_stations ps
     WHERE ps.election_id = NEW.election_id
       AND (
            NEW.scope_level IS NULL
            OR (NEW.scope_level = 'COUNTY' AND EXISTS (
                SELECT 1 FROM registration_centres rc
                JOIN wards w ON w.ward_id = rc.ward_id
                JOIN constituencies c ON c.constituency_id = w.constituency_id
                WHERE rc.registration_centre_id = ps.registration_centre_id
                  AND c.county_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'CONSTITUENCY' AND EXISTS (
                SELECT 1 FROM registration_centres rc
                JOIN wards w ON w.ward_id = rc.ward_id
                WHERE rc.registration_centre_id = ps.registration_centre_id
                  AND w.constituency_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'WARD' AND EXISTS (
                SELECT 1 FROM registration_centres rc
                WHERE rc.registration_centre_id = ps.registration_centre_id
                  AND rc.ward_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'POLLING_STATION' AND ps.polling_station_id = NEW.scope_id)
       )
       AND NOT EXISTS (
            SELECT 1
              FROM registered_voter_observations rv
             WHERE rv.election_id = ps.election_id
               AND rv.polling_station_id = ps.polling_station_id
       )
     LIMIT 1;

    IF missing_station IS NOT NULL THEN
        RAISE EXCEPTION
            'ETVS audit blocked: polling station % has no registered-voter observation',
            missing_station;
    END IF;

    SELECT ps.polling_station_id
      INTO missing_station
      FROM polling_stations ps
     WHERE ps.election_id = NEW.election_id
       AND (
            NEW.scope_level IS NULL
            OR (NEW.scope_level = 'COUNTY' AND EXISTS (
                SELECT 1 FROM registration_centres rc
                JOIN wards w ON w.ward_id = rc.ward_id
                JOIN constituencies c ON c.constituency_id = w.constituency_id
                WHERE rc.registration_centre_id = ps.registration_centre_id
                  AND c.county_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'CONSTITUENCY' AND EXISTS (
                SELECT 1 FROM registration_centres rc
                JOIN wards w ON w.ward_id = rc.ward_id
                WHERE rc.registration_centre_id = ps.registration_centre_id
                  AND w.constituency_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'WARD' AND EXISTS (
                SELECT 1 FROM registration_centres rc
                WHERE rc.registration_centre_id = ps.registration_centre_id
                  AND rc.ward_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'POLLING_STATION' AND ps.polling_station_id = NEW.scope_id)
       )
       AND NOT EXISTS (
            SELECT 1
              FROM turnout_observations t
             WHERE t.election_id = ps.election_id
               AND t.polling_station_id = ps.polling_station_id
       )
     LIMIT 1;

    IF missing_station IS NOT NULL THEN
        RAISE EXCEPTION
            'ETVS audit blocked: polling station % has no turnout observation',
            missing_station;
    END IF;

    -- Every selected station must have exactly one latest record for each of
    -- the six contest positions. The audit engine then evaluates those records.
    SELECT ps.polling_station_id
      INTO missing_station
      FROM polling_stations ps
     WHERE ps.election_id = NEW.election_id
       AND (
            NEW.scope_level IS NULL
            OR (NEW.scope_level = 'POLLING_STATION' AND ps.polling_station_id = NEW.scope_id)
            OR (NEW.scope_level = 'WARD' AND EXISTS (
                SELECT 1 FROM registration_centres rc
                WHERE rc.registration_centre_id = ps.registration_centre_id AND rc.ward_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'CONSTITUENCY' AND EXISTS (
                SELECT 1 FROM registration_centres rc JOIN wards w ON w.ward_id = rc.ward_id
                WHERE rc.registration_centre_id = ps.registration_centre_id AND w.constituency_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'COUNTY' AND EXISTS (
                SELECT 1 FROM registration_centres rc JOIN wards w ON w.ward_id = rc.ward_id
                JOIN constituencies c ON c.constituency_id = w.constituency_id
                WHERE rc.registration_centre_id = ps.registration_centre_id AND c.county_id = NEW.scope_id
            ))
       )
       AND EXISTS (
            SELECT 1 FROM positions p
            WHERE NOT EXISTS (
                SELECT 1
                  FROM ballot_accounting_observations b
                 WHERE b.election_id = ps.election_id
                   AND b.polling_station_id = ps.polling_station_id
                   AND b.position_id = p.position_id
            )
       )
     LIMIT 1;

    IF missing_station IS NOT NULL THEN
        RAISE EXCEPTION
            'ETVS audit blocked: polling station % is missing one or more of the six contest ballot-accounting streams',
            missing_station;
    END IF;

    -- Each contest ballot stream must explicitly point to the station's latest
    -- turnout observation. This prevents accidental double-counting or mixing
    -- turnout versions across the six ballot papers.
    SELECT ps.polling_station_id
      INTO missing_station
      FROM polling_stations ps
     WHERE ps.election_id = NEW.election_id
       AND (
            NEW.scope_level IS NULL
            OR (NEW.scope_level = 'POLLING_STATION' AND ps.polling_station_id = NEW.scope_id)
            OR (NEW.scope_level = 'WARD' AND EXISTS (
                SELECT 1 FROM registration_centres rc WHERE rc.registration_centre_id = ps.registration_centre_id AND rc.ward_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'CONSTITUENCY' AND EXISTS (
                SELECT 1 FROM registration_centres rc JOIN wards w ON w.ward_id = rc.ward_id WHERE rc.registration_centre_id = ps.registration_centre_id AND w.constituency_id = NEW.scope_id
            ))
            OR (NEW.scope_level = 'COUNTY' AND EXISTS (
                SELECT 1 FROM registration_centres rc JOIN wards w ON w.ward_id = rc.ward_id JOIN constituencies c ON c.constituency_id = w.constituency_id WHERE rc.registration_centre_id = ps.registration_centre_id AND c.county_id = NEW.scope_id
            ))
       )
       AND EXISTS (
            SELECT 1
              FROM ballot_accounting_observations b
             WHERE b.election_id = ps.election_id
               AND b.polling_station_id = ps.polling_station_id
               AND b.position_id IS NOT NULL
               AND b.turnout_observation_id IS NULL
       )
     LIMIT 1;

    IF missing_station IS NOT NULL THEN
        RAISE EXCEPTION
            'ETVS audit blocked: polling station % has ballot accounting without a shared turnout_observation_id',
            missing_station;
    END IF;

    SELECT b.position_id
      INTO missing_position
      FROM polling_stations ps
      JOIN ballot_accounting_observations b
        ON b.election_id = ps.election_id
       AND b.polling_station_id = ps.polling_station_id
     WHERE ps.election_id = NEW.election_id
       AND b.position_id IS NOT NULL
       AND b.turnout_observation_id <> (
            SELECT t.turnout_observation_id
              FROM turnout_observations t
             WHERE t.election_id = ps.election_id
               AND t.polling_station_id = ps.polling_station_id
             ORDER BY t.observation_version DESC
             LIMIT 1
       )
     LIMIT 1;

    IF missing_position IS NOT NULL THEN
        RAISE EXCEPTION
            'ETVS audit blocked: ballot accounting position % does not reference the station final turnout observation',
            missing_position;
    END IF;

    -- Candidate results must exist for every contest/candidate combination.
    SELECT ps.polling_station_id
      INTO missing_station
      FROM polling_stations ps
      WHERE ps.election_id = NEW.election_id
        AND EXISTS (
            SELECT 1
              FROM positions p
              JOIN candidates c
                ON c.election_id = ps.election_id
               AND c.position_id = p.position_id
             WHERE NOT EXISTS (
                SELECT 1
                  FROM result_submissions rs
                 WHERE rs.election_id = ps.election_id
                   AND rs.polling_station_id = ps.polling_station_id
                   AND rs.candidate_id = c.candidate_id
                   AND rs.position_id = p.position_id
             )
        )
        AND (
            NEW.scope_level IS NULL
            OR (NEW.scope_level = 'POLLING_STATION' AND ps.polling_station_id = NEW.scope_id)
            OR (NEW.scope_level = 'WARD' AND EXISTS (SELECT 1 FROM registration_centres rc WHERE rc.registration_centre_id=ps.registration_centre_id AND rc.ward_id=NEW.scope_id))
            OR (NEW.scope_level = 'CONSTITUENCY' AND EXISTS (SELECT 1 FROM registration_centres rc JOIN wards w ON w.ward_id=rc.ward_id WHERE rc.registration_centre_id=ps.registration_centre_id AND w.constituency_id=NEW.scope_id))
            OR (NEW.scope_level = 'COUNTY' AND EXISTS (SELECT 1 FROM registration_centres rc JOIN wards w ON w.ward_id=rc.ward_id JOIN constituencies c ON c.constituency_id=w.constituency_id WHERE rc.registration_centre_id=ps.registration_centre_id AND c.county_id=NEW.scope_id))
        )
      LIMIT 1;

    IF missing_station IS NOT NULL THEN
        RAISE EXCEPTION
            'ETVS audit blocked: polling station % is missing one or more candidate result streams',
            missing_station;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_audit_run_data ON audit_runs;
CREATE TRIGGER trg_validate_audit_run_data
BEFORE INSERT ON audit_runs
FOR EACH ROW
EXECUTE FUNCTION etvs_validate_audit_run_data();

COMMIT;
