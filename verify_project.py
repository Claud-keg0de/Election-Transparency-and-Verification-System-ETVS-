"""Verify that the live PostgreSQL ETVS database matches the project contract.

Usage:
    py verify_project.py
    py verify_project.py KE-PRES-2027

This is read-only. It never changes the database.
"""
from __future__ import annotations

import argparse
import os
from getpass import getpass

import psycopg
from psycopg.rows import dict_row

ELECTION_ID = "KE-PRES-2027"

REQUIRED_COLUMNS = {
    "positions": {"position_id", "position_name", "election_level", "geography_level"},
    "candidates": {"candidate_id", "election_id", "candidate_name", "office", "position_id"},
    "result_submissions": {
        "result_submission_id", "election_id", "polling_station_id",
        "candidate_id", "result_version", "votes", "position_id",
        "submission_hash", "source_document_id",
    },
    "published_aggregate_totals": {
        "published_aggregate_id", "election_id", "source_document_id",
        "aggregation_level", "geography_id", "candidate_id", "position_id",
        "metric", "reported_value",
    },
    "polling_stations": {
        "polling_station_id", "election_id", "registration_centre_id",
        "polling_station_code", "registered_voters",
        "turnout_reporting_interval_minutes",
    },
    "turnout_observations": {
        "turnout_observation_id", "election_id", "polling_station_id",
        "observation_version", "voters_turnout", "source_document_id",
    },
    "ballot_accounting_observations": {
        "ballot_accounting_observation_id", "election_id",
        "polling_station_id", "observation_version", "valid_votes",
        "rejected_votes", "spoilt_ballots", "source_document_id",
    },
    "audit_runs": {
        "audit_run_id", "election_id", "scope_level", "scope_id",
        "candidate_id", "position_id", "status", "findings_count",
    },
    "audit_findings": {
        "audit_finding_id", "audit_run_id", "election_id",
        "polling_station_id", "candidate_id", "position_id",
        "geography_level", "geography_id", "rule_code", "status",
        "actual_label", "actual_value", "comparison_label", "comparison_value", "message",
        "previous_hash", "current_hash",
    },
}

REQUIRED_FKS = {
    "fk_candidate_position",
    "fk_result_position",
    "fk_published_aggregate_position",
    "fk_audit_run_position",
    "fk_finding_position",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("election_id", nargs="?", default=ELECTION_ID)
    args = parser.parse_args()

    failures: list[str] = []

    try:
        with psycopg.connect(**connection_kwargs()) as conn:
            with conn.cursor() as cur:
                tables = {
                    r["table_name"]
                    for r in cur.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_type = 'BASE TABLE'
                        """
                    ).fetchall()
                }

                for table, columns in REQUIRED_COLUMNS.items():
                    if table not in tables:
                        failures.append(f"Missing table: {table}")
                        continue
                    actual = {
                        r["column_name"]
                        for r in cur.execute(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = %s
                            """,
                            (table,),
                        ).fetchall()
                    }
                    for column in sorted(columns - actual):
                        failures.append(f"Missing column: {table}.{column}")

                constraints = {
                    r["constraint_name"]
                    for r in cur.execute(
                        """
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_schema = 'public'
                          AND constraint_type = 'FOREIGN KEY'
                        """
                    ).fetchall()
                }
                for fk in sorted(REQUIRED_FKS - constraints):
                    failures.append(f"Missing position FK: {fk}")

                print("\nETVS PROJECT CONSISTENCY CHECK")
                print("=" * 72)
                print(f"Election: {args.election_id}")

                checks = [
                    ("positions", "SELECT COUNT(*) AS n FROM positions"),
                    ("candidates", "SELECT COUNT(*) AS n FROM candidates WHERE election_id = %s"),
                    ("polling_stations", "SELECT COUNT(*) AS n FROM polling_stations WHERE election_id = %s"),
                    ("turnout_observations", "SELECT COUNT(*) AS n FROM turnout_observations WHERE election_id = %s"),
                    ("ballot_accounting_observations", "SELECT COUNT(*) AS n FROM ballot_accounting_observations WHERE election_id = %s"),
                    ("result_submissions", "SELECT COUNT(*) AS n FROM result_submissions WHERE election_id = %s"),
                    ("published_aggregate_totals", "SELECT COUNT(*) AS n FROM published_aggregate_totals WHERE election_id = %s"),
                ]
                for label, sql in checks:
                    row = cur.execute(sql, (args.election_id,) if "%s" in sql else ()).fetchone()
                    print(f"{label:35} {row['n']}")

                orphan = cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM result_submissions rs
                    LEFT JOIN candidates c
                      ON c.candidate_id = rs.candidate_id
                     AND c.election_id = rs.election_id
                    WHERE rs.election_id = %s
                      AND (rs.position_id IS NULL OR c.position_id IS DISTINCT FROM rs.position_id)
                    """,
                    (args.election_id,),
                ).fetchone()["n"]
                if orphan:
                    failures.append(f"Result position mismatch rows: {orphan}")

                interval_invalid = cur.execute("""
                    SELECT COUNT(*) AS n
                    FROM polling_stations
                    WHERE election_id = %s
                      AND (turnout_reporting_interval_minutes < 1
                           OR turnout_reporting_interval_minutes > 1440)
                """, (args.election_id,)).fetchone()["n"]
                if interval_invalid:
                    failures.append(f"Invalid polling-station turnout intervals: {interval_invalid}")

                interval_violations = cur.execute("""
                    WITH ordered AS (
                        SELECT ps.polling_station_id,
                               ps.turnout_reporting_interval_minutes,
                               t.observed_at,
                               LAG(t.observed_at) OVER (
                                   PARTITION BY t.election_id,t.polling_station_id
                                   ORDER BY t.observed_at,t.observation_version
                               ) previous_observed_at
                        FROM polling_stations ps
                        JOIN turnout_observations t
                          ON t.election_id=ps.election_id
                         AND t.polling_station_id=ps.polling_station_id
                        WHERE ps.election_id=%s
                    )
                    SELECT COUNT(*) AS n
                    FROM ordered
                    WHERE previous_observed_at IS NOT NULL
                      AND observed_at < previous_observed_at
                            + (turnout_reporting_interval_minutes * INTERVAL '1 minute')
                """, (args.election_id,)).fetchone()["n"]
                if interval_violations:
                    failures.append(f"Turnout reporting interval violations: {interval_violations}")

                invalid_hash = cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM result_submissions
                    WHERE election_id = %s
                      AND submission_hash IS NULL
                    """,
                    (args.election_id,),
                ).fetchone()["n"]
                if invalid_hash:
                    failures.append(f"Result submissions without hashes: {invalid_hash}")

                print("-" * 72)
                if failures:
                    print("CONSISTENCY FAILED")
                    for failure in failures:
                        print(f" - {failure}")
                    return 1

                print("SCHEMA CONTRACT: PASS")
                print("POSITION RELATIONSHIPS: PASS")
                print("RESULT/CANDIDATE POSITION ALIGNMENT: PASS")
                print("RESULT SUBMISSION HASH PRESENCE: PASS")
                print("TURNOUT INTERVAL CONFIGURATION: PASS")
                print("TURNOUT INTERVAL ENFORCEMENT DATA CHECK: PASS")
                print("CONSISTENCY: PASS")
                return 0

    except Exception as exc:
        print(f"CONSISTENCY CHECK FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
