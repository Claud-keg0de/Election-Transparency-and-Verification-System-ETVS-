"""Manage configurable diaspora/prison special-voting slots.

Examples:
    python special_voting_slots.py list KE-PRES-2027
    python special_voting_slots.py add KE-PRES-2027 SVA-PRISONS
    python special_voting_slots.py activate KE-PRES-2027 SVS-PRISONS-001 --code 0492921451... --location "Example Prison" --registered-voters 100
    python special_voting_slots.py retire KE-PRES-2027 SVS-PRISONS-001
"""
from __future__ import annotations

import argparse
import os
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


def list_slots(cur, election_id: str) -> None:
    rows = cur.execute("""
        SELECT s.slot_code, s.slot_number, s.slot_status,
               a.voting_category, a.country_name, s.location_label,
               s.official_polling_station_code, s.registered_voters
        FROM special_voting_slots s
        JOIN special_voting_areas a
          ON a.special_voting_area_id=s.special_voting_area_id
        WHERE s.election_id=%s
        ORDER BY a.voting_category, a.country_name NULLS LAST, s.slot_number
    """, (election_id,)).fetchall()
    print("\nSPECIAL VOTING SLOTS")
    print("=" * 100)
    for r in rows:
        print(
            f"{r['slot_code']:28} {r['voting_category']:9} "
            f"{(r['country_name'] or 'Kenya prisons'):22} "
            f"{r['slot_status']:10} "
            f"{(r['location_label'] or '-'):28} "
            f"{(r['official_polling_station_code'] or '-'):20} "
            f"{r['registered_voters'] if r['registered_voters'] is not None else '-'}"
        )
    print(f"Total slots: {len(rows)}")


def add_slot(cur, election_id: str, area_id: str) -> None:
    area = cur.execute("""
        SELECT voting_category, country_name
        FROM special_voting_areas
        WHERE election_id=%s AND special_voting_area_id=%s
    """, (election_id, area_id)).fetchone()
    if not area:
        raise ValueError(f"Special voting area not found: {area_id}")

    row = cur.execute("""
        SELECT COALESCE(MAX(slot_number),0)+1 AS next_number
        FROM special_voting_slots
        WHERE election_id=%s AND special_voting_area_id=%s
    """, (election_id, area_id)).fetchone()
    number = row["next_number"]
    suffix = area_id.replace("SVA-", "")
    slot_code = f"SVS-{suffix}-{number:03d}"

    cur.execute("""
        INSERT INTO special_voting_slots(
            election_id,special_voting_area_id,slot_code,slot_number,
            slot_status,country_name,notes
        )
        VALUES(%s,%s,%s,%s,'PLANNED',%s,%s)
    """, (
        election_id, area_id, slot_code, number, area["country_name"],
        "Added as a configurable special-voting slot; activate only when official station data is available.",
    ))
    print(f"Added {slot_code} as PLANNED.")


def activate_slot(cur, election_id: str, slot_code: str, code: str, location: str, registered: int) -> None:
    row = cur.execute("""
        SELECT special_voting_slot_id
        FROM special_voting_slots
        WHERE election_id=%s AND slot_code=%s
    """, (election_id, slot_code)).fetchone()
    if not row:
        raise ValueError(f"Slot not found: {slot_code}")

    cur.execute("""
        UPDATE special_voting_slots
        SET slot_status='ACTIVE',
            official_polling_station_code=%s,
            location_label=%s,
            registered_voters=%s
        WHERE election_id=%s AND slot_code=%s
    """, (code, location, registered, election_id, slot_code))
    print(f"Activated {slot_code}.")


def change_status(cur, election_id: str, slot_code: str, status: str) -> None:
    cur.execute("""
        UPDATE special_voting_slots
        SET slot_status=%s
        WHERE election_id=%s AND slot_code=%s
    """, (status, election_id, slot_code))
    if cur.rowcount == 0:
        raise ValueError(f"Slot not found: {slot_code}")
    print(f"{slot_code} -> {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage ETVS special-voting slots.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("election_id")

    p_add = sub.add_parser("add")
    p_add.add_argument("election_id")
    p_add.add_argument("special_voting_area_id")

    p_activate = sub.add_parser("activate")
    p_activate.add_argument("election_id")
    p_activate.add_argument("slot_code")
    p_activate.add_argument("--code", required=True)
    p_activate.add_argument("--location", required=True)
    p_activate.add_argument("--registered-voters", required=True, type=int)

    for status in ("suspend", "retire"):
        p = sub.add_parser(status)
        p.add_argument("election_id")
        p.add_argument("slot_code")

    args = parser.parse_args()

    try:
        with psycopg.connect(**db_kwargs()) as conn:
            with conn.cursor() as cur:
                if args.command == "list":
                    list_slots(cur, args.election_id)
                elif args.command == "add":
                    add_slot(cur, args.election_id, args.special_voting_area_id)
                elif args.command == "activate":
                    if args.registered_voters < 0:
                        raise ValueError("registered-voters cannot be negative")
                    activate_slot(cur, args.election_id, args.slot_code, args.code, args.location, args.registered_voters)
                elif args.command == "suspend":
                    change_status(cur, args.election_id, args.slot_code, "SUSPENDED")
                elif args.command == "retire":
                    change_status(cur, args.election_id, args.slot_code, "RETIRED")
            conn.commit()
        return 0
    except Exception as exc:
        print(f"FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
