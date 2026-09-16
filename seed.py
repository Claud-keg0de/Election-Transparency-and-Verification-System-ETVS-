"""Seed deterministic ETVS PostgreSQL test data.

The seed deliberately models the election as six separate contests while keeping
ONE turnout figure per polling station.  Every contest's ballot accounting points
back to that same station turnout observation, so voters are never double-counted.

The data also contains controlled anomalies for the audit engine:
- PS003 turnout is greater than registered voters (R001).
- PS005 has a ballot-accounting mismatch and a changed result version.
- PS006 has candidate votes above turnout (R002).
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


STATIONS = (
    StationSeed("PS001", "PS-001", "RC001", 1000, 700),
    StationSeed("PS002", "PS-002", "RC002", 800, 500),
    StationSeed("PS003", "PS-003", "RC003", 950, 1000),  # R001 anomaly
    StationSeed("PS004", "PS-004", "RC004", 1200, 900),
    StationSeed("PS005", "PS-005", "RC005", 600, 450),
    StationSeed("PS006", "PS-006", "RC006", 700, 650),
)

# Base contest-level ballot counts.  Each contest has its own accounting because
# a voter may spoil/reject one ballot paper without doing so on another paper.
BASE_ACCOUNTING = {
    "PS001": (680, 20, 5),
    "PS002": (480, 20, 5),
    "PS003": (960, 40, 15),
    "PS004": (850, 50, 20),
    "PS005": (420, 20, 5),
    "PS006": (620, 30, 0),
}

# Three candidates are supplied for every contest.  The final candidate total is
# normally exactly the contest's valid-ballot total.  PS006 intentionally exceeds
# turnout for the President contest to prove R002 independently of other contests.
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
    return {
        "host": os.getenv("ETVS_DB_HOST", "localhost"),
        "port": int(os.getenv("ETVS_DB_PORT", "5432")),
        "dbname": os.getenv("ETVS_DB_NAME", "etvs"),
        "user": os.getenv("ETVS_DB_USER", "postgres"),
        "password": password,
        "row_factory": dict_row,
    }


def digest(*parts: object) -> str:
    """Return a deterministic SHA-256 digest for a seeded record."""
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def ensure_schema(cur) -> None:
    """Additive compatibility layer for databases created before the redesign."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            position_id TEXT PRIMARY KEY, position_name TEXT NOT NULL UNIQUE,
            election_level TEXT NOT NULL, geography_level TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS registered_voter_observations (
            registered_voter_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            polling_station_id TEXT NOT NULL REFERENCES polling_stations(polling_station_id),
            observation_version INTEGER NOT NULL CHECK (observation_version > 0),
            registered_voters INTEGER NOT NULL CHECK (registered_voters >= 0),
            observed_at TIMESTAMPTZ NOT NULL,
            source_document_id BIGINT,
            source_reference TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (election_id, polling_station_id, observation_version)
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_registered_latest ON registered_voter_observations(election_id, polling_station_id, observation_version DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ballot_latest_position ON ballot_accounting_observations(election_id, polling_station_id, position_id, observation_version DESC)")

    # Source tables are created here only for old installations.  The migration
    # remains the authoritative production schema; this makes seed.py repeatable.
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
            UNIQUE (source_id, document_name, content_hash)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS published_aggregate_totals (
            published_aggregate_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id),
            source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id),
            aggregation_level TEXT NOT NULL, geography_id TEXT NOT NULL, candidate_id TEXT,
            position_id TEXT, metric TEXT NOT NULL, reported_value INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE NULLS NOT DISTINCT (election_id, source_document_id, aggregation_level,
                geography_id, candidate_id, position_id, metric)
        )
    """)


def ensure_reporting_views(cur) -> None:
    """Create stable dashboard views without changing source observations."""
    cur.execute("""
        CREATE OR REPLACE VIEW v_audit_station_findings AS
        SELECT f.audit_finding_id, f.audit_run_id, f.election_id, f.polling_station_id,
               ps.polling_station_code, f.position_id, f.rule_code, f.status,
               f.actual_label, f.actual_value, f.comparison_label, f.comparison_value,
               f.message, f.created_at
        FROM audit_findings f
        LEFT JOIN polling_stations ps ON ps.polling_station_id = f.polling_station_id
        WHERE f.polling_station_id IS NOT NULL
    """)
    cur.execute("""
        CREATE OR REPLACE VIEW v_audit_station_summary AS
        SELECT audit_run_id, election_id, polling_station_id,
               COUNT(*)::INTEGER AS rules_checked,
               COUNT(*) FILTER (WHERE status='PASSED')::INTEGER AS passed_count,
               COUNT(*) FILTER (WHERE status='FAILED')::INTEGER AS failed_count,
               COUNT(*) FILTER (WHERE status='WARNING')::INTEGER AS warning_count,
               CASE WHEN COUNT(*) FILTER (WHERE status='FAILED') > 0 THEN 'FAILED'
                    WHEN COUNT(*) FILTER (WHERE status='WARNING') > 0 THEN 'WARNING'
                    ELSE 'PASSED' END AS station_status
        FROM audit_findings WHERE polling_station_id IS NOT NULL
        GROUP BY audit_run_id, election_id, polling_station_id
    """)


def seed_positions(cur) -> None:
    for pid, name, office, geography, ballot_code, sequence in POSITIONS:
        cur.execute("""
            INSERT INTO positions(position_id, position_name, election_level, geography_level,
                                  ballot_code, observation_sequence)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT(position_id) DO UPDATE SET position_name=EXCLUDED.position_name,
                election_level=EXCLUDED.election_level, geography_level=EXCLUDED.geography_level,
                ballot_code=EXCLUDED.ballot_code, observation_sequence=EXCLUDED.observation_sequence
        """, (pid, name, office, geography, ballot_code, sequence))


def seed_sources(cur) -> tuple[int, int]:
    """Create deterministic source documents so every observation is traceable."""
    for sid, name in ((SOURCE_ID, "ETVS controlled sample source"),
                      (PUBLISHED_SOURCE_ID, "Published aggregate comparison source")):
        cur.execute("""
            INSERT INTO sources(source_id,source_name,source_type,organization_name,description)
            VALUES(%s,%s,'OTHER','ETVS project','Controlled provenance source for the sample dataset.')
            ON CONFLICT(source_id) DO UPDATE SET source_name=EXCLUDED.source_name
        """, (sid, name))
    ids = []
    for sid, name in ((SOURCE_ID, "ETVS sample election observations"),
                      (PUBLISHED_SOURCE_ID, "Published aggregate results comparison")):
        h = digest("SOURCE", ELECTION_ID, sid, name)
        row = cur.execute("""
            INSERT INTO source_documents(source_id,document_name,document_type,document_uri,content_hash)
            VALUES(%s,%s,'SEEDED_DATASET','seed.py',%s)
            ON CONFLICT(source_id,document_name,content_hash) DO UPDATE SET document_uri='seed.py'
            RETURNING document_id
        """, (sid, name, h)).fetchone()
        ids.append(int(row["document_id"]))
    return tuple(ids)


def reset_sample(cur) -> None:
    """Delete only ETVS sample rows, leaving unrelated elections untouched."""
    # Child tables first: this keeps --reset safe when the database contains old runs.
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
        "DELETE FROM polling_stations WHERE election_id=%s",
        "DELETE FROM candidates WHERE election_id=%s",
        "DELETE FROM elections WHERE election_id=%s",
    ):
        try:
            cur.execute(sql, (ELECTION_ID,))
        except psycopg.errors.UndefinedTable:
            pass
    for table, column, values in (
        ("registration_centres", "registration_centre_id", ["RC001","RC002","RC003","RC004","RC005","RC006"]),
        ("wards", "ward_id", ["W001","W002","W003","W004"]),
        ("constituencies", "constituency_id", ["CON001","CON002"]),
        ("counties", "county_id", ["COUNTY001"]),
    ):
        cur.execute(f"DELETE FROM {table} WHERE {column}=ANY(%s)", (values,))
    cur.execute("DELETE FROM source_documents WHERE source_id IN (%s,%s)", (SOURCE_ID, PUBLISHED_SOURCE_ID))
    cur.execute("DELETE FROM sources WHERE source_id IN (%s,%s)", (SOURCE_ID, PUBLISHED_SOURCE_ID))


def seed_master_data(cur) -> None:
    cur.execute("INSERT INTO elections(election_id,election_name,election_date,status) VALUES(%s,'ETVS Sample Election 2027','2027-08-10','ACTIVE') ON CONFLICT DO NOTHING", (ELECTION_ID,))
    cur.execute("INSERT INTO counties(county_id,county_name) VALUES('COUNTY001','Sample County') ON CONFLICT DO NOTHING")
    for cid, name in (("CON001","Greenfield Constituency"),("CON002","Riverdale Constituency")):
        cur.execute("INSERT INTO constituencies(constituency_id,constituency_name,county_id) VALUES(%s,%s,'COUNTY001') ON CONFLICT DO NOTHING", (cid,name))
    wards = (("W001","Greenfield Central","CON001"),("W002","Greenfield East","CON001"),("W003","Riverdale Central","CON002"),("W004","Riverdale East","CON002"))
    for wid,name,cid in wards:
        cur.execute("INSERT INTO wards(ward_id,ward_name,constituency_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (wid,name,cid))
    centres = (("RC001","Greenfield Primary School","W001"),("RC002","Greenfield Community Hall","W002"),("RC003","Greenfield Secondary School","W001"),("RC004","Riverdale Primary School","W003"),("RC005","Riverdale Community Hall","W004"),("RC006","Riverdale Secondary School","W003"))
    for rid,name,wid in centres:
        cur.execute("INSERT INTO registration_centres(registration_centre_id,registration_centre_name,ward_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (rid,name,wid))
    for s in STATIONS:
        cur.execute("""
            INSERT INTO polling_stations(polling_station_id,election_id,registration_centre_id,polling_station_code,registered_voters)
            VALUES(%s,%s,%s,%s,%s)
            ON CONFLICT(polling_station_id) DO UPDATE SET election_id=EXCLUDED.election_id,
                registration_centre_id=EXCLUDED.registration_centre_id,polling_station_code=EXCLUDED.polling_station_code,
                registered_voters=EXCLUDED.registered_voters
        """, (s.station_id,ELECTION_ID,s.centre_id,s.code,s.registered))

    # Each office has its own candidates.  This prevents President votes from ever
    # being accidentally combined with MCA/MP/etc. in an aggregate query.
    offices = [(p[0], p[1]) for p in POSITIONS]
    for pid, pname in offices:
        for n, name in ((1,"Amina Njeri"),(2,"Brian Wanyonyi"),(3,"David Mwangi")):
            cid = f"{pid}-C{n:03d}"
            cur.execute("""
                INSERT INTO candidates(candidate_id,election_id,candidate_name,office,position_id)
                VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(candidate_id) DO UPDATE SET candidate_name=EXCLUDED.candidate_name,
                    office=EXCLUDED.office,position_id=EXCLUDED.position_id
            """, (cid,ELECTION_ID,name,pname,pid))


def seed_observations(cur, source_document_id: int) -> None:
    """Insert registered voters, one shared turnout stream, and six ballot streams."""
    base_time = datetime(2027, 8, 10, 8, 0, tzinfo=timezone.utc)
    for i, s in enumerate(STATIONS):
        # Registered voters are the first election-day observation for the station.
        observed = base_time + timedelta(minutes=i)
        cur.execute("""
            INSERT INTO registered_voter_observations
                (election_id,polling_station_id,observation_version,registered_voters,observed_at,source_document_id,source_reference)
            VALUES(%s,%s,1,%s,%s,%s,%s)
            ON CONFLICT(election_id,polling_station_id,observation_version) DO UPDATE SET
                registered_voters=EXCLUDED.registered_voters,observed_at=EXCLUDED.observed_at,
                source_document_id=EXCLUDED.source_document_id,source_reference=EXCLUDED.source_reference
        """, (ELECTION_ID,s.station_id,s.registered,observed,source_document_id,f"SEED-REGISTERED-{s.station_id}-V1"))

        # Version 1 is an initial count; version 2 is the final turnout.  The same
        # final turnout observation is referenced by all six contest ballot rows.
        t1 = observed + timedelta(hours=3)
        t2 = observed + timedelta(hours=7)
        initial = max(0, s.turnout - (5 if s.station_id == "PS005" else 0))
        for version, turnout, when in ((1, initial, t1), (2, s.turnout, t2)):
            ref = digest("TURNOUT",ELECTION_ID,s.station_id,version,turnout)
            cur.execute("""
                INSERT INTO turnout_observations
                    (election_id,polling_station_id,observation_version,voters_turnout,source_document_id,source_reference,observed_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(election_id,polling_station_id,observation_version) DO UPDATE SET
                    voters_turnout=EXCLUDED.voters_turnout,source_document_id=EXCLUDED.source_document_id,
                    source_reference=EXCLUDED.source_reference,observed_at=EXCLUDED.observed_at
            """, (ELECTION_ID,s.station_id,version,turnout,source_document_id,ref,when))
        turnout_row = cur.execute("SELECT turnout_observation_id FROM turnout_observations WHERE election_id=%s AND polling_station_id=%s AND observation_version=2", (ELECTION_ID,s.station_id)).fetchone()
        turnout_id = turnout_row["turnout_observation_id"]

        valid, rejected, spoilt = BASE_ACCOUNTING[s.station_id]
        # PS005: deliberately makes valid+rejected=440 instead of turnout 450.
        if s.station_id == "PS005":
            rejected = 20
        for pid, *_ in POSITIONS:
            when = t2 + timedelta(minutes=10 + POSITIONS.index(next(p for p in POSITIONS if p[0] == pid)))
            cur.execute("""
                INSERT INTO ballot_accounting_observations
                    (election_id,polling_station_id,position_id,observation_version,valid_votes,rejected_votes,spoilt_ballots,turnout_observation_id,source_document_id,source_reference,observed_at)
                VALUES(%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(election_id,polling_station_id,position_id,observation_version) DO UPDATE SET
                    valid_votes=EXCLUDED.valid_votes,rejected_votes=EXCLUDED.rejected_votes,
                    spoilt_ballots=EXCLUDED.spoilt_ballots,turnout_observation_id=EXCLUDED.turnout_observation_id,
                    source_document_id=EXCLUDED.source_document_id,source_reference=EXCLUDED.source_reference,observed_at=EXCLUDED.observed_at
            """, (ELECTION_ID,s.station_id,pid,valid,rejected,spoilt,turnout_id,source_document_id,f"SEED-BALLOT-{s.station_id}-{pid}",when))


def votes_for(valid: int, split: tuple[float,float,float]) -> tuple[int,int,int]:
    a = int(valid * split[0]); b = int(valid * split[1]); c = valid - a - b
    return a,b,c


def seed_results(cur, source_document_id: int) -> None:
    """Insert contest-specific candidate results and a controlled version change."""
    for s in STATIONS:
        for pid, *_ in POSITIONS:
            valid, _, _ = BASE_ACCOUNTING[s.station_id]
            v1 = votes_for(valid, VOTE_SPLITS[s.station_id])
            for n, votes in enumerate(v1, 1):
                cid = f"{pid}-C{n:03d}"
                versions = (1,2) if s.station_id == "PS005" and pid == "POS-PRESIDENT" and n == 1 else (1,)
                for version in versions:
                    final_votes = votes + 5 if version == 2 else votes
                    when = datetime(2027,8,10,18,0,tzinfo=timezone.utc) + timedelta(minutes=len(pid)+n+version)
                    h = digest("RESULT",ELECTION_ID,s.station_id,cid,version,final_votes)
                    cur.execute("""
                        INSERT INTO result_submissions
                            (election_id,polling_station_id,candidate_id,result_version,votes,position_id,submission_hash,source_document_id,source_reference,observed_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(election_id,polling_station_id,candidate_id,result_version) DO UPDATE SET
                            votes=EXCLUDED.votes,position_id=EXCLUDED.position_id,submission_hash=EXCLUDED.submission_hash,
                            source_document_id=EXCLUDED.source_document_id,source_reference=EXCLUDED.source_reference,observed_at=EXCLUDED.observed_at
                    """, (ELECTION_ID,s.station_id,cid,version,final_votes,pid,h,source_document_id,f"SEED-RESULT-{s.station_id}-{pid}-V{version}",when))


def seed_published_aggregates(cur, source_document_id: int) -> None:
    """Publish station-derived candidate totals at the legally relevant geography level."""
    # Only the contest's own geography receives a candidate aggregate:
    # MCA->WARD, MP->CONSTITUENCY, three county contests->COUNTY, President->NATIONAL.
    latest = cur.execute("""
        SELECT DISTINCT ON (rs.election_id,rs.polling_station_id,rs.candidate_id)
               rs.polling_station_id,rs.candidate_id,rs.position_id,rs.votes,
               w.ward_id,c.constituency_id,co.county_id
        FROM result_submissions rs
        JOIN polling_stations ps ON ps.polling_station_id=rs.polling_station_id
        JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
        JOIN wards w ON w.ward_id=rc.ward_id
        JOIN constituencies c ON c.constituency_id=w.constituency_id
        JOIN counties co ON co.county_id=c.county_id
        WHERE rs.election_id=%s
        ORDER BY rs.election_id,rs.polling_station_id,rs.candidate_id,rs.result_version DESC
    """, (ELECTION_ID,)).fetchall()
    geography = {"POS-MCA":("WARD","ward_id"),"POS-MP":("CONSTITUENCY","constituency_id"),
                 "POS-WOMEN-REP":("COUNTY","county_id"),"POS-SENATOR":("COUNTY","county_id"),
                 "POS-GOVERNOR":("COUNTY","county_id"),"POS-PRESIDENT":("NATIONAL",None)}
    totals: dict[tuple[str,str,str,str],int] = {}
    for r in latest:
        level,key = geography[r["position_id"]]
        gid = "NATIONAL" if key is None else r[key]
        k=(level,gid,r["candidate_id"],r["position_id"])
        totals[k]=totals.get(k,0)+r["votes"]
    for (level,gid,cid,pid), value in totals.items():
        # One published value is deliberately changed to prove R007.
        if level == "CONSTITUENCY" and gid == "CON001" and cid == "POS-MP-C001":
            value += 7
        cur.execute("""
            INSERT INTO published_aggregate_totals
                (election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric,reported_value)
            VALUES(%s,%s,%s,%s,%s,%s,'CANDIDATE_VOTES',%s)
            ON CONFLICT(election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric)
            DO UPDATE SET reported_value=EXCLUDED.reported_value
        """, (ELECTION_ID,source_document_id,level,gid,cid,pid,value))


def check(cur) -> None:
    print("\nETVS SEED VERIFICATION")
    print("="*78)
    for table in ("positions","elections","counties","constituencies","wards","registration_centres",
                  "polling_stations","registered_voter_observations","turnout_observations",
                  "ballot_accounting_observations","candidates","result_submissions",
                  "published_aggregate_totals","audit_runs","audit_findings"):
        try:
            n=cur.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            print(f"{table:36}{n:>6}")
        except psycopg.errors.UndefinedTable:
            print(f"{table:36} MISSING")
    rows=cur.execute("""
        SELECT ps.polling_station_id,rv.registered_voters,t.voters_turnout,
               COUNT(DISTINCT b.position_id) AS contests,
               MIN(b.valid_votes+b.rejected_votes) AS min_accounted,
               MAX(b.valid_votes+b.rejected_votes) AS max_accounted,
               COUNT(DISTINCT rs.position_id) AS result_positions
        FROM polling_stations ps
        LEFT JOIN registered_voter_observations rv ON rv.election_id=ps.election_id AND rv.polling_station_id=ps.polling_station_id AND rv.observation_version=(SELECT MAX(x.observation_version) FROM registered_voter_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id)
        LEFT JOIN turnout_observations t ON t.election_id=ps.election_id AND t.polling_station_id=ps.polling_station_id AND t.observation_version=(SELECT MAX(x.observation_version) FROM turnout_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id)
        LEFT JOIN ballot_accounting_observations b ON b.election_id=ps.election_id AND b.polling_station_id=ps.polling_station_id AND b.observation_version=(SELECT MAX(x.observation_version) FROM ballot_accounting_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id AND x.position_id=b.position_id)
        LEFT JOIN result_submissions rs ON rs.election_id=ps.election_id AND rs.polling_station_id=ps.polling_station_id
        WHERE ps.election_id=%s GROUP BY ps.polling_station_id,rv.registered_voters,t.voters_turnout ORDER BY ps.polling_station_id
    """,(ELECTION_ID,)).fetchall()
    print("\nSTATION COVERAGE")
    for r in rows:
        print(f"{r['polling_station_id']}: registered={r['registered_voters']} turnout={r['voters_turnout']} contests={r['contests']} result_positions={r['result_positions']} accounting_range={r['min_accounted']}..{r['max_accounted']}")


def main()->int:
    parser=argparse.ArgumentParser(description="Seed the ETVS PostgreSQL database.")
    parser.add_argument("--reset",action="store_true")
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    try:
        with psycopg.connect(**db_kwargs()) as conn:
            with conn.cursor() as cur:
                # Existing DBs need the election tables before the additive layer.
                ensure_schema(cur)
                if args.reset: reset_sample(cur)
                seed_positions(cur)
                source_doc,published_doc=seed_sources(cur)
                seed_master_data(cur)
                seed_observations(cur,source_doc)
                seed_results(cur,source_doc)
                seed_published_aggregates(cur,published_doc)
                ensure_reporting_views(cur)
                check(cur)
            conn.commit()
        print("\nSEED SUCCESS: PostgreSQL data committed successfully.")
        return 0
    except Exception as exc:
        print(f"\nSEED FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
