"""User-friendly turnout input for ETVS.

Commands:
    py turnout_input.py set-interval KE-PRES-2027 PS001 30
    py turnout_input.py record KE-PRES-2027 PS001 725

A reporting interval is versioned. Changing it closes the current interval
configuration and creates a new one; historical configurations and turnout
observations are never overwritten.

Turnout values are source observations. This input layer validates that the
value is a non-negative integer and that the polling station/configuration
exists, but deliberately does not reject turnout values that violate audit
rules. The audit engine must be able to detect such source anomalies.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from getpass import getpass

import psycopg
from psycopg.rows import dict_row


def db_kwargs() -> dict:
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


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def station_exists(cur, election_id: str, station_id: str) -> bool:
    return cur.execute(
        "SELECT 1 FROM polling_stations WHERE election_id=%s AND polling_station_id=%s",
        (election_id, station_id),
    ).fetchone() is not None


def current_interval(cur, election_id: str, station_id: str, at: datetime):
    return cur.execute(
        """
        SELECT turnout_interval_id,interval_minutes,effective_from,effective_to,reporting_enabled
        FROM turnout_reporting_intervals
        WHERE election_id=%s AND polling_station_id=%s
          AND effective_from <= %s
          AND (effective_to IS NULL OR effective_to > %s)
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        (election_id, station_id, at, at),
    ).fetchone()


def set_interval(election_id: str, station_id: str, minutes: int, effective_from: datetime) -> None:
    if minutes <= 0:
        raise ValueError("The turnout interval must be greater than 0 minutes.")

    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:
            if not station_exists(cur, election_id, station_id):
                raise ValueError(f"Polling station {station_id!r} does not exist in {election_id!r}.")

            current = cur.execute(
                """
                SELECT turnout_interval_id,interval_minutes,effective_from
                FROM turnout_reporting_intervals
                WHERE election_id=%s AND polling_station_id=%s AND effective_to IS NULL
                ORDER BY effective_from DESC
                LIMIT 1
                """,
                (election_id, station_id),
            ).fetchone()

            if current and effective_from <= current["effective_from"]:
                raise ValueError(
                    "The new effective time must be after the current configuration's effective time "
                    f"({current['effective_from'].isoformat()})."
                )

            if current:
                cur.execute(
                    """
                    UPDATE turnout_reporting_intervals
                    SET effective_to=%s
                    WHERE turnout_interval_id=%s AND effective_to IS NULL
                    """,
                    (effective_from, current["turnout_interval_id"]),
                )

            row = cur.execute(
                """
                INSERT INTO turnout_reporting_intervals(
                    election_id,polling_station_id,interval_minutes,effective_from,reporting_enabled
                )
                VALUES(%s,%s,%s,%s,TRUE)
                RETURNING turnout_interval_id,effective_from
                """,
                (election_id, station_id, minutes, effective_from),
            ).fetchone()
        conn.commit()

    previous = current["interval_minutes"] if current else None
    print(
        f"TURNOUT INTERVAL SET: {station_id} -> {minutes} minutes "
        f"from {row['effective_from'].isoformat()}."
    )
    if previous is not None:
        print(f"Previous interval ({previous} minutes) was closed and retained as history.")


def record_turnout(election_id: str, station_id: str, turnout: int, observed_at: datetime) -> None:
    if turnout < 0:
        raise ValueError("Voter turnout cannot be negative.")

    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:
            station = cur.execute(
                """
                SELECT registered_voters
                FROM polling_stations
                WHERE election_id=%s AND polling_station_id=%s
                """,
                (election_id, station_id),
            ).fetchone()
            if station is None:
                raise ValueError(f"Polling station {station_id!r} does not exist in {election_id!r}.")

            config = current_interval(cur, election_id, station_id, observed_at)
            if config is None:
                raise ValueError(
                    f"No turnout reporting interval is active for {station_id} at {observed_at.isoformat()}."
                )
            if not config["reporting_enabled"]:
                raise ValueError(f"Turnout reporting is disabled for {station_id} at that time.")

            previous = cur.execute(
                """
                SELECT observation_version,voters_turnout,observed_at
                FROM turnout_observations
                WHERE election_id=%s AND polling_station_id=%s
                ORDER BY observation_version DESC
                LIMIT 1
                """,
                (election_id, station_id),
            ).fetchone()
            next_version = (previous["observation_version"] + 1) if previous else 1

            row = cur.execute(
                """
                INSERT INTO turnout_observations(
                    election_id,polling_station_id,observation_version,
                    interval_configuration_id,voters_turnout,observed_at
                )
                VALUES(%s,%s,%s,%s,%s,%s)
                RETURNING turnout_observation_id,observation_version
                """,
                (
                    election_id,
                    station_id,
                    next_version,
                    config["turnout_interval_id"],
                    turnout,
                    observed_at,
                ),
            ).fetchone()
        conn.commit()

    print(
        f"TURNOUT RECORDED: {station_id} observation v{row['observation_version']} "
        f"= {turnout} voters at {observed_at.isoformat()}."
    )
    print(
        f"Registered voters: {station['registered_voters']} | "
        f"Configured interval: {config['interval_minutes']} minutes."
    )

    if previous:
        actual_minutes = (observed_at - previous["observed_at"]).total_seconds() / 60
        expected = config["interval_minutes"]
        status = "ON TIME" if round(actual_minutes, 6) == expected else "TIMING WARNING"
        print(
            f"{status}: {actual_minutes:g} minutes since v{previous['observation_version']}; "
            f"expected {expected} minutes."
        )
    else:
        expected_at = config["effective_from"]
        expected_minutes = (observed_at - expected_at).total_seconds() / 60
        status = "ON TIME" if round(expected_minutes, 6) == config["interval_minutes"] else "TIMING WARNING"
        print(
            f"{status}: first entry is {expected_minutes:g} minutes after the interval start; "
            f"expected {config['interval_minutes']} minutes."
        )

    if turnout > station["registered_voters"]:
        print(
            "AUDIT NOTICE: turnout exceeds registered voters. The value was retained "
            "as source evidence so the audit engine can report the anomaly."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Enter ETVS turnout data without overwriting source observations.")
    sub = parser.add_subparsers(dest="command", required=True)

    interval = sub.add_parser("set-interval", help="Set a station-specific turnout reporting interval.")
    interval.add_argument("election_id")
    interval.add_argument("polling_station_id")
    interval.add_argument("minutes", type=int)
    interval.add_argument(
        "--effective-from",
        help="ISO-8601 timestamp. Defaults to the current UTC time.",
    )

    record = sub.add_parser("record", help="Record one immutable turnout observation.")
    record.add_argument("election_id")
    record.add_argument("polling_station_id")
    record.add_argument("turnout", type=int)
    record.add_argument(
        "--observed-at",
        help="ISO-8601 timestamp. Defaults to the current UTC time.",
    )

    args = parser.parse_args()
    try:
        if args.command == "set-interval":
            set_interval(
                args.election_id,
                args.polling_station_id,
                args.minutes,
                parse_timestamp(args.effective_from),
            )
        else:
            record_turnout(
                args.election_id,
                args.polling_station_id,
                args.turnout,
                parse_timestamp(args.observed_at),
            )
        return 0
    except Exception as exc:
        print(f"TURNOUT INPUT FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
