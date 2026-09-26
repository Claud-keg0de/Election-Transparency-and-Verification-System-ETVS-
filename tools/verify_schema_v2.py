"""Read-only verification for the ETVS schema v2 contract.

Usage:
    py verify_schema_v2.py
    py verify_schema_v2.py KE-PRES-2027
"""
from __future__ import annotations

import argparse
import os
from getpass import getpass

import psycopg
from psycopg.rows import dict_row

ELECTION_ID = "KE-PRES-2027"

PUBLIC_REQUIRED = {
    "registered_voter_observations",
    "election_positions",
}

PRIVATE_REQUIRED = {
    "electors",
    "device_capabilities",
    "devices",
    "device_capability_assignments",
    "elector_ballot_artifacts",
    "counterfoil_artifacts",
    "ballot_artifact_validations",
    "ballot_artifact_validation_checks",
    "ballot_artifact_security_links",
}

FORBIDDEN_CHOICE_COLUMNS = {
    "candidate_id",
    "vote_choice",
    "choice",
    "selected_candidate_id",
}


def db_kwargs() -> dict:
    password = os.getenv("ETVS_DB_PASSWORD")
    if password is None:
        password = getpass("PostgreSQL password: ")
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

    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:
            public_tables = {
                r["table_name"]
                for r in cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema='public' AND table_type='BASE TABLE'
                """).fetchall()
            }

            private_tables = {
                r["table_name"]
                for r in cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema='etvs_private' AND table_type='BASE TABLE'
                """).fetchall()
            }

            for table in sorted(PUBLIC_REQUIRED - public_tables):
                failures.append(f"Missing public table: {table}")
            for table in sorted(PRIVATE_REQUIRED - private_tables):
                failures.append(f"Missing private table: etvs_private.{table}")

            columns = {}
            for table in sorted(PRIVATE_REQUIRED):
                if table not in private_tables:
                    continue
                columns[table] = {
                    r["column_name"]
                    for r in cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema='etvs_private'
                          AND table_name=%s
                    """, (table,)).fetchall()
                }
                forbidden = columns[table] & FORBIDDEN_CHOICE_COLUMNS
                if forbidden:
                    failures.append(
                        f"Ballot-secrecy violation: etvs_private.{table} contains "
                        f"choice column(s): {sorted(forbidden)}"
                    )

            # The corrected ballot-accounting uniqueness must contain position_id.
            unique_keys = cur.execute("""
                SELECT tc.constraint_name,
                       string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position) AS columns
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON kcu.constraint_name=tc.constraint_name
                 AND kcu.table_schema=tc.table_schema
                 AND kcu.table_name=tc.table_name
                WHERE tc.table_schema='public'
                  AND tc.table_name='ballot_accounting_observations'
                  AND tc.constraint_type='UNIQUE'
                GROUP BY tc.constraint_name
            """).fetchall()
            if not any(
                r["columns"] == "election_id,polling_station_id,position_id,observation_version"
                for r in unique_keys
            ):
                failures.append(
                    "Missing six-contest ballot-accounting key: "
                    "(election_id,polling_station_id,position_id,observation_version)"
                )

            # Applicable contests are data-driven rather than hard-coded.
            missing_positions = cur.execute("""
                SELECT COUNT(*) AS n
                FROM public.election_positions ep
                LEFT JOIN public.positions p ON p.position_id=ep.position_id
                WHERE ep.election_id=%s
                  AND ep.enabled
                  AND p.position_id IS NULL
            """, (args.election_id,)).fetchone()["n"]
            if missing_positions:
                failures.append(f"Enabled election positions without position definitions: {missing_positions}")

            invalid_validation = cur.execute("""
                SELECT COUNT(*) AS n
                FROM etvs_private.ballot_artifact_validation_checks
                WHERE availability_status='NOT_AVAILABLE'
                  AND result_status <> 'NOT_AVAILABLE'
            """).fetchone()["n"]
            if invalid_validation:
                failures.append(
                    f"Device-capability availability/result mismatch rows: {invalid_validation}"
                )

            elector_context = cur.execute("""
                SELECT COUNT(*) AS n
                FROM etvs_private.elector_ballot_artifacts a
                JOIN etvs_private.electors e ON e.elector_id=a.elector_id
                WHERE a.election_id <> e.election_id
            """).fetchone()["n"]
            if elector_context:
                failures.append(f"Elector/artifact election mismatches: {elector_context}")

            print("\nETVS SCHEMA V2 VERIFICATION")
            print("=" * 72)
            print(f"Election: {args.election_id}")
            print(f"Public v2 tables present: {len(PUBLIC_REQUIRED & public_tables)}/{len(PUBLIC_REQUIRED)}")
            print(f"Private v2 tables present: {len(PRIVATE_REQUIRED & private_tables)}/{len(PRIVATE_REQUIRED)}")
            print(f"Enabled contests: {cur.execute('SELECT COUNT(*) AS n FROM public.election_positions WHERE election_id=%s AND enabled', (args.election_id,)).fetchone()['n']}")
            print("-" * 72)

            if failures:
                print("SCHEMA V2 VERIFICATION: FAILED")
                for failure in failures:
                    print(f" - {failure}")
                return 1

            print("SIX-CONTEST ACCOUNTING KEY: PASS")
            print("ELECTION-SPECIFIC CONTEST CONFIGURATION: PASS")
            print("ELECTOR/CHOICE SEPARATION: PASS")
            print("DEVICE-AWARE VALIDATION STATUS: PASS")
            print("ELECTOR/ARTIFACT CONTEXT: PASS")
            print("SCHEMA V2 VERIFICATION: PASS")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
