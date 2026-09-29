"""Check that the ETVS PostgreSQL connection works and report the database
objects needed by the form-driven input workflow.

Environment variables:
  ETVS_DB_HOST (default localhost)
  ETVS_DB_PORT (default 5432)
  ETVS_DB_NAME (default etvs)
  ETVS_DB_USER (default postgres)
  ETVS_DB_PASSWORD (default empty)

For the Debian VM behind the existing VirtualBox NAT forwarding, use:
  ETVS_DB_HOST=127.0.0.1 ETVS_DB_PORT=5432 ...
when the script runs inside the VM, or port 5433 from Windows/DBeaver.
"""
from __future__ import annotations
import os
import psycopg

def main() -> int:
    kwargs = {
        "host": os.getenv("ETVS_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("ETVS_DB_PORT", "5432")),
        "dbname": os.getenv("ETVS_DB_NAME", "etvs"),
        "user": os.getenv("ETVS_DB_USER", "postgres"),
        "password": os.getenv("ETVS_DB_PASSWORD", ""),
    }
    print("ETVS PostgreSQL connection")
    print(f"  host={kwargs['host']} port={kwargs['port']} dbname={kwargs['dbname']} user={kwargs['user']}")
    try:
        with psycopg.connect(**kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user, version()")
                dbname, user, version = cur.fetchone()
                cur.execute("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema='public'
                      AND table_name IN (
                        'elections','etvs_regions','counties','constituencies','wards',
                        'registration_centres','polling_stations','positions','candidates',
                        'turnout_observations','result_submissions',
                        'ballot_accounting_observations','audit_runs','audit_findings'
                      )
                """)
                table_count = cur.fetchone()[0]
                cur.execute("""
                    SELECT
                      (SELECT COUNT(*) FROM counties),
                      (SELECT COUNT(*) FROM constituencies),
                      (SELECT COUNT(*) FROM wards),
                      (SELECT COUNT(*) FROM polling_stations),
                      (SELECT COUNT(*) FROM turnout_observations),
                      (SELECT COUNT(*) FROM result_submissions),
                      (SELECT COUNT(*) FROM ballot_accounting_observations)
                """)
                counts = cur.fetchone()
        print("  STATUS: CONNECTED")
        print(f"  database={dbname} user={user}")
        print(f"  required public tables present={table_count}/13")
        print(f"  geography: counties={counts[0]} constituencies={counts[1]} wards={counts[2]}")
        print(f"  operational data: stations={counts[3]} turnout={counts[4]} results={counts[5]} accounting={counts[6]}")
        print(f"  server={version}")
        return 0
    except Exception as exc:
        print(f"  STATUS: FAILED")
        print(f"  {type(exc).__name__}: {exc}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
