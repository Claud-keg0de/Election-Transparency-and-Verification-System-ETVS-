#!/usr/bin/env bash
set -euo pipefail

# Destructive PG18 development rebuild for ETVS.
# Required safety gate:
#   ETVS_REBUILD_PG18=YES ./tools/rebuild_pg18.sh
#
# Optional:
#   ETVS_PG18_PORT=5433
#   ETVS_SEED=1
#
# The script rebuilds ONLY the database named "etvs" on the selected
# PostgreSQL cluster. It does not touch PostgreSQL 17 on port 5432.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ETVS_PG18_PORT:-5433}"
DB="etvs"

if [[ "${ETVS_REBUILD_PG18:-}" != "YES" ]]; then
  echo "Refusing destructive rebuild."
  echo "Run: ETVS_REBUILD_PG18=YES ETVS_PG18_PORT=$PORT $0"
  exit 2
fi

cd "$ROOT"

echo "=== TARGET ==="
sudo -u postgres psql -p "$PORT" -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT version();"

echo
echo "=== TERMINATE EXISTING ETVS CONNECTIONS ==="
sudo -u postgres psql -p "$PORT" -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid <> pg_backend_pid();"

echo
echo "=== DROP/CREATE CLEAN DATABASE ==="
sudo -u postgres psql -p "$PORT" -d postgres -v ON_ERROR_STOP=1 <<SQL
DROP DATABASE IF EXISTS $DB;
CREATE DATABASE $DB OWNER etvs_owner TEMPLATE template0;
SQL

echo
echo "=== CREATE AUTHORITATIVE SCHEMA ==="
sudo -u postgres psql -p "$PORT" -d "$DB" -v ON_ERROR_STOP=1 -f schema.sql

echo
echo "=== APPLY ALL MIGRATIONS ==="
for migration in migrations/*.sql; do
  echo "Applying $migration"
  sudo -u postgres psql -p "$PORT" -d "$DB" -v ON_ERROR_STOP=1 -f "$migration"
done

echo
echo "=== RUNTIME ROLE PRIVILEGES ==="
sudo -u postgres psql -p "$PORT" -d "$DB" -v ON_ERROR_STOP=1 <<'SQL'
GRANT CONNECT ON DATABASE etvs TO etvs_app, etvs_reader, etvs_seed;
GRANT USAGE ON SCHEMA public TO etvs_app, etvs_reader, etvs_seed;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO etvs_reader;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO etvs_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO etvs_seed;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO etvs_app, etvs_seed;
ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO etvs_app;
ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO etvs_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO etvs_seed;
ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO etvs_app, etvs_seed;
SQL

echo
echo "=== STRUCTURAL VERIFICATION ==="
sudo -u postgres psql -p "$PORT" -d "$DB" -v ON_ERROR_STOP=1 <<'SQL'
SELECT current_database() AS database, current_user, version();
SELECT COUNT(*) AS base_tables
FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE';
SELECT COUNT(*) AS etvs_regions FROM etvs_regions;
SELECT COUNT(*) AS special_areas FROM special_registration_areas;
SELECT COUNT(*) AS special_registration_centres FROM special_registration_centres;
SELECT COUNT(*) AS special_polling_stations FROM special_polling_stations;
SELECT COALESCE(SUM(s.registered_voters),0) AS special_prison_registered_voters
FROM special_polling_stations s JOIN special_registration_centres c ON c.special_registration_centre_id=s.special_registration_centre_id JOIN special_registration_areas a ON a.special_area_id=c.special_area_id
WHERE a.special_area_type='PRISONS' AND s.election_reference_year=2022;
SELECT COALESCE(SUM(s.registered_voters),0) AS special_diaspora_registered_voters
FROM special_polling_stations s JOIN special_registration_centres c ON c.special_registration_centre_id=s.special_registration_centre_id JOIN special_registration_areas a ON a.special_area_id=c.special_area_id
WHERE a.special_area_type='DIASPORA' AND s.election_reference_year=2022;
SELECT COUNT(*) AS required_tables
FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN (
    'elections','etvs_regions','counties','constituencies','wards',
    'registration_centres','polling_stations','positions','candidates',
    'turnout_observations','registered_voter_observations',
    'result_submissions','ballot_accounting_observations',
    'ballot_specifications','ballot_security_features','ballot_stock_batches',
    'ballot_units','ballot_security_observations',
    'source_submissions','submission_validation_results',
    'published_aggregate_totals','audit_runs','audit_findings',
    'audit_passed_results','audit_failed_results','source_comparisons',
    'audit_position_results','sources','source_documents','etvs_input_scope',
    'special_registration_areas','special_registration_centres','special_polling_stations'
  );
SELECT COUNT(*) AS required_foreign_keys
FROM information_schema.table_constraints
WHERE table_schema='public'
  AND constraint_type='FOREIGN KEY'
  AND constraint_name IN (
    'fk_candidate_position','fk_result_position',
    'fk_published_aggregate_position','fk_audit_run_position',
    'fk_finding_position','fk_ballot_position',
    'fk_ballot_turnout_observation','fk_ballot_security_observation_station_election',
    'fk_ballot_security_observation_specification','fk_ballot_security_observation_batch',
    'fk_ballot_unit_station_election','fk_ballot_unit_position','fk_ballot_unit_batch_context'
  );
SELECT tgname AS trigger_name, tgrelid::regclass AS table_name
FROM pg_trigger
WHERE NOT tgisinternal
  AND tgname IN (
    'trg_validate_audit_run_data',
    'trg_validate_contest_accounting_results',
    'trg_validate_contest_accounting_ballots',
    'trg_validate_turnout_interval'
  )
ORDER BY tgname;
SQL

if [[ "${ETVS_SEED:-0}" == "1" ]]; then
  echo
  echo "=== OPTIONAL CONTROLLED SAMPLE SEED ==="
  echo "Use a configured ETVS_DB_PASSWORD if the PostgreSQL authentication policy requires it."
  ETVS_DB_HOST=127.0.0.1 ETVS_DB_PORT="$PORT" ETVS_DB_NAME="$DB" \
    ETVS_DB_USER="${ETVS_DB_USER:-postgres}" \
    python3 seed.py --reset
fi

echo
echo "PG18 ETVS rebuild completed structurally."
echo "Next connection target inside Debian: 127.0.0.1:$PORT / $DB"
