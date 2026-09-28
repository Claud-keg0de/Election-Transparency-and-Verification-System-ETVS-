"""Load Kenya's complete county/constituency/ward reference geography.

Source:
    CitizenGuide.KE ward export (compiled from public IEBC materials)
    https://www.citizenguide.ke/api/data/exports/wards?format=json

The loader intentionally does NOT create polling stations. Polling stations,
turnout observations, results and ballot accounting are the current ETVS
source-entry surface.

Examples:
    python tools/load_kenya_geography.py
    python tools/load_kenya_geography.py --input kenya_wards.json
    python tools/load_kenya_geography.py --check-only
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

import psycopg

SOURCE_URL = "https://www.citizenguide.ke/api/data/exports/wards?format=json"

COUNTY_CODES = {
    "Mombasa County":"001","Kwale County":"002","Kilifi County":"003","Tana River County":"004",
    "Lamu County":"005","Taita-Taveta County":"006","Garissa County":"007","Wajir County":"008",
    "Mandera County":"009","Marsabit County":"010","Isiolo County":"011","Meru County":"012",
    "Tharaka-Nithi County":"013","Embu County":"014","Kitui County":"015","Machakos County":"016",
    "Makueni County":"017","Nyandarua County":"018","Nyeri County":"019","Kirinyaga County":"020",
    "Murang'a County":"021","Kiambu County":"022","Turkana County":"023","West Pokot County":"024",
    "Samburu County":"025","Trans Nzoia County":"026","Uasin Gishu County":"027",
    "Elgeyo-Marakwet County":"028","Nandi County":"029","Baringo County":"030","Laikipia County":"031",
    "Nakuru County":"032","Narok County":"033","Kajiado County":"034","Kericho County":"035",
    "Bomet County":"036","Kakamega County":"037","Vihiga County":"038","Bungoma County":"039",
    "Busia County":"040","Siaya County":"041","Kisumu County":"042","Homa Bay County":"043",
    "Migori County":"044","Kisii County":"045","Nyamira County":"046","Nairobi County":"047",
}

# Six ETVS operational regions. This is metadata, not a constitutional tier.
REGION_BY_COUNTY = {
    "REG-01": {"Mombasa County","Kwale County","Kilifi County","Tana River County","Lamu County","Taita-Taveta County"},
    "REG-02": {"Machakos County","Makueni County","Kitui County","Kajiado County"},
    "REG-03": {"Nyandarua County","Nyeri County","Kirinyaga County","Murang'a County","Kiambu County","Meru County","Tharaka-Nithi County","Embu County","Laikipia County","Nairobi County"},
    "REG-04": {"Garissa County","Wajir County","Mandera County","Marsabit County","Isiolo County","Samburu County","Turkana County"},
    "REG-05": {"West Pokot County","Trans Nzoia County","Uasin Gishu County","Elgeyo-Marakwet County","Nandi County","Baringo County","Nakuru County","Narok County","Kericho County","Bomet County"},
    "REG-06": {"Kakamega County","Vihiga County","Bungoma County","Busia County","Siaya County","Kisumu County","Homa Bay County","Migori County","Kisii County","Nyamira County"},
}
REGION_NAMES = {
    "REG-01":"Coastal Region","REG-02":"South Eastern Region","REG-03":"Mt Kenya Region",
    "REG-04":"Northern Region","REG-05":"North Rift Valley Region","REG-06":"Western Region",
}


def db_kwargs() -> dict:
    return {
        "host": os.getenv("ETVS_DB_HOST", "localhost"),
        "port": int(os.getenv("ETVS_DB_PORT", "5432")),
        "dbname": os.getenv("ETVS_DB_NAME", "etvs"),
        "user": os.getenv("ETVS_DB_USER", "postgres"),
        "password": os.getenv("ETVS_DB_PASSWORD", ""),
    }


def load_json(path: str | None) -> list[dict]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    req = Request(SOURCE_URL, headers={"User-Agent":"ETVS-geography-loader/1.0"})
    with urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def validate(rows: list[dict]) -> tuple[dict[str,dict],dict[tuple[str,str],dict]]:
    required={"ward_code","name","constituency_name","county_name"}
    if not rows:
        raise ValueError("Ward dataset is empty.")
    if not all(required.issubset(r) for r in rows):
        raise ValueError("Ward dataset is missing one or more required fields.")
    counties={r["county_name"] for r in rows}
    constituencies={(r["county_name"],r["constituency_name"]) for r in rows}
    wards={r["ward_code"] for r in rows}
    if len(counties)!=47 or len(constituencies)!=290 or len(wards)!=1450:
        raise ValueError(f"Expected 47/290/1450; got {len(counties)}/{len(constituencies)}/{len(wards)}.")
    if set(COUNTY_CODES)!=counties:
        missing=set(COUNTY_CODES)-counties
        extra=counties-set(COUNTY_CODES)
        raise ValueError(f"County set mismatch. Missing={sorted(missing)} Extra={sorted(extra)}")
    for rid,names in REGION_BY_COUNTY.items():
        if not names:
            raise ValueError(f"Empty region {rid}")
    assigned=set().union(*REGION_BY_COUNTY.values())
    if assigned!=counties:
        raise ValueError("Six-region mapping does not cover exactly the 47 counties.")
    return (
        {name: {"county_id": COUNTY_CODES[name]} for name in counties},
        {(c,k): {"constituency_name":k} for c,k in constituencies},
    )


def region_for(county_name: str) -> str:
    for rid,names in REGION_BY_COUNTY.items():
        if county_name in names:
            return rid
    raise KeyError(county_name)


def load(rows: list[dict]) -> None:
    counties,_=validate(rows)
    # Stable constituency IDs are derived deterministically from the sorted
    # county/constituency pairs; the official ward code remains the ward ID.
    pairs=sorted({(r["county_name"],r["constituency_name"]) for r in rows})
    constituency_ids={pair:f"CON-{i:03d}" for i,pair in enumerate(pairs,1)}
    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS etvs_regions (
                    region_id TEXT PRIMARY KEY, region_name TEXT NOT NULL UNIQUE,
                    classification_type TEXT NOT NULL DEFAULT 'ETVS_OPERATIONAL',
                    classification_note TEXT NOT NULL
                )
            """)
            for rid,name in REGION_NAMES.items():
                cur.execute("""
                    INSERT INTO etvs_regions(region_id,region_name,classification_note)
                    VALUES(%s,%s,%s)
                    ON CONFLICT(region_id) DO UPDATE SET region_name=EXCLUDED.region_name
                """,(rid,name,"Six-region ETVS operational classification; not a constitutional county tier."))
            cur.execute("ALTER TABLE counties ADD COLUMN IF NOT EXISTS region_id TEXT")
            cur.execute("ALTER TABLE counties DROP CONSTRAINT IF EXISTS fk_county_region")
            cur.execute("ALTER TABLE counties ADD CONSTRAINT fk_county_region FOREIGN KEY(region_id) REFERENCES etvs_regions(region_id) ON UPDATE CASCADE ON DELETE RESTRICT")
            for county_name,meta in sorted(counties.items(),key=lambda x:x[1]["county_id"]):
                cur.execute("""
                    INSERT INTO counties(county_id,county_name,region_id)
                    VALUES(%s,%s,%s)
                    ON CONFLICT(county_id) DO UPDATE SET county_name=EXCLUDED.county_name,region_id=EXCLUDED.region_id
                """,(meta["county_id"],county_name,region_for(county_name)))
            for (county_name,constituency_name),cid in constituency_ids.items():
                cur.execute("""
                    INSERT INTO constituencies(constituency_id,constituency_name,county_id)
                    VALUES(%s,%s,%s)
                    ON CONFLICT(constituency_id) DO UPDATE SET constituency_name=EXCLUDED.constituency_name,county_id=EXCLUDED.county_id
                """,(cid,constituency_name,COUNTY_CODES[county_name]))
            for r in rows:
                cid=constituency_ids[(r["county_name"],r["constituency_name"])]
                cur.execute("""
                    INSERT INTO wards(ward_id,ward_name,constituency_id)
                    VALUES(%s,%s,%s)
                    ON CONFLICT(ward_id) DO UPDATE SET ward_name=EXCLUDED.ward_name,constituency_id=EXCLUDED.constituency_id
                """,(r["ward_code"],r["name"],cid))
        conn.commit()


def check_only(rows: list[dict]) -> None:
    validate(rows)
    print("REFERENCE DATA VALID: 47 counties / 290 constituencies / 1450 wards")


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",help="Local CitizenGuide JSON export.")
    parser.add_argument("--check-only",action="store_true")
    args=parser.parse_args()
    rows=load_json(args.input)
    if args.check_only:
        check_only(rows)
    else:
        load(rows)
        print("Loaded Kenya geography: 47 counties / 290 constituencies / 1450 wards")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
