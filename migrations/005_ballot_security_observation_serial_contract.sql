BEGIN;

-- Security-feature observations are batch/station evidence by default.
-- Serialized-ballot evidence is enforced by the audit engine (R018/R019)
-- and by ballot_units.counterfoil/serial constraints. A PostgreSQL CHECK
-- cannot safely inspect ballot_security_features via a subquery.
ALTER TABLE ballot_security_observations
    DROP CONSTRAINT IF EXISTS ballot_security_observation_serial_check;

COMMIT;
