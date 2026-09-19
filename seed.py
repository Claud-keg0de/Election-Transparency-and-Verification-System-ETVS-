"""Seed deterministic ETVS PostgreSQL test data.

The seed deliberately models the election as six separate contests while keeping
ONE turnout figure per polling station. Every contest's ballot accounting points
back to that same station turnout observation, so voters are never double-counted.

Controlled anomalies prove the audit rules:
- PS003 turnout is greater than registered voters (R001).
- PS005 ballot accounting does not reconcile to turnout (R003).
- PS005 has a changed result version (R005).
- PS006 President candidate votes exceed turnout (R002/R004).
- One published constituency result is intentionally changed (R007).

Run:
    py seed.py --reset
    py seed.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from getpass import getpass

import psycopg
from psycopg.rows import dict_row

from kenya_reference_data import COUNTIES, CONSTITUENCIES, DIASPORA_STATIONS_2022, PRISON_STATIONS_2022, REGIONS

ELECTION_ID = "KE-PRES-2027"
SOURCE_ID = "SRC-ETVS-SAMPLE"
PUBLISHED_SOURCE_ID = "SRC-PUBLISHED-AGGREGATES"
POSITIONS = (
    ("POS-MCA", "Member of County Assembly", "MCA", "WARD", "WARD-MCA", 1),
    ("POS-MP", "Member of Parliament", "MP", "CONSTITUENCY", "CONST-MP", 2),
    ("POS-WOMEN-REP", "Women Representative", "WOMEN_REP", "COUNTY", "COUNTY-WR", 3),
    ("POS-SENATOR", "Senator", "SENATOR", "COUNTY", "COUNTY-SNT", 4),
    ("POS-GOVERNOR", "Governor", "GOVERNOR", "COUNTY", "COUNTY-GVN", 5),
    ("POS-PRESIDENT", "President", "PRESIDENT", "NATIONAL", "NATIONAL-PRES", 6),
)


@dataclass(frozen=True)
class StationSeed:
    station_id: str
    code: str
    centre_id: str
    registered: int
    turnout: int
    turnout_interval_minutes: int


STATIONS = (
    StationSeed("PS001", "PS-001", "RC001", 1000, 700, 15),
    StationSeed("PS002", "PS-002", "RC002", 800, 500, 30),
    StationSeed("PS003", "PS-003", "RC003", 950, 1000, 60),  # R001 anomaly
    StationSeed("PS004", "PS-004", "RC004", 1200, 900, 20),
    StationSeed("PS005", "PS-005", "RC005", 600, 450, 45),
    StationSeed("PS006", "PS-006", "RC006", 700, 650, 120),
)

# Each tuple is (valid, rejected, spoilt) for every contest at that station.
# Spoilt papers are tracked separately and are NOT added to turnout.
BASE_ACCOUNTING = {
    "PS001": (680, 20, 5),
    "PS002": (480, 20, 5),
    "PS003": (960, 40, 15),
    "PS004": (850, 50, 20),
    "PS005": (420, 20, 5),  # 440 != turnout 450 -> R003 failure
    "PS006": (620, 30, 0),
}

VOTE_SPLITS = {
    "PS001": (0.50, 0.32, 0.18),
    "PS002": (0.52, 0.31, 0.17),
    "PS003": (0.52, 0.31, 0.17),
    "PS004": (0.50, 0.32, 0.18),
    "PS005": (0.50, 0.33, 0.17),
    "PS006": (0.50, 0.28, 0.22),
}


def db_kwargs() -> dict:
    password = os.getenv("ETVS_DB_PASSWORD")
    if password is None:
        password = getpass("PostgreSQL password for user postgres: ")
    return {"host": os.getenv("ETVS_DB_HOST", "localhost"), "port": int(os.getenv("ETVS_DB_PORT", "5432")),
            "dbname": os.getenv("ETVS_DB_NAME", "etvs"), "user": os.getenv("ETVS_DB_USER", "postgres"),
            "password": password, "row_factory": dict_row}


def digest(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def ensure_schema(cur) -> None:
    """Additive compatibility layer for databases created before this redesign."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS special_voting_areas (
            special_voting_area_id TEXT PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            area_code TEXT NOT NULL,
            area_name TEXT NOT NULL,
            voting_category TEXT NOT NULL CHECK (voting_category IN ('DIASPORA','PRISON')),
            country_name TEXT,
            source_document_id BIGINT,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (election_id, area_code, country_name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            region_id TEXT PRIMARY KEY,
            region_name TEXT NOT NULL UNIQUE,
            region_type TEXT NOT NULL DEFAULT 'FORMER_PROVINCE'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS county_region_assignments (
            county_id TEXT PRIMARY KEY,
            region_id TEXT NOT NULL REFERENCES regions(region_id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS political_parties (
            party_id TEXT PRIMARY KEY,
            party_name TEXT NOT NULL UNIQUE,
            party_abbreviation TEXT UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS party_symbols (
            party_symbol_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            party_id TEXT NOT NULL REFERENCES political_parties(party_id),
            symbol_name TEXT NOT NULL,
            symbol_uri TEXT,
            approved BOOLEAN NOT NULL DEFAULT TRUE,
            effective_from DATE,
            effective_to DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (party_id, symbol_name)
        )
    """)
    cur.execute("ALTER TABLE polling_stations ADD COLUMN IF NOT EXISTS special_voting_area_id TEXT")
    cur.execute("ALTER TABLE polling_stations ADD COLUMN IF NOT EXISTS special_voting_slot_id BIGINT")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS special_voting_slots (
            special_voting_slot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            special_voting_area_id TEXT NOT NULL REFERENCES special_voting_areas(special_voting_area_id),
            slot_code TEXT NOT NULL,
            slot_number INTEGER NOT NULL,
            slot_status TEXT NOT NULL DEFAULT 'PLANNED',
            location_label TEXT,
            country_name TEXT,
            official_polling_station_code TEXT,
            registered_voters INTEGER,
            source_document_id BIGINT,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (slot_status IN ('PLANNED','ACTIVE','SUSPENDED','RETIRED')),
            CHECK (slot_number > 0),
            CHECK (registered_voters IS NULL OR registered_voters >= 0),
            UNIQUE (election_id, slot_code),
            UNIQUE (election_id, special_voting_area_id, slot_number),
            UNIQUE (special_voting_slot_id, special_voting_area_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS special_voting_area_reference_stations (
            reference_station_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            special_voting_area_id TEXT NOT NULL REFERENCES special_voting_areas(special_voting_area_id),
            reference_year INTEGER NOT NULL,
            registration_centre_code TEXT,
            polling_station_code TEXT NOT NULL,
            polling_station_name TEXT,
            registered_voters INTEGER,
            source_document_id BIGINT,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (reference_year >= 2012),
            CHECK (registered_voters IS NULL OR registered_voters >= 0),
            UNIQUE (special_voting_area_id, reference_year, polling_station_code)
        )
    """)
    cur.execute("""
        DO $ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_polling_station_special_slot') THEN
                ALTER TABLE polling_stations
                ADD CONSTRAINT fk_polling_station_special_slot
                FOREIGN KEY (special_voting_slot_id)
                REFERENCES special_voting_slots(special_voting_slot_id)
                ON UPDATE CASCADE ON DELETE RESTRICT;
            END IF;
        END $;
    """)
    cur.execute("ALTER TABLE polling_stations ADD COLUMN IF NOT EXISTS location_type TEXT NOT NULL DEFAULT 'NORMAL'")
    cur.execute("ALTER TABLE polling_stations ALTER COLUMN registration_centre_id DROP NOT NULL")
    cur.execute("""
        DO $
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname='fk_polling_station_special_area'
            ) THEN
                ALTER TABLE polling_stations
                ADD CONSTRAINT fk_polling_station_special_area
                FOREIGN KEY (special_voting_area_id)
                REFERENCES special_voting_areas(special_voting_area_id)
                ON UPDATE CASCADE ON DELETE RESTRICT;
            END IF;
        END $;
    """)

    cur.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS candidate_type TEXT NOT NULL DEFAULT 'PARTY'")
    cur.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS party_id TEXT")
    # Candidate affiliation constraints are added after the deterministic sample
    # candidates have been refreshed below, so legacy rows are not stranded.
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_party_symbol_current
        ON party_symbols(party_id)
        WHERE effective_to IS NULL
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS independent_candidate_symbols (
            independent_symbol_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            candidate_id TEXT NOT NULL UNIQUE,
            election_id TEXT NOT NULL,
            symbol_name TEXT NOT NULL,
            symbol_uri TEXT,
            approved BOOLEAN NOT NULL DEFAULT TRUE,
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (candidate_id, election_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_independent_symbols_candidate ON independent_candidate_symbols(candidate_id,election_id)")
    cur.execute("""
        DO $ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_independent_symbol_candidate') THEN
                ALTER TABLE independent_candidate_symbols
                ADD CONSTRAINT fk_independent_symbol_candidate
                FOREIGN KEY (candidate_id, election_id)
                REFERENCES candidates(candidate_id, election_id)
                ON UPDATE CASCADE ON DELETE RESTRICT;
            END IF;
        END $;
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS registered_voter_observations (
            registered_voter_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            polling_station_id TEXT NOT NULL REFERENCES polling_stations(polling_station_id),
            observation_version INTEGER NOT NULL CHECK (observation_version > 0),
            registered_voters INTEGER NOT NULL CHECK (registered_voters >= 0),
            observed_at TIMESTAMPTZ NOT NULL, source_document_id BIGINT,
            source_reference TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (election_id, polling_station_id, observation_version)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            position_id TEXT PRIMARY KEY, position_name TEXT NOT NULL UNIQUE,
            election_level TEXT NOT NULL, geography_level TEXT NOT NULL
        )
    """)
    for table in ("turnout_observations", "ballot_accounting_observations", "result_submissions"):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS source_document_id BIGINT")
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS turnout_observation_id BIGINT")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS submission_hash TEXT")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS ballot_code TEXT")
    cur.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS observation_sequence INTEGER")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS turnout_reporting_intervals (
            turnout_interval_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            polling_station_id TEXT NOT NULL REFERENCES polling_stations(polling_station_id),
            interval_minutes INTEGER NOT NULL CHECK (interval_minutes > 0),
            effective_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            effective_to TIMESTAMPTZ,
            reporting_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (election_id, polling_station_id, effective_from),
            CHECK (effective_to IS NULL OR effective_to > effective_from)
        )
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_turnout_interval_current
        ON turnout_reporting_intervals(election_id, polling_station_id)
        WHERE effective_to IS NULL
    """)
    cur.execute("ALTER TABLE turnout_observations ADD COLUMN IF NOT EXISTS interval_configuration_id BIGINT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_turnout_interval_configuration ON turnout_observations(interval_configuration_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_registered_latest ON registered_voter_observations(election_id,polling_station_id,observation_version DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ballot_latest_position ON ballot_accounting_observations(election_id,polling_station_id,position_id,observation_version DESC)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY, source_name TEXT NOT NULL, source_type TEXT NOT NULL,
            organization_name TEXT, description TEXT, source_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS source_documents (
            document_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(source_id), document_name TEXT NOT NULL,
            document_type TEXT NOT NULL, document_uri TEXT, content_hash TEXT NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (source_id,document_name,content_hash)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS special_area_contest_rules (
            special_area_contest_rule_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            special_voting_area_id TEXT NOT NULL REFERENCES special_voting_areas(special_voting_area_id),
            position_id TEXT NOT NULL REFERENCES positions(position_id),
            reference_year INTEGER NOT NULL,
            eligibility_status TEXT NOT NULL CHECK (eligibility_status IN ('ALLOWED','NOT_ELIGIBLE')),
            source_document_id BIGINT REFERENCES source_documents(document_id),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (special_voting_area_id, position_id, reference_year)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS published_aggregate_totals (
            published_aggregate_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id), source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id),
            aggregation_level TEXT NOT NULL, geography_id TEXT NOT NULL, candidate_id TEXT, position_id TEXT,
            metric TEXT NOT NULL, reported_value INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE NULLS NOT DISTINCT (election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric)
        )
    """)


    cur.execute("ALTER TABLE candidates DROP CONSTRAINT IF EXISTS unique_candidate_per_election")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidate_electoral_areas (
            candidate_electoral_area_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            election_id TEXT NOT NULL,
            position_id TEXT NOT NULL,
            electoral_area_type TEXT NOT NULL,
            electoral_area_id TEXT NOT NULL,
            candidate_type TEXT NOT NULL,
            party_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (candidate_id,election_id) REFERENCES candidates(candidate_id,election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            FOREIGN KEY (position_id) REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            FOREIGN KEY (party_id) REFERENCES political_parties(party_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            CHECK (electoral_area_type IN ('NATIONAL','COUNTY','CONSTITUENCY','WARD')),
            CHECK (candidate_type IN ('PARTY','INDEPENDENT')),
            CHECK ((candidate_type='PARTY' AND party_id IS NOT NULL) OR (candidate_type='INDEPENDENT' AND party_id IS NULL)),
            UNIQUE (candidate_id,election_id)
        )
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_party_candidate_slot
        ON candidate_electoral_areas(election_id,position_id,electoral_area_type,electoral_area_id,party_id)
        WHERE candidate_type='PARTY'
    """)
    cur.execute("""
        CREATE OR REPLACE FUNCTION validate_candidate_electoral_area()
        RETURNS trigger LANGUAGE plpgsql AS $
        DECLARE expected_geography TEXT; candidate_position TEXT; candidate_party TEXT; candidate_kind TEXT;
        BEGIN
            SELECT p.geography_level,c.position_id,c.party_id,c.candidate_type
              INTO expected_geography,candidate_position,candidate_party,candidate_kind
              FROM candidates c JOIN positions p ON p.position_id=c.position_id
             WHERE c.candidate_id=NEW.candidate_id AND c.election_id=NEW.election_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Candidate % does not belong to election %',NEW.candidate_id,NEW.election_id; END IF;
            IF NEW.position_id<>candidate_position THEN RAISE EXCEPTION 'Candidate position mismatch for %',NEW.candidate_id; END IF;
            IF NEW.electoral_area_type<>expected_geography THEN RAISE EXCEPTION 'Position % requires % area, not %',NEW.position_id,expected_geography,NEW.electoral_area_type; END IF;
            IF NEW.candidate_type<>candidate_kind OR NEW.party_id IS DISTINCT FROM candidate_party THEN RAISE EXCEPTION 'Candidate affiliation mismatch for %',NEW.candidate_id; END IF;
            IF NEW.electoral_area_type='NATIONAL' AND NEW.electoral_area_id<>'NATIONAL' THEN RAISE EXCEPTION 'National contests must use NATIONAL area'; END IF;
            IF NEW.electoral_area_type='COUNTY' AND NOT EXISTS (SELECT 1 FROM counties WHERE county_id=NEW.electoral_area_id) THEN RAISE EXCEPTION 'Unknown county area %',NEW.electoral_area_id; END IF;
            IF NEW.electoral_area_type='CONSTITUENCY' AND NOT EXISTS (SELECT 1 FROM constituencies WHERE constituency_id=NEW.electoral_area_id) THEN RAISE EXCEPTION 'Unknown constituency area %',NEW.electoral_area_id; END IF;
            IF NEW.electoral_area_type='WARD' AND NOT EXISTS (SELECT 1 FROM wards WHERE ward_id=NEW.electoral_area_id) THEN RAISE EXCEPTION 'Unknown ward area %',NEW.electoral_area_id; END IF;
            RETURN NEW;
        END $;
    """)
    cur.execute("DROP TRIGGER IF EXISTS trg_validate_candidate_electoral_area ON candidate_electoral_areas")
    cur.execute("""
        CREATE TRIGGER trg_validate_candidate_electoral_area
        BEFORE INSERT OR UPDATE ON candidate_electoral_areas
        FOR EACH ROW EXECUTE FUNCTION validate_candidate_electoral_area()
    """)
    cur.execute("""
        CREATE OR REPLACE FUNCTION validate_result_candidate_electoral_area()
        RETURNS trigger LANGUAGE plpgsql AS $
        DECLARE station_area_type TEXT; station_area_id TEXT; candidate_area_type TEXT; candidate_area_id TEXT;
        BEGIN
            SELECT p.geography_level,
                   CASE p.geography_level
                     WHEN 'NATIONAL' THEN 'NATIONAL'
                     WHEN 'COUNTY' THEN co.county_id
                     WHEN 'CONSTITUENCY' THEN co2.constituency_id
                     WHEN 'WARD' THEN w.ward_id
                   END
              INTO station_area_type,station_area_id
              FROM polling_stations ps
              LEFT JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
              LEFT JOIN wards w ON w.ward_id=rc.ward_id
              LEFT JOIN constituencies co2 ON co2.constituency_id=w.constituency_id
              LEFT JOIN counties co ON co.county_id=co2.county_id
              JOIN positions p ON p.position_id=NEW.position_id
             WHERE ps.polling_station_id=NEW.polling_station_id AND ps.election_id=NEW.election_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Cannot resolve polling station % and position %',NEW.polling_station_id,NEW.position_id; END IF;
            IF EXISTS (SELECT 1 FROM polling_stations WHERE polling_station_id=NEW.polling_station_id AND location_type='SPECIAL') THEN RETURN NEW; END IF;
            SELECT electoral_area_type,electoral_area_id INTO candidate_area_type,candidate_area_id
              FROM candidate_electoral_areas
             WHERE candidate_id=NEW.candidate_id AND election_id=NEW.election_id AND position_id=NEW.position_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Candidate % has no electoral-area assignment',NEW.candidate_id; END IF;
            IF candidate_area_type<>station_area_type OR candidate_area_id<>station_area_id THEN
                RAISE EXCEPTION 'Candidate % is not valid for polling station % area (%:%)',NEW.candidate_id,NEW.polling_station_id,station_area_type,station_area_id;
            END IF;
            RETURN NEW;
        END $;
    """)
    cur.execute("DROP TRIGGER IF EXISTS trg_validate_result_candidate_electoral_area ON result_submissions")
    cur.execute("""
        CREATE TRIGGER trg_validate_result_candidate_electoral_area
        BEFORE INSERT OR UPDATE ON result_submissions
        FOR EACH ROW EXECUTE FUNCTION validate_result_candidate_electoral_area()
    """)


def ensure_reporting_views(cur) -> None:
    """Create stable dashboard views; these never alter source observations."""
    cur.execute("""
        CREATE OR REPLACE VIEW v_audit_station_findings AS
        SELECT f.audit_finding_id,f.audit_run_id,f.election_id,f.polling_station_id,ps.polling_station_code,
               f.position_id,f.rule_code,f.status,f.actual_label,f.actual_value,f.comparison_label,f.comparison_value,f.message,f.created_at
        FROM audit_findings f LEFT JOIN polling_stations ps ON ps.polling_station_id=f.polling_station_id
        WHERE f.polling_station_id IS NOT NULL
    """)
    cur.execute("""
        CREATE OR REPLACE VIEW v_audit_station_summary AS
        SELECT audit_run_id,election_id,polling_station_id,COUNT(*)::INTEGER rules_checked,
               COUNT(*) FILTER(WHERE status='PASSED')::INTEGER passed_count,
               COUNT(*) FILTER(WHERE status='FAILED')::INTEGER failed_count,
               COUNT(*) FILTER(WHERE status='WARNING')::INTEGER warning_count,
               CASE WHEN COUNT(*) FILTER(WHERE status='FAILED')>0 THEN 'FAILED'
                    WHEN COUNT(*) FILTER(WHERE status='WARNING')>0 THEN 'WARNING' ELSE 'PASSED' END station_status
        FROM audit_findings WHERE polling_station_id IS NOT NULL GROUP BY audit_run_id,election_id,polling_station_id
    """)


def seed_positions(cur) -> None:
    for pid,name,office,geo,code,seq in POSITIONS:
        cur.execute("""
            INSERT INTO positions(position_id,position_name,election_level,geography_level,ballot_code,observation_sequence)
            VALUES(%s,%s,%s,%s,%s,%s)
            ON CONFLICT(position_id) DO UPDATE SET position_name=EXCLUDED.position_name,election_level=EXCLUDED.election_level,
                geography_level=EXCLUDED.geography_level,ballot_code=EXCLUDED.ballot_code,observation_sequence=EXCLUDED.observation_sequence
        """,(pid,name,office,geo,code,seq))


def seed_sources(cur) -> tuple[int,int]:
    for sid,name in ((SOURCE_ID,"ETVS controlled sample source"),(PUBLISHED_SOURCE_ID,"Published aggregate comparison source")):
        cur.execute("""
            INSERT INTO sources(source_id,source_name,source_type,organization_name,description)
            VALUES(%s,%s,'OTHER','ETVS project','Controlled provenance source for the sample dataset.')
            ON CONFLICT(source_id) DO UPDATE SET source_name=EXCLUDED.source_name
        """,(sid,name))
    ids=[]
    for sid,name in ((SOURCE_ID,"ETVS sample election observations"),(PUBLISHED_SOURCE_ID,"Published aggregate results comparison")):
        h=digest("SOURCE",ELECTION_ID,sid,name)
        row=cur.execute("""
            INSERT INTO source_documents(source_id,document_name,document_type,document_uri,content_hash)
            VALUES(%s,%s,'SEEDED_DATASET','seed.py',%s)
            ON CONFLICT(source_id,document_name,content_hash) DO UPDATE SET document_uri='seed.py'
            RETURNING document_id
        """,(sid,name,h)).fetchone()
        ids.append(int(row["document_id"]))
    return tuple(ids)


def reset_sample(cur) -> None:
    """Delete only the sample election in dependency order."""
    for sql in (
        "DELETE FROM source_comparisons WHERE election_id=%s",
        "DELETE FROM submission_validation_results WHERE source_submission_id IN (SELECT source_submission_id FROM source_submissions WHERE election_id=%s)",
        "DELETE FROM source_submissions WHERE election_id=%s",
        "DELETE FROM audit_position_results WHERE election_id=%s",
        "DELETE FROM audit_passed_results WHERE election_id=%s",
        "DELETE FROM audit_failed_results WHERE election_id=%s",
        "DELETE FROM audit_findings WHERE election_id=%s",
        "DELETE FROM audit_runs WHERE election_id=%s",
        "DELETE FROM result_submissions WHERE election_id=%s",
        "DELETE FROM published_aggregate_totals WHERE election_id=%s",
        "DELETE FROM ballot_accounting_observations WHERE election_id=%s",
        "DELETE FROM registered_voter_observations WHERE election_id=%s",
        "DELETE FROM turnout_observations WHERE election_id=%s",
        "DELETE FROM turnout_reporting_intervals WHERE election_id=%s",
        "DELETE FROM polling_stations WHERE election_id=%s",
        "DELETE FROM special_voting_slots WHERE election_id=%s",
        "DELETE FROM special_voting_area_reference_stations WHERE special_voting_area_id IN (SELECT special_voting_area_id FROM special_voting_areas WHERE election_id=%s)",
        "DELETE FROM independent_candidate_symbols WHERE election_id=%s",
        "DELETE FROM candidate_electoral_areas WHERE election_id=%s",
        "DELETE FROM candidates WHERE election_id=%s",
        "DELETE FROM special_area_contest_rules WHERE special_voting_area_id IN (SELECT special_voting_area_id FROM special_voting_areas WHERE election_id=%s)",
        "DELETE FROM special_voting_areas WHERE election_id=%s",
        "DELETE FROM elections WHERE election_id=%s",
    ):
        try: cur.execute(sql,(ELECTION_ID,))
        except psycopg.errors.UndefinedTable: pass
    cur.execute("DELETE FROM party_symbols WHERE party_id IN ('PTY-ALPHA','PTY-BETA')")
    cur.execute("DELETE FROM political_parties WHERE party_id IN ('PTY-ALPHA','PTY-BETA')")
    cur.execute("DELETE FROM county_region_assignments WHERE county_id='COUNTY001'")
    for table,column,values in (("registration_centres","registration_centre_id",["RC001","RC002","RC003","RC004","RC005","RC006"]),("wards","ward_id",["W001","W002","W003","W004"]),("constituencies","constituency_id",["CON001","CON002"]),("counties","county_id",["COUNTY001"])):
        cur.execute(f"DELETE FROM {table} WHERE {column}=ANY(%s)",(values,))
    cur.execute("DELETE FROM source_documents WHERE source_id IN (%s,%s)",(SOURCE_ID,PUBLISHED_SOURCE_ID))
    cur.execute("DELETE FROM sources WHERE source_id IN (%s,%s)",(SOURCE_ID,PUBLISHED_SOURCE_ID))


def seed_master_data(cur) -> None:
    # Hard-coded national reference geography for the current ETVS phase.
    for rid, name in REGIONS.items():
        cur.execute("""
            INSERT INTO regions(region_id, region_name, region_type)
            VALUES(%s,%s,'FORMER_PROVINCE')
            ON CONFLICT(region_id) DO UPDATE SET region_name=EXCLUDED.region_name
        """, (rid,name))

    for county_id, county_code, county_name, region_id in COUNTIES:
        cur.execute("""
            INSERT INTO counties(county_id,county_name)
            VALUES(%s,%s)
            ON CONFLICT(county_id) DO UPDATE SET county_name=EXCLUDED.county_name
        """, (county_id,county_name))
        cur.execute("""
            INSERT INTO county_region_assignments(county_id,region_id)
            VALUES(%s,%s)
            ON CONFLICT(county_id) DO UPDATE SET region_id=EXCLUDED.region_id
        """, (county_id,region_id))

    county_by_code={code:cid for cid,code,_,_ in COUNTIES}
    for number,name,county_code in CONSTITUENCIES:
        county_id=county_by_code[county_code]
        constituency_id=f"KE-C{number:03d}"
        cur.execute("""
            INSERT INTO constituencies(constituency_id,constituency_name,county_id)
            VALUES(%s,%s,%s)
            ON CONFLICT(constituency_id) DO UPDATE SET constituency_name=EXCLUDED.constituency_name,
                county_id=EXCLUDED.county_id
        """, (constituency_id,name,county_id))

    cur.execute("""
        INSERT INTO elections(election_id,election_name,election_date,status)
        VALUES(%s,'ETVS Sample Election 2027','2027-08-10','ACTIVE')
        ON CONFLICT DO NOTHING
    """, (ELECTION_ID,))

    # Controlled test wards use real Trans Nzoia constituencies.
    wards=(
        ("W001","Keiyo","KE-C136"),
        ("W002","Bidii","KE-C136"),
        ("W003","Endebess","KE-C137"),
        ("W004","Matumbei","KE-C137"),
    )
    for wid,name,cid in wards:
        cur.execute("""
            INSERT INTO wards(ward_id,ward_name,constituency_id)
            VALUES(%s,%s,%s)
            ON CONFLICT(ward_id) DO UPDATE SET ward_name=EXCLUDED.ward_name,
                constituency_id=EXCLUDED.constituency_id
        """, (wid,name,cid))

    cur.execute("""
        INSERT INTO political_parties(party_id,party_name,party_abbreviation)
        VALUES('PTY-ALPHA','Civic Renewal Party','CRP'),
              ('PTY-BETA','National Development Party','NDP')
        ON CONFLICT(party_id) DO UPDATE SET party_name=EXCLUDED.party_name,
            party_abbreviation=EXCLUDED.party_abbreviation
    """)
    cur.execute("""
        INSERT INTO party_symbols(party_id,symbol_name,symbol_uri,approved)
        VALUES('PTY-ALPHA','Rising Sun','seed://symbols/crp-rising-sun',TRUE),
              ('PTY-BETA','Open Book','seed://symbols/ndp-open-book',TRUE)
        ON CONFLICT(party_id,symbol_name) DO UPDATE SET symbol_uri=EXCLUDED.symbol_uri,
            approved=EXCLUDED.approved
    """)

    centres=(
        ("RC001","Greenfield Primary School","W001"),
        ("RC002","Greenfield Community Hall","W002"),
        ("RC003","Greenfield Secondary School","W001"),
        ("RC004","Riverdale Primary School","W003"),
        ("RC005","Riverdale Community Hall","W004"),
        ("RC006","Riverdale Secondary School","W003"),
    )
    for rid,name,wid in centres:
        cur.execute("""
            INSERT INTO registration_centres(registration_centre_id,registration_centre_name,ward_id)
            VALUES(%s,%s,%s)
            ON CONFLICT(registration_centre_id) DO UPDATE SET registration_centre_name=EXCLUDED.registration_centre_name,
                ward_id=EXCLUDED.ward_id
        """, (rid,name,wid))

    for s in STATIONS:
        cur.execute("""
            INSERT INTO polling_stations(
                polling_station_id,election_id,registration_centre_id,special_voting_area_id,
                location_type,polling_station_code,registered_voters
            )
            VALUES(%s,%s,%s,NULL,'NORMAL',%s,%s)
            ON CONFLICT(polling_station_id) DO UPDATE SET
                election_id=EXCLUDED.election_id,
                registration_centre_id=EXCLUDED.registration_centre_id,
                special_voting_area_id=NULL,
                location_type='NORMAL',
                polling_station_code=EXCLUDED.polling_station_code,
                registered_voters=EXCLUDED.registered_voters
        """, (s.station_id,ELECTION_ID,s.centre_id,s.code,s.registered))

    # Candidate slots are seeded for the applicable electoral area:
    # President -> national; Governor/Senator/Women Rep -> county;
    # MP -> constituency; MCA -> ward.
    contest_areas = {
        "POS-PRESIDENT": [("NATIONAL", "NATIONAL")],
        "POS-GOVERNOR": [("COUNTY", "KE-026")],
        "POS-SENATOR": [("COUNTY", "KE-026")],
        "POS-WOMEN-REP": [("COUNTY", "KE-026")],
        "POS-MP": [("CONSTITUENCY", "KE-C136"), ("CONSTITUENCY", "KE-C137")],
        "POS-MCA": [("WARD", "W001"), ("WARD", "W002"), ("WARD", "W003"), ("WARD", "W004")],
    }
    cur.execute("DELETE FROM candidate_electoral_areas WHERE election_id=%s", (ELECTION_ID,))
    cur.execute("DELETE FROM candidates WHERE election_id=%s", (ELECTION_ID,))
    for pid,pname,_,_,_,_ in POSITIONS:
        for area_type, area_id in contest_areas[pid]:
            for n,name in ((1,"Amina Njeri"),(2,"Brian Wanyonyi"),(3,"David Mwangi")):
                cid=f"{pid}-{area_id}-C{n:03d}"
                candidate_type='INDEPENDENT' if n==3 else 'PARTY'
                party_id=None if n==3 else ('PTY-ALPHA' if n==1 else 'PTY-BETA')
                cur.execute("""
                    INSERT INTO candidates(candidate_id,election_id,candidate_name,office,position_id,candidate_type,party_id)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(candidate_id) DO UPDATE SET candidate_name=EXCLUDED.candidate_name,
                        office=EXCLUDED.office,position_id=EXCLUDED.position_id,
                        candidate_type=EXCLUDED.candidate_type,party_id=EXCLUDED.party_id
                """, (cid,ELECTION_ID,name,pname,pid,candidate_type,party_id))
                cur.execute("""
                    INSERT INTO candidate_electoral_areas(
                        candidate_id,election_id,position_id,electoral_area_type,electoral_area_id,candidate_type,party_id
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s)
                """, (cid,ELECTION_ID,pid,area_type,area_id,candidate_type,party_id))
                if candidate_type=='INDEPENDENT':
                    cur.execute("""
                        INSERT INTO independent_candidate_symbols(
                            candidate_id,election_id,symbol_name,symbol_uri,approved,approved_at
                        ) VALUES(%s,%s,%s,%s,TRUE,%s)
                        ON CONFLICT(candidate_id) DO UPDATE SET
                            election_id=EXCLUDED.election_id,symbol_name=EXCLUDED.symbol_name,
                            symbol_uri=EXCLUDED.symbol_uri,approved=EXCLUDED.approved,
                            approved_at=EXCLUDED.approved_at
                    """, (cid,ELECTION_ID,f"Independent symbol for {name} ({area_id})",
                          f"seed://symbols/{cid.lower()}",datetime(2027,7,1).date()))

    cur.execute("""
        DO $ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_candidate_party') THEN
                ALTER TABLE candidates ADD CONSTRAINT fk_candidate_party
                FOREIGN KEY (party_id) REFERENCES political_parties(party_id)
                ON UPDATE CASCADE ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='candidate_type_check') THEN
                ALTER TABLE candidates ADD CONSTRAINT candidate_type_check
                CHECK (candidate_type IN ('PARTY','INDEPENDENT'));
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='candidate_party_affiliation_check') THEN
                ALTER TABLE candidates ADD CONSTRAINT candidate_party_affiliation_check
                CHECK ((candidate_type='PARTY' AND party_id IS NOT NULL)
                    OR (candidate_type='INDEPENDENT' AND party_id IS NULL));
            END IF;
        END $;
    """)


def seed_special_voting_areas(cur, source_document_id: int) -> None:
    """Seed special voting areas, historical references, and configurable 2027 slots.

    Historical 2022 IEBC station rows are stored only in the reference table.
    They are NOT copied into the active 2027 polling-station configuration.
    The number of 2027 special polling stations is controlled by slots and can
    increase, decrease, or be retired without changing the schema.
    """
    country_codes = {
        "Tanzania": "05000",
        "Uganda": "05001",
        "Rwanda": "05002",
        "Burundi": "05003",
        "South Africa": "05004",
        "South Sudan": "05005",
        "Germany": "05006",
        "United Kingdom": "05007",
        "Qatar": "05008",
        "United Arab Emirates": "05009",
        "Canada": "05010",
        "United States of America": "05011",
    }

    countries = list(dict.fromkeys(country for _, country, _, _ in DIASPORA_STATIONS_2022))

    for country in countries:
        code = country_codes[country]
        area_id = f"SVA-DIA-{code}"
        cur.execute("""
            INSERT INTO special_voting_areas(
                special_voting_area_id,election_id,area_code,area_name,
                voting_category,country_name,source_document_id,notes
            )
            VALUES(%s,%s,%s,%s,'DIASPORA',%s,%s,%s)
            ON CONFLICT(special_voting_area_id) DO UPDATE SET
                area_code=EXCLUDED.area_code,
                area_name=EXCLUDED.area_name,
                voting_category=EXCLUDED.voting_category,
                country_name=EXCLUDED.country_name,
                source_document_id=EXCLUDED.source_document_id,
                notes=EXCLUDED.notes
        """, (
            area_id,ELECTION_ID,code,country,country,source_document_id,
            "Historical 2022 IEBC reference is retained separately; 2027 special polling locations are configured through slots.",
        ))

    cur.execute("""
        INSERT INTO special_voting_areas(
            special_voting_area_id,election_id,area_code,area_name,
            voting_category,country_name,source_document_id,notes
        )
        VALUES(
            'SVA-PRISONS',%s,'01451','Prisons','PRISON',NULL,%s,
            'Historical 2022 IEBC Gazette data is retained separately; the active 2027 prison polling-station count is controlled through configurable slots.'
        )
        ON CONFLICT(special_voting_area_id) DO UPDATE SET
            area_code=EXCLUDED.area_code,
            area_name=EXCLUDED.area_name,
            voting_category=EXCLUDED.voting_category,
            source_document_id=EXCLUDED.source_document_id,
            notes=EXCLUDED.notes
    """, (ELECTION_ID,source_document_id))

    # Remove only the old hard-coded special stations from this sample election.
    # Historical source rows are copied to the reference table below, not to
    # polling_stations.
    cur.execute("""
        DELETE FROM polling_stations
        WHERE election_id=%s AND location_type='SPECIAL'
    """, (ELECTION_ID,))

    # Preserve the 2022 IEBC station-level evidence as historical reference data.
    cur.execute("""
        DELETE FROM special_voting_area_reference_stations
        WHERE reference_year=2022
          AND special_voting_area_id IN (
              SELECT special_voting_area_id
              FROM special_voting_areas
              WHERE election_id=%s
          )
    """, (ELECTION_ID,))

    for station_code,country,station_name,registered in DIASPORA_STATIONS_2022:
        area_id=f"SVA-DIA-{country_codes[country]}"
        cur.execute("""
            INSERT INTO special_voting_area_reference_stations(
                special_voting_area_id,reference_year,polling_station_code,
                polling_station_name,registered_voters,source_document_id,notes
            )
            VALUES(%s,2022,%s,%s,%s,%s,%s)
            ON CONFLICT(special_voting_area_id,reference_year,polling_station_code)
            DO UPDATE SET polling_station_name=EXCLUDED.polling_station_name,
                          registered_voters=EXCLUDED.registered_voters,
                          source_document_id=EXCLUDED.source_document_id,
                          notes=EXCLUDED.notes
        """, (
            area_id,station_code,station_name,registered,source_document_id,
            "Historical IEBC 2022 Gazette reference; not an active 2027 polling-station assignment.",
        ))

    for centre_code,station_name,registered in PRISON_STATIONS_2022:
        station_code=f"0492921451{centre_code}01"
        cur.execute("""
            INSERT INTO special_voting_area_reference_stations(
                special_voting_area_id,reference_year,registration_centre_code,
                polling_station_code,polling_station_name,registered_voters,
                source_document_id,notes
            )
            VALUES('SVA-PRISONS',2022,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(special_voting_area_id,reference_year,polling_station_code)
            DO UPDATE SET registration_centre_code=EXCLUDED.registration_centre_code,
                          polling_station_name=EXCLUDED.polling_station_name,
                          registered_voters=EXCLUDED.registered_voters,
                          source_document_id=EXCLUDED.source_document_id,
                          notes=EXCLUDED.notes
        """, (
            centre_code,station_code,station_name,registered,source_document_id,
            "Historical IEBC 2022 Gazette reference; not an active 2027 polling-station assignment.",
        ))

    # Seed one planned slot per special voting area as a configurable starting
    # point. Administrators can add more slots or retire/suspend existing ones.
    areas=cur.execute("""
        SELECT special_voting_area_id, voting_category, country_name
        FROM special_voting_areas
        WHERE election_id=%s
        ORDER BY special_voting_area_id
    """,(ELECTION_ID,)).fetchall()

    for area in areas:
        area_id=area["special_voting_area_id"]
        suffix=area_id.replace("SVA-","")
        slot_code=f"SVS-{suffix}-001"
        cur.execute("""
            INSERT INTO special_voting_slots(
                election_id,special_voting_area_id,slot_code,slot_number,
                slot_status,country_name,source_document_id,notes
            )
            VALUES(%s,%s,%s,1,'PLANNED',%s,%s,%s)
            ON CONFLICT(election_id,special_voting_area_id,slot_number)
            DO UPDATE SET country_name=EXCLUDED.country_name,
                          source_document_id=EXCLUDED.source_document_id,
                          notes=EXCLUDED.notes
        """, (
            ELECTION_ID,area_id,slot_code,area["country_name"],source_document_id,
            "Configurable special-voting slot. Activate only when the applicable official election configuration is known.",
        ))

def seed_special_area_contest_rules(cur) -> None:
    """Record historical 2022 special-area contest eligibility separately.

    Both diaspora and prison voters are recorded as presidential-only for the
    2022 historical reference. These rows are explicitly keyed to 2022 and do
    not authorize the 2027 sample election.
    """
    area_ids = [
        r["special_voting_area_id"]
        for r in cur.execute("""
            SELECT special_voting_area_id
            FROM special_voting_areas
            WHERE election_id=%s
            ORDER BY special_voting_area_id
        """, (ELECTION_ID,)).fetchall()
    ]
    for area_id in area_ids:
        for position_id, *_ in POSITIONS:
            status = "ALLOWED" if position_id == "POS-PRESIDENT" else "NOT_ELIGIBLE"
            cur.execute("""
                INSERT INTO special_area_contest_rules(
                    special_voting_area_id,position_id,reference_year,
                    eligibility_status,source_document_id,notes
                )
                VALUES(%s,%s,2022,%s,NULL,%s)
                ON CONFLICT(special_voting_area_id,position_id,reference_year)
                DO UPDATE SET eligibility_status=EXCLUDED.eligibility_status,
                              source_document_id=NULL,
                              notes=EXCLUDED.notes
            """, (
                area_id,
                position_id,
                status,
                "Historical 2022 IEBC reference; presidential-only special voting rule. "
                "This does not determine 2027 eligibility.",
            ))


def seed_turnout_intervals(cur) -> None:
    """Seed one independently configurable reporting interval for every station."""
    base=datetime(2027,8,10,8,0,tzinfo=timezone.utc)
    for i,s in enumerate(STATIONS):
        effective_from=base+timedelta(minutes=i)
        cur.execute("""
            INSERT INTO turnout_reporting_intervals(
                election_id,polling_station_id,interval_minutes,effective_from,
                effective_to,reporting_enabled
            )
            VALUES(%s,%s,%s,%s,NULL,TRUE)
            ON CONFLICT(election_id,polling_station_id,effective_from) DO UPDATE SET
                interval_minutes=EXCLUDED.interval_minutes,
                effective_to=NULL,
                reporting_enabled=EXCLUDED.reporting_enabled
        """,(ELECTION_ID,s.station_id,s.turnout_interval_minutes,effective_from))


def seed_observations(cur,source_document_id:int) -> None:
    """Create registered, shared turnout, and six contest-specific ballot streams."""
    base=datetime(2027,8,10,8,0,tzinfo=timezone.utc)
    for i,s in enumerate(STATIONS):
        registered_at=base+timedelta(minutes=i)
        cur.execute("""
            INSERT INTO registered_voter_observations(election_id,polling_station_id,observation_version,registered_voters,observed_at,source_document_id,source_reference)
            VALUES(%s,%s,1,%s,%s,%s,%s)
            ON CONFLICT(election_id,polling_station_id,observation_version) DO UPDATE SET registered_voters=EXCLUDED.registered_voters,
            observed_at=EXCLUDED.observed_at,source_document_id=EXCLUDED.source_document_id,source_reference=EXCLUDED.source_reference
        """,(ELECTION_ID,s.station_id,s.registered,registered_at,source_document_id,f"SEED-REGISTERED-{s.station_id}-V1"))
        interval_id=cur.execute("""
            SELECT turnout_interval_id FROM turnout_reporting_intervals
            WHERE election_id=%s AND polling_station_id=%s AND effective_from <= %s
              AND (effective_to IS NULL OR effective_to > %s)
            ORDER BY effective_from DESC LIMIT 1
        """,(ELECTION_ID,s.station_id,registered_at,registered_at)).fetchone()["turnout_interval_id"]
        # Turnout is one voter count for the station, not six separate counts.
        # Store the configuration used at entry time so the audit trail preserves
        # the exact reporting cadence that applied to each observation.
        t1=registered_at+timedelta(minutes=s.turnout_interval_minutes)
        t2=t1+timedelta(minutes=s.turnout_interval_minutes)
        initial=max(0,s.turnout-(5 if s.station_id=="PS005" else 0))
        for version,turnout,when in ((1,initial,t1),(2,s.turnout,t2)):
            ref=digest("TURNOUT",ELECTION_ID,s.station_id,version,turnout)
            cur.execute("""
                INSERT INTO turnout_observations(election_id,polling_station_id,observation_version,interval_configuration_id,voters_turnout,source_document_id,source_reference,observed_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(election_id,polling_station_id,observation_version) DO UPDATE SET voters_turnout=EXCLUDED.voters_turnout,
                interval_configuration_id=EXCLUDED.interval_configuration_id,source_document_id=EXCLUDED.source_document_id,source_reference=EXCLUDED.source_reference,observed_at=EXCLUDED.observed_at
            """,(ELECTION_ID,s.station_id,version,interval_id,turnout,source_document_id,ref,when))
        turnout_id=cur.execute("SELECT turnout_observation_id FROM turnout_observations WHERE election_id=%s AND polling_station_id=%s AND observation_version=2",(ELECTION_ID,s.station_id)).fetchone()["turnout_observation_id"]
        valid,rejected,spoilt=BASE_ACCOUNTING[s.station_id]
        for pos_index,(pid,*_) in enumerate(POSITIONS):
            when=t2+timedelta(minutes=10+pos_index)
            cur.execute("""
                INSERT INTO ballot_accounting_observations(election_id,polling_station_id,position_id,observation_version,valid_votes,rejected_votes,spoilt_ballots,turnout_observation_id,source_document_id,source_reference,observed_at)
                VALUES(%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(election_id,polling_station_id,position_id,observation_version) DO UPDATE SET valid_votes=EXCLUDED.valid_votes,
                rejected_votes=EXCLUDED.rejected_votes,spoilt_ballots=EXCLUDED.spoilt_ballots,turnout_observation_id=EXCLUDED.turnout_observation_id,
                source_document_id=EXCLUDED.source_document_id,source_reference=EXCLUDED.source_reference,observed_at=EXCLUDED.observed_at
            """,(ELECTION_ID,s.station_id,pid,valid,rejected,spoilt,turnout_id,source_document_id,f"SEED-BALLOT-{s.station_id}-{pid}",when))


def votes_for(valid:int,split:tuple[float,float,float])->tuple[int,int,int]:
    a=int(valid*split[0]);b=int(valid*split[1]);return a,b,valid-a-b


def seed_results(cur,source_document_id:int)->None:
    """Create candidate results using the candidate nominated for each station's area."""
    station_rows=cur.execute("""
        SELECT ps.polling_station_id,w.ward_id,c.constituency_id,co.county_id
        FROM polling_stations ps
        JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
        JOIN wards w ON w.ward_id=rc.ward_id
        JOIN constituencies c ON c.constituency_id=w.constituency_id
        JOIN counties co ON co.county_id=c.county_id
        WHERE ps.election_id=%s
    """,(ELECTION_ID,)).fetchall()
    for s in STATIONS:
        area_row=next(r for r in station_rows if r["polling_station_id"]==s.station_id)
        area_by_position={
            "POS-PRESIDENT":("NATIONAL","NATIONAL"),
            "POS-GOVERNOR":("COUNTY",area_row["county_id"]),
            "POS-SENATOR":("COUNTY",area_row["county_id"]),
            "POS-WOMEN-REP":("COUNTY",area_row["county_id"]),
            "POS-MP":("CONSTITUENCY",area_row["constituency_id"]),
            "POS-MCA":("WARD",area_row["ward_id"]),
        }
        for pid,*_ in POSITIONS:
            valid,_,_=BASE_ACCOUNTING[s.station_id]
            votes=votes_for(valid,VOTE_SPLITS[s.station_id])
            area_type,area_id=area_by_position[pid]
            for n,base_votes in enumerate(votes,1):
                cid=f"{pid}-{area_id}-C{n:03d}"
                versions=(1,2) if s.station_id=="PS005" and pid=="POS-PRESIDENT" and n==1 else (1,)
                for version in versions:
                    final=base_votes+5 if version==2 else base_votes
                    if s.station_id=="PS006" and pid=="POS-PRESIDENT" and n==1: final+=40
                    when=datetime(2027,8,10,18,0,tzinfo=timezone.utc)+timedelta(minutes=len(pid)+n+version)
                    h=digest("RESULT",ELECTION_ID,s.station_id,cid,version,final)
                    cur.execute("""
                        INSERT INTO result_submissions(election_id,polling_station_id,candidate_id,result_version,votes,position_id,submission_hash,source_document_id,source_reference,observed_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(election_id,polling_station_id,candidate_id,result_version) DO UPDATE SET votes=EXCLUDED.votes,position_id=EXCLUDED.position_id,
                        submission_hash=EXCLUDED.submission_hash,source_document_id=EXCLUDED.source_document_id,source_reference=EXCLUDED.source_reference,observed_at=EXCLUDED.observed_at
                    """,(ELECTION_ID,s.station_id,cid,version,final,pid,h,source_document_id,f"SEED-RESULT-{s.station_id}-{pid}-V{version}",when))


def seed_published_aggregates(cur,source_document_id:int)->None:
    """Create independent publication totals for turnout and each contest's valid votes."""
    # Turnout publication covers the hierarchy because turnout is station-level and
    # can legitimately be aggregated through ward -> constituency -> county -> national.
    hierarchy={"WARD":"ward_id","CONSTITUENCY":"constituency_id","COUNTY":"county_id"}
    stations=cur.execute("""
        SELECT ps.polling_station_id,w.ward_id,c.constituency_id,co.county_id
        FROM polling_stations ps JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
        JOIN wards w ON w.ward_id=rc.ward_id JOIN constituencies c ON c.constituency_id=w.constituency_id
        JOIN counties co ON co.county_id=c.county_id WHERE ps.election_id=%s
    """,(ELECTION_ID,)).fetchall()
    turnout=cur.execute("""
        SELECT polling_station_id,voters_turnout FROM turnout_observations
        WHERE election_id=%s AND observation_version=(SELECT MAX(x.observation_version) FROM turnout_observations x WHERE x.election_id=turnout_observations.election_id AND x.polling_station_id=turnout_observations.polling_station_id)
    """,(ELECTION_ID,)).fetchall()
    tmap={r["polling_station_id"]:r["voters_turnout"] for r in turnout}
    totals={}
    for s in stations:
        for level,key in hierarchy.items(): totals[(level,s[key])]=totals.get((level,s[key]),0)+tmap.get(s["polling_station_id"],0)
        totals[("NATIONAL","NATIONAL")]=totals.get(("NATIONAL","NATIONAL"),0)+tmap.get(s["polling_station_id"],0)
    for (level,gid),value in totals.items():
        cur.execute("""
            INSERT INTO published_aggregate_totals(election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric,reported_value)
            VALUES(%s,%s,%s,%s,NULL,NULL,'TURNOUT',%s)
            ON CONFLICT(election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric) DO UPDATE SET reported_value=EXCLUDED.reported_value
        """,(ELECTION_ID,source_document_id,level,gid,value))

    latest=cur.execute("""
        SELECT DISTINCT ON(rs.election_id,rs.polling_station_id,rs.candidate_id) rs.polling_station_id,rs.candidate_id,rs.position_id,rs.votes,w.ward_id,c.constituency_id,co.county_id
        FROM result_submissions rs JOIN polling_stations ps ON ps.polling_station_id=rs.polling_station_id
        JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id JOIN wards w ON w.ward_id=rc.ward_id
        JOIN constituencies c ON c.constituency_id=w.constituency_id JOIN counties co ON co.county_id=c.county_id
        WHERE rs.election_id=%s ORDER BY rs.election_id,rs.polling_station_id,rs.candidate_id,rs.result_version DESC
    """,(ELECTION_ID,)).fetchall()
    geography={"POS-MCA":("WARD","ward_id"),"POS-MP":("CONSTITUENCY","constituency_id"),"POS-WOMEN-REP":("COUNTY","county_id"),"POS-SENATOR":("COUNTY","county_id"),"POS-GOVERNOR":("COUNTY","county_id"),"POS-PRESIDENT":("NATIONAL",None)}
    totals={}
    for r in latest:
        level,key=geography[r["position_id"]];gid="NATIONAL" if key is None else r[key]
        k=(level,gid,r["candidate_id"],r["position_id"]);totals[k]=totals.get(k,0)+r["votes"]
    for (level,gid,cid,pid),value in totals.items():
        # One publication is intentionally wrong to prove an aggregate failure.
        if level=="CONSTITUENCY" and gid=="CON001" and cid=="POS-MP-KE-C136-C001": value+=7
        cur.execute("""
            INSERT INTO published_aggregate_totals(election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric,reported_value)
            VALUES(%s,%s,%s,%s,%s,%s,'CANDIDATE_VOTES',%s)
            ON CONFLICT(election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric) DO UPDATE SET reported_value=EXCLUDED.reported_value
        """,(ELECTION_ID,source_document_id,level,gid,cid,pid,value))


def check(cur)->None:
    print("\nETVS SEED VERIFICATION\n"+"="*82)
    tables=("special_voting_slots","special_voting_area_reference_stations","positions","candidate_electoral_areas","elections","counties","constituencies","wards","registration_centres","polling_stations","turnout_reporting_intervals","registered_voter_observations","turnout_observations","ballot_accounting_observations","candidates","result_submissions","published_aggregate_totals","audit_runs","audit_findings")
    for table in tables:
        try: print(f"{table:38}{cur.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n']:>7}")
        except psycopg.errors.UndefinedTable: print(f"{table:38} MISSING")
    rows=cur.execute("""
        SELECT ps.polling_station_id,ps.registered_voters,ri.interval_minutes turnout_interval_minutes,ri.reporting_enabled,rv.registered_voters,t.voters_turnout,
               COUNT(DISTINCT b.position_id) contests,MIN(b.valid_votes+b.rejected_votes) min_accounted,MAX(b.valid_votes+b.rejected_votes) max_accounted,
               COUNT(DISTINCT rs.position_id) result_positions
        FROM polling_stations ps
        LEFT JOIN turnout_reporting_intervals ri ON ri.election_id=ps.election_id AND ri.polling_station_id=ps.polling_station_id AND ri.effective_to IS NULL
        LEFT JOIN registered_voter_observations rv ON rv.election_id=ps.election_id AND rv.polling_station_id=ps.polling_station_id AND rv.observation_version=(SELECT MAX(x.observation_version) FROM registered_voter_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id)
        LEFT JOIN turnout_observations t ON t.election_id=ps.election_id AND t.polling_station_id=ps.polling_station_id AND t.observation_version=(SELECT MAX(x.observation_version) FROM turnout_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id)
        LEFT JOIN ballot_accounting_observations b ON b.election_id=ps.election_id AND b.polling_station_id=ps.polling_station_id AND b.observation_version=(SELECT MAX(x.observation_version) FROM ballot_accounting_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id AND x.position_id=b.position_id)
        LEFT JOIN result_submissions rs ON rs.election_id=ps.election_id AND rs.polling_station_id=ps.polling_station_id
        WHERE ps.election_id=%s GROUP BY ps.polling_station_id,ps.registered_voters,ri.interval_minutes,ri.reporting_enabled,rv.registered_voters,t.voters_turnout ORDER BY ps.polling_station_id
    """,(ELECTION_ID,)).fetchall()
    print("\nSTATION COVERAGE")
    for r in rows:print(f"{r['polling_station_id']}: registered={r['registered_voters']} turnout={r['voters_turnout']} interval={r['turnout_interval_minutes']}min enabled={r['reporting_enabled']} contests={r['contests']} result_positions={r['result_positions']} accounting={r['min_accounted']}..{r['max_accounted']}")


def main()->int:
    p=argparse.ArgumentParser(description="Seed the ETVS PostgreSQL database.");p.add_argument("--reset",action="store_true");p.add_argument("--check",action="store_true");a=p.parse_args()
    try:
        with psycopg.connect(**db_kwargs()) as conn:
            with conn.cursor() as cur:
                ensure_schema(cur)
                if a.reset:reset_sample(cur)
                seed_positions(cur);source_doc,published_doc=seed_sources(cur);seed_master_data(cur);seed_special_voting_areas(cur,source_doc);seed_special_area_contest_rules(cur);seed_turnout_intervals(cur);seed_observations(cur,source_doc);seed_results(cur,source_doc);seed_published_aggregates(cur,published_doc);ensure_reporting_views(cur);check(cur)
            conn.commit()
        print("\nSEED SUCCESS: PostgreSQL data committed successfully.");return 0
    except Exception as exc:print(f"\nSEED FAILED: {exc}");return 1


if __name__=="__main__":raise SystemExit(main())