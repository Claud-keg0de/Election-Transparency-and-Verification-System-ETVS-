"""Seed the current ETVS PostgreSQL schema with deterministic test data.

This script is intentionally PostgreSQL-specific and matches the hardened ETVS
schema used by the current project. It inserts source/master data and deliberately
includes a few controlled anomalies so audit_engine.py can prove that its rules work.

Usage:
    py seed.py
    py seed.py --reset
    py seed.py --check

Connection settings come from environment variables:
    ETVS_DB_HOST      default: localhost
    ETVS_DB_PORT      default: 5432
    ETVS_DB_NAME      default: etvs
    ETVS_DB_USER      default: postgres
    ETVS_DB_PASSWORD  optional; if omitted, psycopg asks for it.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from getpass import getpass

import psycopg
from psycopg.rows import dict_row

ELECTION_ID = "KE-PRES-2027"
SOURCE_ID = "SRC-ETVS-SAMPLE"
PUBLISHED_SOURCE_ID = "SRC-PUBLISHED-AGGREGATES"
DOCUMENT_NAME = "ETVS sample election observations"
PUBLISHED_DOCUMENT_NAME = "Published aggregate results comparison"
POSITIONS = (
    ("POS-PRESIDENT", "President", "PRESIDENT", "NATIONAL"),
    ("POS-GOVERNOR", "Governor", "GOVERNOR", "COUNTY"),
    ("POS-SENATOR", "Senator", "SENATOR", "COUNTY"),
    ("POS-WOMEN-REP", "Women Representative", "WOMEN_REP", "COUNTY"),
    ("POS-MP", "Member of Parliament", "MP", "CONSTITUENCY"),
    ("POS-MCA", "Member of County Assembly", "MCA", "WARD"),
)


@dataclass(frozen=True)
class StationSeed:
    station_id: str
    code: str
    centre_id: str
    registered: int
    turnout: int
    valid: int
    rejected: int
    spoilt: int


STATIONS = (
    StationSeed("PS001", "PS-001", "RC001", 1000, 700, 680, 15, 5),
    StationSeed("PS002", "PS-002", "RC002", 800, 500, 480, 15, 5),
    # Controlled anomaly: turnout is greater than registered voters.
    StationSeed("PS003", "PS-003", "RC003", 950, 1000, 960, 25, 15),
    StationSeed("PS004", "PS-004", "RC004", 1200, 900, 850, 30, 20),
    # Controlled anomaly: ballot components total 440, but turnout is 450.
    StationSeed("PS005", "PS-005", "RC005", 600, 450, 420, 15, 5),
    # Controlled anomaly: candidate total will be greater than turnout.
    StationSeed("PS006", "PS-006", "RC006", 700, 650, 650, 30, 0),
)

CANDIDATE_VOTES = {
    "PS001": {"CAND001": 350, "CAND002": 220, "CAND003": 110},
    "PS002": {"CAND001": 250, "CAND002": 150, "CAND003": 80},
    "PS003": {"CAND001": 500, "CAND002": 300, "CAND003": 160},
    "PS004": {"CAND001": 430, "CAND002": 270, "CAND003": 150},
    "PS005": {"CAND001": 210, "CAND002": 140, "CAND003": 70},
    # Total = 680 while turnout = 650: deliberate Rule 2 anomaly.
    "PS006": {"CAND001": 400, "CAND002": 180, "CAND003": 100},
}


def connection_kwargs() -> dict:
    password = os.getenv("ETVS_DB_PASSWORD")
    if password is None:
        password = getpass("PostgreSQL password for user postgres: ")
    return {
        "host": os.getenv("ETVS_DB_HOST", "localhost"),
        "port": int(os.getenv("ETVS_DB_PORT", "5432")),
        "dbname": os.getenv("ETVS_DB_NAME", "etvs"),
        "user": os.getenv("ETVS_DB_USER", "postgres"),
        "password": password,
        "row_factory": dict_row,
    }


def digest(*parts: object) -> str:
    """Create a stable SHA-256 fingerprint for a seeded observation/result."""
    payload = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reset_sample(cur) -> None:
    """Delete only the sample election, in dependency-safe order."""
    cur.execute("DELETE FROM source_comparisons WHERE election_id = %s", (ELECTION_ID,))
    cur.execute(
        """
        DELETE FROM submission_validation_results
        WHERE source_submission_id IN (
            SELECT source_submission_id
            FROM source_submissions
            WHERE election_id = %s
        )
        """,
        (ELECTION_ID,),
    )
    cur.execute("DELETE FROM source_submissions WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM audit_position_results WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM audit_passed_results WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM audit_failed_results WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM audit_findings WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM audit_runs WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM result_submissions WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM published_aggregate_totals WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM ballot_accounting_observations WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM turnout_observations WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM polling_stations WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM candidates WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM registration_centres WHERE registration_centre_id LIKE 'RC00%'")
    cur.execute("DELETE FROM wards WHERE ward_id LIKE 'W00%'")
    cur.execute("DELETE FROM constituencies WHERE constituency_id IN ('CON001', 'CON002')")
    cur.execute("DELETE FROM counties WHERE county_id = 'COUNTY001'")
    cur.execute("DELETE FROM elections WHERE election_id = %s", (ELECTION_ID,))
    cur.execute("DELETE FROM source_documents WHERE source_id = %s", (SOURCE_ID,))
    cur.execute("DELETE FROM source_documents WHERE source_id = %s", (PUBLISHED_SOURCE_ID,))
    cur.execute("DELETE FROM sources WHERE source_id = %s", (SOURCE_ID,))
    cur.execute("DELETE FROM sources WHERE source_id = %s", (PUBLISHED_SOURCE_ID,))


def ensure_positions_table(cur) -> None:
    """Ensure the positions master table exists before any position foreign keys are added."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            position_id TEXT PRIMARY KEY,
            position_name TEXT NOT NULL UNIQUE,
            election_level TEXT NOT NULL,
            geography_level TEXT NOT NULL
        )
    """)


def ensure_reporting_views(cur) -> None:
    """Create station-oriented reporting views used by the audit output/dashboard."""
    cur.execute("""
        CREATE OR REPLACE VIEW v_audit_station_findings AS
        SELECT f.audit_finding_id, f.audit_run_id, f.election_id,
               f.polling_station_id, ps.polling_station_code, f.position_id,
               f.rule_code, f.status, f.actual_label, f.actual_value,
               f.comparison_label, f.comparison_value, f.message, f.created_at
        FROM audit_findings f
        LEFT JOIN polling_stations ps
          ON ps.polling_station_id = f.polling_station_id
         AND ps.election_id = f.election_id
        WHERE f.polling_station_id IS NOT NULL
    """)
    cur.execute("""
        CREATE OR REPLACE VIEW v_audit_station_summary AS
        SELECT f.audit_run_id, f.election_id, f.polling_station_id,
               COUNT(*)::INTEGER AS rules_checked,
               COUNT(*) FILTER (WHERE f.status = 'PASSED')::INTEGER AS passed_count,
               COUNT(*) FILTER (WHERE f.status = 'FAILED')::INTEGER AS failed_count,
               COUNT(*) FILTER (WHERE f.status = 'WARNING')::INTEGER AS warning_count,
               CASE WHEN COUNT(*) FILTER (WHERE f.status = 'FAILED') > 0 THEN 'FAILED'
                    WHEN COUNT(*) FILTER (WHERE f.status = 'WARNING') > 0 THEN 'WARNING'
                    ELSE 'PASSED' END AS station_status
        FROM audit_findings f
        WHERE f.polling_station_id IS NOT NULL
        GROUP BY f.audit_run_id, f.election_id, f.polling_station_id
    """)


def seed_positions(cur) -> None:
    for position_id, name, election_level, geography_level in POSITIONS:
        cur.execute(
            """
            INSERT INTO positions (position_id, position_name, election_level, geography_level)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (position_id) DO UPDATE SET
                position_name = EXCLUDED.position_name,
                election_level = EXCLUDED.election_level,
                geography_level = EXCLUDED.geography_level
            """,
            (position_id, name, election_level, geography_level),
        )


def ensure_provenance_schema(cur) -> None:
    """Apply the additive provenance migration to an existing ETVS database."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (
            position_id TEXT PRIMARY KEY,
            position_name TEXT NOT NULL UNIQUE,
            election_level TEXT NOT NULL,
            geography_level TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            organization_name TEXT,
            description TEXT,
            source_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT sources_type_check
                CHECK (source_type IN ('OFFICIAL', 'MEDIA', 'CIVIL_SOCIETY', 'OTHER'))
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS source_documents (
            document_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(source_id)
                ON UPDATE CASCADE ON DELETE RESTRICT,
            document_name TEXT NOT NULL,
            document_type TEXT NOT NULL,
            document_uri TEXT,
            content_hash TEXT NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT source_document_hash_format
                CHECK (content_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT unique_source_document
                UNIQUE (source_id, document_name, content_hash)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS published_aggregate_totals (
            published_aggregate_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id),
            aggregation_level TEXT NOT NULL,
            geography_id TEXT NOT NULL,
            candidate_id TEXT,
            position_id TEXT,
            metric TEXT NOT NULL,
            reported_value INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE NULLS NOT DISTINCT (election_id, source_document_id,
                    aggregation_level, geography_id, candidate_id, position_id, metric)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS source_submissions (
            source_submission_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id),
            position_id TEXT REFERENCES positions(position_id),
            submission_level TEXT NOT NULL,
            geography_id TEXT NOT NULL,
            candidate_id TEXT,
            payload JSONB NOT NULL,
            submission_hash TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (election_id, source_document_id, submission_level,
                    geography_id, candidate_id, submission_hash)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS submission_validation_results (
            validation_result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_submission_id BIGINT NOT NULL UNIQUE REFERENCES source_submissions(source_submission_id),
            status TEXT NOT NULL,
            error_message TEXT,
            validated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for table in (
        "turnout_observations",
        "ballot_accounting_observations",
        "result_submissions",
    ):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS source_document_id BIGINT")
    # Position is a first-class election concept.  Add it to legacy databases
    # before any seed query references result_submissions.position_id.
    cur.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS submission_hash TEXT")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS position_id TEXT")

    # Backfill position_id on existing result rows from their candidate.
    cur.execute(
        """
        UPDATE result_submissions rs
        SET position_id = c.position_id
        FROM candidates c
        WHERE c.candidate_id = rs.candidate_id
          AND c.election_id = rs.election_id
          AND rs.position_id IS NULL
        """
    )

    # Add the FK once the column exists and existing rows have been backfilled.
    cur.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_result_position'
            ) THEN
                ALTER TABLE result_submissions
                ADD CONSTRAINT fk_result_position
                FOREIGN KEY (position_id)
                REFERENCES positions(position_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT;
            END IF;
        END $$;
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_results_position ON result_submissions(position_id)"
    )

    cur.execute("ALTER TABLE published_aggregate_totals ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS scope_level TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS scope_id TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS candidate_id TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS candidate_id TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS geography_level TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS geography_id TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS position_id TEXT")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_passed_results (
            audit_passed_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            audit_finding_id BIGINT NOT NULL UNIQUE REFERENCES audit_findings(audit_finding_id),
            audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id),
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            candidate_id TEXT, geography_level TEXT, geography_id TEXT,
            position_id TEXT,
            polling_station_id TEXT, rule_code TEXT NOT NULL, message TEXT NOT NULL,
            actual_value INTEGER, comparison_value INTEGER,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_failed_results (
            audit_failed_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            audit_finding_id BIGINT NOT NULL UNIQUE REFERENCES audit_findings(audit_finding_id),
            audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id),
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            candidate_id TEXT, geography_level TEXT, geography_id TEXT,
            position_id TEXT,
            polling_station_id TEXT, rule_code TEXT NOT NULL, message TEXT NOT NULL,
            actual_value INTEGER, comparison_value INTEGER,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS source_comparisons (
            source_comparison_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id),
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            published_document_id BIGINT NOT NULL REFERENCES source_documents(document_id),
            derived_source_document_id BIGINT REFERENCES source_documents(document_id),
            aggregation_level TEXT NOT NULL, geography_id TEXT NOT NULL,
            candidate_id TEXT, position_id TEXT, metric TEXT NOT NULL, published_value INTEGER,
            derived_value INTEGER, difference INTEGER, status TEXT NOT NULL,
            compared_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_position_results (
            audit_position_result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id),
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            position_id TEXT NOT NULL REFERENCES positions(position_id),
            passed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (audit_run_id, position_id)
        )
        """
    )

    # Ensure semantic audit-value columns exist before foreign-key setup.
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS actual_label TEXT NOT NULL DEFAULT 'Actual value'")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS comparison_label TEXT NOT NULL DEFAULT 'Comparison value'")
    cur.execute("ALTER TABLE audit_passed_results ADD COLUMN IF NOT EXISTS actual_label TEXT NOT NULL DEFAULT 'Actual value'")
    cur.execute("ALTER TABLE audit_passed_results ADD COLUMN IF NOT EXISTS comparison_label TEXT NOT NULL DEFAULT 'Comparison value'")
    cur.execute("ALTER TABLE audit_failed_results ADD COLUMN IF NOT EXISTS actual_label TEXT NOT NULL DEFAULT 'Actual value'")
    cur.execute("ALTER TABLE audit_failed_results ADD COLUMN IF NOT EXISTS comparison_label TEXT NOT NULL DEFAULT 'Comparison value'")

    cur.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE published_aggregate_totals ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_passed_results ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_failed_results ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE source_comparisons ADD COLUMN IF NOT EXISTS position_id TEXT")

    # Keep every position_id column tied to the same positions master table.
    # This makes the live database match the foreign-key relationships in schema.sql.
    position_fks = (
        ("candidates", "fk_candidate_position"),
        ("published_aggregate_totals", "fk_published_aggregate_position"),
        ("audit_runs", "fk_audit_run_position"),
        ("audit_findings", "fk_finding_position"),
        ("audit_passed_results", "fk_passed_position"),
        ("audit_failed_results", "fk_failed_position"),
        ("source_comparisons", "fk_source_comparison_position"),
    )
    for table, constraint in position_fks:
        cur.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = '{constraint}'
                ) THEN
                    ALTER TABLE {table}
                    ADD CONSTRAINT {constraint}
                    FOREIGN KEY (position_id)
                    REFERENCES positions(position_id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT;
                END IF;
            END $$;
            """
        )

    constraints = (
        ("turnout_observations", "fk_turnout_source_document"),
        ("ballot_accounting_observations", "fk_ballot_source_document"),
        ("result_submissions", "fk_result_source_document"),
    )
    for table, constraint in constraints:
        cur.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = '{constraint}'
                ) THEN
                    ALTER TABLE {table}
                    ADD CONSTRAINT {constraint}
                    FOREIGN KEY (source_document_id)
                    REFERENCES source_documents(document_id)
                    ON UPDATE CASCADE ON DELETE RESTRICT;
                END IF;
            END $$;
            """
        )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_source_documents_source ON source_documents(source_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_turnout_source_document ON turnout_observations(source_document_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ballot_source_document ON ballot_accounting_observations(source_document_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_results_source_document ON result_submissions(source_document_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_results_submission_hash ON result_submissions(submission_hash)")
    cur.execute("ALTER TABLE audit_passed_results ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_failed_results ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE source_comparisons ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'unique_published_aggregate'
            ) THEN
                ALTER TABLE published_aggregate_totals
                DROP CONSTRAINT unique_published_aggregate;
            END IF;
            ALTER TABLE published_aggregate_totals
            ADD CONSTRAINT unique_published_aggregate
            UNIQUE NULLS NOT DISTINCT (election_id, source_document_id,
                aggregation_level, geography_id, candidate_id, position_id, metric);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def seed_provenance(cur) -> tuple[int, int]:
    def source_document(source_id: str, source_name: str, document_name: str) -> int:
        document_hash = digest("ETVS-SOURCE", ELECTION_ID, source_id, document_name)
        cur.execute(
            """
            INSERT INTO sources
                (source_id, source_name, source_type, organization_name, description)
            VALUES (%s, %s, 'OTHER', %s, %s)
            ON CONFLICT (source_id) DO UPDATE SET
                source_name = EXCLUDED.source_name,
                organization_name = EXCLUDED.organization_name,
                description = EXCLUDED.description
            """,
            (source_id, source_name, "ETVS project", "Controlled provenance source for comparison."),
        )
        document = cur.execute(
            """
            INSERT INTO source_documents
                (source_id, document_name, document_type, document_uri, content_hash)
            VALUES (%s, %s, 'SEEDED_DATASET', %s, %s)
            ON CONFLICT (source_id, document_name, content_hash)
            DO UPDATE SET document_uri = EXCLUDED.document_uri
            RETURNING document_id
            """,
            (source_id, document_name, "seed.py", document_hash),
        ).fetchone()
        return int(document["document_id"])

    observation_document_id = source_document(
        SOURCE_ID, "ETVS controlled sample source", DOCUMENT_NAME
    )
    published_document_id = source_document(
        PUBLISHED_SOURCE_ID, "Published aggregate comparison source", PUBLISHED_DOCUMENT_NAME
    )
    return observation_document_id, published_document_id


def seed(cur) -> None:
    seed_positions(cur)
    source_document_id, published_document_id = seed_provenance(cur)
    # ------------------------------------------------------------------
    # 1. Election and administrative hierarchy
    # ------------------------------------------------------------------
    cur.execute(
        """
        INSERT INTO elections (election_id, election_name, election_date, status)
        VALUES (%s, %s, %s, 'ACTIVE')
        ON CONFLICT (election_id) DO NOTHING
        """,
        (ELECTION_ID, "ETVS Presidential Election 2027", "2027-08-10"),
    )

    cur.execute(
        """
        INSERT INTO counties (county_id, county_name)
        VALUES ('COUNTY001', 'Sample County')
        ON CONFLICT (county_id) DO NOTHING
        """
    )

    for cid, name in (("CON001", "Greenfield Constituency"), ("CON002", "Riverdale Constituency")):
        cur.execute(
            """
            INSERT INTO constituencies (constituency_id, constituency_name, county_id)
            VALUES (%s, %s, 'COUNTY001')
            ON CONFLICT (constituency_id) DO NOTHING
            """,
            (cid, name),
        )

    wards = (
        ("W001", "Greenfield Central", "CON001"),
        ("W002", "Greenfield East", "CON001"),
        ("W003", "Riverdale Central", "CON002"),
        ("W004", "Riverdale East", "CON002"),
    )
    for wid, name, cid in wards:
        cur.execute(
            """
            INSERT INTO wards (ward_id, ward_name, constituency_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (ward_id) DO NOTHING
            """,
            (wid, name, cid),
        )

    centres = (
        ("RC001", "Greenfield Primary School", "W001"),
        ("RC002", "Greenfield Community Hall", "W002"),
        ("RC003", "Greenfield Secondary School", "W001"),
        ("RC004", "Riverdale Primary School", "W003"),
        ("RC005", "Riverdale Community Hall", "W004"),
        ("RC006", "Riverdale Secondary School", "W003"),
    )
    for rid, name, wid in centres:
        cur.execute(
            """
            INSERT INTO registration_centres
                (registration_centre_id, registration_centre_name, ward_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (registration_centre_id) DO NOTHING
            """,
            (rid, name, wid),
        )

    # ------------------------------------------------------------------
    # 2. Election-specific polling stations and candidates
    # ------------------------------------------------------------------
    for s in STATIONS:
        cur.execute(
            """
            INSERT INTO polling_stations
                (polling_station_id, election_id, registration_centre_id,
                 polling_station_code, registered_voters)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (polling_station_id) DO UPDATE SET
                election_id = EXCLUDED.election_id,
                registration_centre_id = EXCLUDED.registration_centre_id,
                polling_station_code = EXCLUDED.polling_station_code,
                registered_voters = EXCLUDED.registered_voters
            """,
            (s.station_id, ELECTION_ID, s.centre_id, s.code, s.registered),
        )

    candidates = (
        ("CAND001", "Amina Njeri", "PRESIDENT"),
        ("CAND002", "Brian Wanyonyi", "PRESIDENT"),
        ("CAND003", "David Mwangi", "PRESIDENT"),
    )
    for candidate_id, name, office in candidates:
        cur.execute(
            """
            INSERT INTO candidates
                (candidate_id, election_id, candidate_name, office, position_id)
            VALUES (%s, %s, %s, %s, 'POS-PRESIDENT')
            ON CONFLICT (candidate_id) DO UPDATE SET
                election_id = EXCLUDED.election_id,
                candidate_name = EXCLUDED.candidate_name,
                office = EXCLUDED.office,
                position_id = 'POS-PRESIDENT'
            """,
            (candidate_id, ELECTION_ID, name, office),
        )

    # ------------------------------------------------------------------
    # 3. Independent turnout observations
    # ------------------------------------------------------------------
    for s in STATIONS:
        observation_hash = digest("TURNOUT", ELECTION_ID, s.station_id, 1, s.turnout)
        cur.execute(
            """
            INSERT INTO turnout_observations
                (election_id, polling_station_id, observation_version,
                  voters_turnout, source_document_id, source_reference)
              VALUES (%s, %s, 1, %s, %s, %s)
            ON CONFLICT (election_id, polling_station_id, observation_version)
            DO UPDATE SET voters_turnout = EXCLUDED.voters_turnout,
                          source_document_id = EXCLUDED.source_document_id,
                          source_reference = EXCLUDED.source_reference
            """,
            (ELECTION_ID, s.station_id, s.turnout, source_document_id, observation_hash),
        )

    # ------------------------------------------------------------------
    # 4. Independent ballot-accounting observations
    # ------------------------------------------------------------------
    for s in STATIONS:
        cur.execute(
            """
            INSERT INTO ballot_accounting_observations
                (election_id, polling_station_id, observation_version,
                  valid_votes, rejected_votes, spoilt_ballots,
                  source_document_id, source_reference)
              VALUES (%s, %s, 1, %s, %s, %s, %s, %s)
            ON CONFLICT (election_id, polling_station_id, observation_version)
            DO UPDATE SET valid_votes = EXCLUDED.valid_votes,
                          rejected_votes = EXCLUDED.rejected_votes,
                          spoilt_ballots = EXCLUDED.spoilt_ballots,
                          source_document_id = EXCLUDED.source_document_id,
                          source_reference = EXCLUDED.source_reference
            """,
            (
                ELECTION_ID,
                s.station_id,
                s.valid,
                s.rejected,
                s.spoilt,
                source_document_id,
                f"SEED-BALLOT-{s.station_id}",
            ),
        )

    # ------------------------------------------------------------------
    # 5. Candidate result submissions
    # ------------------------------------------------------------------
    for station_id, candidate_votes in CANDIDATE_VOTES.items():
        for candidate_id, votes in candidate_votes.items():
            # PS005 deliberately receives a second version for one candidate.
            versions = (1, 2) if station_id == "PS005" and candidate_id == "CAND001" else (1,)
            for version in versions:
                final_votes = votes + 5 if version == 2 else votes
                cur.execute(
                    """
                    INSERT INTO result_submissions
                        (election_id, polling_station_id, candidate_id,
                        result_version, votes, position_id, submission_hash,
                        source_document_id, source_reference)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (election_id, polling_station_id, candidate_id, result_version)
                    DO UPDATE SET votes = EXCLUDED.votes,
                                  position_id = EXCLUDED.position_id,
                                  submission_hash = EXCLUDED.submission_hash,
                                  source_document_id = EXCLUDED.source_document_id,
                                  source_reference = EXCLUDED.source_reference
                    """,
                    (
                        ELECTION_ID,
                        station_id,
                        candidate_id,
                        version,
                        final_votes,
                        "POS-PRESIDENT",
                        digest("RESULT", ELECTION_ID, station_id, candidate_id, version, final_votes),
                        source_document_id,
                        f"SEED-RESULT-{station_id}-V{version}",
                    ),
                )

    seed_published_aggregates(cur, published_document_id)


def seed_published_aggregates(cur, source_document_id: int) -> None:
    """Seed a second-source publication derived independently from stations."""
    rows = cur.execute(
        """
        WITH latest_results AS (
            SELECT rs.*
            FROM result_submissions rs
            JOIN (
                SELECT election_id, polling_station_id, candidate_id,
                       MAX(result_version) AS result_version
                FROM result_submissions
                WHERE election_id = %s
                GROUP BY election_id, polling_station_id, candidate_id
            ) latest
              ON latest.election_id = rs.election_id
             AND latest.polling_station_id = rs.polling_station_id
             AND latest.candidate_id = rs.candidate_id
             AND latest.result_version = rs.result_version
        )
        SELECT ps.polling_station_id, w.ward_id, c.constituency_id,
               cty.county_id, t.voters_turnout, lr.candidate_id, lr.votes,
               lr.position_id
        FROM polling_stations ps
        JOIN registration_centres rc ON rc.registration_centre_id = ps.registration_centre_id
        JOIN wards w ON w.ward_id = rc.ward_id
        JOIN constituencies c ON c.constituency_id = w.constituency_id
        JOIN counties cty ON cty.county_id = c.county_id
        LEFT JOIN turnout_observations t
          ON t.election_id = ps.election_id
         AND t.polling_station_id = ps.polling_station_id
         AND t.observation_version = (
             SELECT MAX(t2.observation_version)
             FROM turnout_observations t2
             WHERE t2.election_id = ps.election_id
               AND t2.polling_station_id = ps.polling_station_id
         )
        LEFT JOIN latest_results lr
          ON lr.election_id = ps.election_id
         AND lr.polling_station_id = ps.polling_station_id
        WHERE ps.election_id = %s
        """,
        (ELECTION_ID, ELECTION_ID),
    ).fetchall()

    levels = {
        "WARD": "ward_id",
        "CONSTITUENCY": "constituency_id",
        "COUNTY": "county_id",
    }
    aggregates: dict[tuple[str, str, str | None, str | None], int] = {}
    counted_stations: set[str] = set()
    for row in rows:
        for level, key in levels.items():
            geography_id = row[key]
            if row["polling_station_id"] not in counted_stations:
                turnout_key = (level, geography_id, None, None)
                aggregates[turnout_key] = aggregates.get(turnout_key, 0) + (row["voters_turnout"] or 0)
            if row["candidate_id"] is not None:
                result_key = (level, geography_id, row["candidate_id"], row["position_id"])
                aggregates[result_key] = aggregates.get(result_key, 0) + row["votes"]

        if row["polling_station_id"] not in counted_stations:
            national_turnout_key = ("NATIONAL", "NATIONAL", None, None)
            aggregates[national_turnout_key] = aggregates.get(national_turnout_key, 0) + (row["voters_turnout"] or 0)
            counted_stations.add(row["polling_station_id"])
        if row["candidate_id"] is not None:
            national_result_key = ("NATIONAL", "NATIONAL", row["candidate_id"], row["position_id"])
            aggregates[national_result_key] = aggregates.get(national_result_key, 0) + row["votes"]

    for (level, geography_id, candidate_id, position_id), value in aggregates.items():
        if level == "CONSTITUENCY" and geography_id == "CON001" and candidate_id == "CAND001":
            value += 7
        cur.execute(
            """
            INSERT INTO published_aggregate_totals
                (election_id, source_document_id, aggregation_level,
                  geography_id, candidate_id, position_id, metric, reported_value)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (election_id, source_document_id, aggregation_level,
                        geography_id, candidate_id, position_id, metric)
            DO UPDATE SET reported_value = EXCLUDED.reported_value
            """,
            (
                ELECTION_ID, source_document_id, level, geography_id, candidate_id, position_id,
                "TURNOUT" if candidate_id is None else "CANDIDATE_VOTES", value,
            ),
        )


def check(cur) -> None:
    print("\nETVS SEED VERIFICATION")
    print("=" * 72)
    tables = (
        "positions",
        "sources", "source_documents",
        "elections", "counties", "constituencies", "wards",
        "registration_centres", "polling_stations", "candidates",
        "published_aggregate_totals",
        "turnout_observations", "ballot_accounting_observations",
        "result_submissions", "audit_runs", "audit_findings",
        "audit_passed_results", "audit_failed_results", "source_comparisons",
        "audit_position_results",
        "source_submissions", "submission_validation_results",
    )
    for table in tables:
        row = cur.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        print(f"{table:35} {row['n']:>6}")

    provenance = cur.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM turnout_observations WHERE source_document_id IS NOT NULL)
            + (SELECT COUNT(*) FROM ballot_accounting_observations WHERE source_document_id IS NOT NULL)
            + (SELECT COUNT(*) FROM result_submissions WHERE source_document_id IS NOT NULL)
            AS linked_observations
        """
    ).fetchone()
    print(f"{'provenance-linked observations':35} {provenance['linked_observations']:>6}")

    rows = cur.execute(
        """
        SELECT
            ps.polling_station_id,
            ps.registered_voters,
            t.voters_turnout,
            b.valid_votes,
            b.rejected_votes,
            b.spoilt_ballots,
            COALESCE(SUM(rs.votes), 0) AS candidate_votes
        FROM polling_stations ps
        LEFT JOIN turnout_observations t
          ON t.polling_station_id = ps.polling_station_id
         AND t.election_id = ps.election_id
         AND t.observation_version = (
             SELECT MAX(t2.observation_version)
             FROM turnout_observations t2
             WHERE t2.polling_station_id = ps.polling_station_id
               AND t2.election_id = ps.election_id
         )
        LEFT JOIN ballot_accounting_observations b
          ON b.polling_station_id = ps.polling_station_id
         AND b.election_id = ps.election_id
         AND b.observation_version = (
             SELECT MAX(b2.observation_version)
             FROM ballot_accounting_observations b2
             WHERE b2.polling_station_id = ps.polling_station_id
               AND b2.election_id = ps.election_id
         )
        LEFT JOIN result_submissions rs
          ON rs.polling_station_id = ps.polling_station_id
         AND rs.election_id = ps.election_id
         AND rs.result_version = (
             SELECT MAX(rs2.result_version)
             FROM result_submissions rs2
             WHERE rs2.polling_station_id = ps.polling_station_id
               AND rs2.election_id = ps.election_id
               AND rs2.candidate_id = rs.candidate_id
         )
        WHERE ps.election_id = %s
        GROUP BY ps.polling_station_id, ps.registered_voters,
                 t.voters_turnout, b.valid_votes, b.rejected_votes, b.spoilt_ballots
        ORDER BY ps.polling_station_id
        """,
        (ELECTION_ID,),
    ).fetchall()

    print("\nSTATION TEST DATA")
    print("-" * 72)
    for r in rows:
        print(
            f"{r['polling_station_id']}: registered={r['registered_voters']}, "
            f"turnout={r['voters_turnout']}, valid={r['valid_votes']}, "
            f"rejected={r['rejected_votes']}, spoilt={r['spoilt_ballots']}, "
            f"candidate_votes={r['candidate_votes']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the ETVS PostgreSQL database.")
    parser.add_argument("--reset", action="store_true", help="Replace the KE-PRES-2027 sample data first.")
    parser.add_argument("--check", action="store_true", help="Verify the seeded row counts and values.")
    args = parser.parse_args()

    try:
        with psycopg.connect(**connection_kwargs()) as conn:
            with conn.cursor() as cur:
                ensure_provenance_schema(cur)
                ensure_positions_table(cur)
                ensure_reporting_views(cur)
                if args.reset:
                    reset_sample(cur)
                seed(cur)
                check(cur)
            conn.commit()
        print("\nSEED SUCCESS: PostgreSQL data committed successfully.")
        if args.check:
            print("CHECK SUCCESS: Seed verification completed.")
        return 0
    except Exception as exc:
        print(f"\nSEED FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
