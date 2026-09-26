"""Diagnose a failing seed without hiding the SQL statement or parameters.

This helper imports the existing seed functions and wraps cursor.execute so a
PostgreSQL parameter-count error identifies the exact SQL statement. It is a
one-off troubleshooting tool and does not commit any changes.
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

import seed


class TracingCursor:
    """Proxy cursor that prints the failing SQL and parameter tuple."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        try:
            return self._cursor.execute(query, params)
        except Exception as exc:
            print("\nSEED SQL ERROR")
            print("=" * 80)
            print(f"Exception: {exc}")
            print("Parameters:", repr(params))
            print("SQL:")
            print(query)
            print("=" * 80)
            raise

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def main() -> int:
    try:
        with psycopg.connect(**seed.db_kwargs()) as conn:
            with conn.cursor() as raw:
                cur = TracingCursor(raw)
                # Reproduce the normal seed sequence but roll it back. This is
                # intentionally diagnostic only; no sample data is committed.
                seed.ensure_schema(cur)
                seed.reset_sample(cur)
                seed.seed_positions(cur)
                source_doc, published_doc = seed.seed_sources(cur)
                seed.seed_master_data(cur)
                seed.seed_observations(cur, source_doc)
                seed.seed_results(cur, source_doc)
                seed.seed_published_aggregates(cur, published_doc)
            conn.rollback()
        print("Seed diagnostic completed without reproducing an SQL error.")
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
