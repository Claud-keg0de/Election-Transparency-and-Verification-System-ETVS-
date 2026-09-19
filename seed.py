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

ELECTION_ID = "KE-PRES-2027"
SOURCE_ID = "SRC-ETVS-SAMPLE"
PUBLISHED_SOURCE_ID = "SRC-PUBLISHED-AGGREGATES"
BALLOT_SPEC_SOURCE_ID = "SRC-IEBC-BALLOT-SPEC"
BALLOT_SPEC_URI = "https://iebc.or.ke/uploads/tenders/5RfdjVjUmJ.pdf"
POSITIONS = (
    ("POS-MCA", "Member of County Assembly", "MCA", "WARD", "WARD-MCA", 1),
    ("POS-MP", "Member of Parliament", "MP", "CONSTITUENCY", "CONST-MP", 2),
    ("POS-WOMEN-REP", "Women Representative", "WOMEN_REP", "COUNTY", "COUNTY-WR", 3),
    ("POS-SENATOR", "Senator", "SENATOR", "COUNTY", "COUNTY-SNT", 4),
    ("POS-GOVERNOR", "Governor", "GOVERNOR", "COUNTY", "COUNTY-GVN", 5),
    ("POS-PRESIDENT", "President", "PRESIDENT", "NATIONAL", "NATIONAL-PRES", 6),
)

# Source-backed ballot-paper fixture. These colours/codes are from an IEBC
# ballot-paper standard and are stored as election-specific specifications.
# The authoritative 2027 specification must replace these values if IEBC
# publishes a different 2027 standard.
BALLOT_SPECS = {
    "POS-PRESIDENT": ("White", None),
    "POS-MP": ("Green", "352 U"),
    "POS-MCA": ("Brown", "481 U"),
    "POS-SENATOR": ("Yellow", "3935 U"),
    "POS-WOMEN-REP": ("Purple", "250 U"),
    "POS-GOVERNOR": ("Sky Blue", "658 U"),
}

BALLOT_FEATURES = (
    ("WATERMARK", "At least one generic watermark visible under normal light.", "NORMAL_LIGHT"),
    ("UV", "UV-sensitive security feature including an IEBC logo/security mark.", "UV_LIGHT"),
    ("ANTI_COPY", "Anti-copy security feature intended to reveal reproduction.", "PHOTOCOPY_OR_SCAN_TEST"),
    ("GUILLOCHE", "Guilloche security pattern.", "VISUAL_INSPECTION"),
    ("MICROTEXT", "Microtext security feature.", "MAGNIFIED_VISUAL_INSPECTION"),
    ("SERIALIZATION", "Controlled ballot serialisation/tapered serialisation.", "SERIAL_RANGE_CHECK"),
    ("EMBOSSMENT", "Embossed security feature where specified.", "TACTILE_INSPECTION"),
    ("OFFICIAL_MARK", "Official Commission mark/stamp applied as required.", "VISUAL_INSPECTION"),
    ("PAPER", "Smooth ballot paper free from specified visible defects.", "VISUAL_INSPECTION"),
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
        ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS position_id TEXT
    """)
    cur.execute("""
        ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS turnout_observation_id BIGINT
    """)
    cur.execute("""
        ALTER TABLE ballot_accounting_observations DROP CONSTRAINT IF EXISTS unique_ballot_observation_version
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ballot_accounting_station_position_version
        ON ballot_accounting_observations(election_id,polling_station_id,position_id,observation_version)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ballot_specifications (
            ballot_specification_id TEXT PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            position_id TEXT NOT NULL REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            colour_name TEXT, colour_code TEXT, paper_description TEXT, paper_size TEXT, paper_finish TEXT,
            counterfoil_required BOOLEAN NOT NULL DEFAULT TRUE, official_mark_required BOOLEAN NOT NULL DEFAULT TRUE,
            source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(election_id,position_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ballot_security_features (
            security_feature_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ballot_specification_id TEXT NOT NULL REFERENCES ballot_specifications(ballot_specification_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            feature_type TEXT NOT NULL, feature_code TEXT, description TEXT NOT NULL, verification_method TEXT,
            required BOOLEAN NOT NULL DEFAULT TRUE,
            source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ballot_specification_id,feature_type)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ballot_stock_batches (
            ballot_batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            position_id TEXT NOT NULL REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            ballot_specification_id TEXT NOT NULL REFERENCES ballot_specifications(ballot_specification_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            polling_station_id TEXT, serial_start TEXT NOT NULL, serial_end TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            allocation_status TEXT NOT NULL DEFAULT 'ALLOCATED', notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(election_id,position_id,polling_station_id,serial_start,serial_end)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ballot_security_observations (
            ballot_security_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            polling_station_id TEXT NOT NULL,
            ballot_specification_id TEXT NOT NULL REFERENCES ballot_specifications(ballot_specification_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            ballot_batch_id BIGINT REFERENCES ballot_stock_batches(ballot_batch_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            security_feature_id BIGINT REFERENCES ballot_security_features(security_feature_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            serial_number TEXT,
            observed_status TEXT NOT NULL CHECK(observed_status IN('PASS','FAIL','NOT_VERIFIED','NOT_PRESENT')),
            observed_value TEXT, verification_method TEXT,
            source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            source_reference TEXT UNIQUE,
            CONSTRAINT fk_security_observation_station_election
                FOREIGN KEY (polling_station_id,election_id)
                REFERENCES polling_stations(polling_station_id,election_id)
                ON UPDATE CASCADE ON DELETE RESTRICT,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ballot_security_features_spec ON ballot_security_features(ballot_specification_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ballot_stock_batches_lookup ON ballot_stock_batches(election_id,position_id,polling_station_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ballot_security_observations_station ON ballot_security_observations(election_id,polling_station_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ballot_security_observations_serial ON ballot_security_observations(election_id,ballot_specification_id,serial_number)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS published_aggregate_totals (
            published_aggregate_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            election_id TEXT NOT NULL REFERENCES elections(election_id), source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id),
            aggregation_level TEXT NOT NULL, geography_id TEXT NOT NULL, candidate_id TEXT, position_id TEXT,
            metric TEXT NOT NULL, reported_value INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE NULLS NOT DISTINCT (election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric)
        )
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


def seed_sources(cur) -> tuple[int,int,int]:
    for sid,name in ((SOURCE_ID,"ETVS controlled sample source"),(PUBLISHED_SOURCE_ID,"Published aggregate comparison source"),(BALLOT_SPEC_SOURCE_ID,"IEBC ballot-paper specification source")):
        cur.execute("""
            INSERT INTO sources(source_id,source_name,source_type,organization_name,description)
            VALUES(%s,%s,'OTHER','ETVS project','Controlled provenance source for the sample dataset.')
            ON CONFLICT(source_id) DO UPDATE SET source_name=EXCLUDED.source_name
        """,(sid,name))
    ids=[]
    for sid,name in ((SOURCE_ID,"ETVS sample election observations"),(PUBLISHED_SOURCE_ID,"Published aggregate results comparison"),(BALLOT_SPEC_SOURCE_ID,"IEBC ballot-paper standard reference")):
        h=digest("SOURCE",ELECTION_ID,sid,name)
        uri = BALLOT_SPEC_URI if sid == BALLOT_SPEC_SOURCE_ID else "seed.py"
        row=cur.execute("""
            INSERT INTO source_documents(source_id,document_name,document_type,document_uri,content_hash)
            VALUES(%s,%s,'SEEDED_DATASET',%s,%s)
            ON CONFLICT(source_id,document_name,content_hash) DO UPDATE SET document_uri=EXCLUDED.document_uri
            RETURNING document_id
        """,(sid,name,uri,h)).fetchone()
        ids.append(int(row["document_id"]))
    return tuple(ids)


def reset_sample(cur) -> None:
    """Reset the controlled sample and its derived audit history.

    The audit hash chain is global. Removing findings from the middle of that
    chain would make later verification fail, so a deterministic sample reset
    clears the complete derived audit history before rebuilding the sample.
    This function is intended for the controlled development/test database.
    """
    # The first six deletes clear the global derived audit chain and have no
    # SQL parameters. All remaining deletes are scoped to the controlled sample.
    global_deletes = (
        "DELETE FROM source_comparisons",
        "DELETE FROM audit_position_results",
        "DELETE FROM audit_passed_results",
        "DELETE FROM audit_failed_results",
        "DELETE FROM audit_findings",
        "DELETE FROM audit_runs",
    )
    for sql in global_deletes:
        try: cur.execute(sql)
        except psycopg.errors.UndefinedTable: pass

    scoped_deletes = (
        "DELETE FROM submission_validation_results WHERE source_submission_id IN (SELECT source_submission_id FROM source_submissions WHERE election_id=%s)",
        "DELETE FROM source_submissions WHERE election_id=%s",
        "DELETE FROM result_submissions WHERE election_id=%s",
        "DELETE FROM published_aggregate_totals WHERE election_id=%s",
        "DELETE FROM ballot_security_observations WHERE election_id=%s",
        "DELETE FROM ballot_stock_batches WHERE election_id=%s",
        "DELETE FROM ballot_security_features WHERE ballot_specification_id IN (SELECT ballot_specification_id FROM ballot_specifications WHERE election_id=%s)",
        "DELETE FROM ballot_specifications WHERE election_id=%s",
        "DELETE FROM ballot_accounting_observations WHERE election_id=%s",
        "DELETE FROM registered_voter_observations WHERE election_id=%s",
        "DELETE FROM turnout_observations WHERE election_id=%s",
        "DELETE FROM polling_stations WHERE election_id=%s",
        "DELETE FROM candidates WHERE election_id=%s",
        "DELETE FROM elections WHERE election_id=%s",
    )
    for sql in scoped_deletes:
        try: cur.execute(sql,(ELECTION_ID,))
        except psycopg.errors.UndefinedTable: pass
    for table,column,values in (("registration_centres","registration_centre_id",["RC001","RC002","RC003","RC004","RC005","RC006"]),("wards","ward_id",["W001","W002","W003","W004"]),("constituencies","constituency_id",["CON001","CON002"]),("counties","county_id",["COUNTY001"])):
        cur.execute(f"DELETE FROM {table} WHERE {column}=ANY(%s)",(values,))
    cur.execute("DELETE FROM source_documents WHERE source_id IN (%s,%s,%s)",(SOURCE_ID,PUBLISHED_SOURCE_ID,BALLOT_SPEC_SOURCE_ID))
    cur.execute("DELETE FROM sources WHERE source_id IN (%s,%s,%s)",(SOURCE_ID,PUBLISHED_SOURCE_ID,BALLOT_SPEC_SOURCE_ID))


def seed_master_data(cur) -> None:
    cur.execute("INSERT INTO elections(election_id,election_name,election_date,status) VALUES(%s,'ETVS Sample Election 2027','2027-08-10','ACTIVE') ON CONFLICT DO NOTHING",(ELECTION_ID,))
    cur.execute("INSERT INTO counties(county_id,county_name) VALUES('COUNTY001','Sample County') ON CONFLICT DO NOTHING")
    for cid,name in (("CON001","Greenfield Constituency"),("CON002","Riverdale Constituency")):
        cur.execute("INSERT INTO constituencies(constituency_id,constituency_name,county_id) VALUES(%s,%s,'COUNTY001') ON CONFLICT DO NOTHING",(cid,name))
    wards=(("W001","Greenfield Central","CON001"),("W002","Greenfield East","CON001"),("W003","Riverdale Central","CON002"),("W004","Riverdale East","CON002"))
    for wid,name,cid in wards:cur.execute("INSERT INTO wards(ward_id,ward_name,constituency_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",(wid,name,cid))
    centres=(("RC001","Greenfield Primary School","W001"),("RC002","Greenfield Community Hall","W002"),("RC003","Greenfield Secondary School","W001"),("RC004","Riverdale Primary School","W003"),("RC005","Riverdale Community Hall","W004"),("RC006","Riverdale Secondary School","W003"))
    for rid,name,wid in centres:cur.execute("INSERT INTO registration_centres(registration_centre_id,registration_centre_name,ward_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",(rid,name,wid))
    for s in STATIONS:
        cur.execute("""
            INSERT INTO polling_stations(polling_station_id,election_id,registration_centre_id,polling_station_code,registered_voters)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(polling_station_id) DO UPDATE SET election_id=EXCLUDED.election_id,
            registration_centre_id=EXCLUDED.registration_centre_id,polling_station_code=EXCLUDED.polling_station_code,registered_voters=EXCLUDED.registered_voters
        """,(s.station_id,ELECTION_ID,s.centre_id,s.code,s.registered))
    for pid,pname,_,_,_,_ in POSITIONS:
        for n,name in ((1,"Amina Njeri"),(2,"Brian Wanyonyi"),(3,"David Mwangi")):
            cid=f"{pid}-C{n:03d}"
            cur.execute("""
                INSERT INTO candidates(candidate_id,election_id,candidate_name,office,position_id)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(candidate_id) DO UPDATE SET candidate_name=EXCLUDED.candidate_name,office=EXCLUDED.office,position_id=EXCLUDED.position_id
            """,(cid,ELECTION_ID,name,pname,pid))


def seed_ballot_security(cur, ballot_source_document_id:int) -> None:
    """Seed one specification per contest plus controlled stock allocations."""
    for pid, pname, office, _, ballot_code, _ in POSITIONS:
        colour, colour_code = BALLOT_SPECS[pid]
        spec_id = f"BS-{ELECTION_ID}-{pid}"
        cur.execute("""
            INSERT INTO ballot_specifications(
                ballot_specification_id,election_id,position_id,colour_name,colour_code,
                paper_description,paper_size,paper_finish,counterfoil_required,
                official_mark_required,source_document_id
            )
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,TRUE,TRUE,%s)
            ON CONFLICT(election_id,position_id) DO UPDATE SET
                colour_name=EXCLUDED.colour_name,colour_code=EXCLUDED.colour_code,
                paper_description=EXCLUDED.paper_description,
                paper_size=EXCLUDED.paper_size,paper_finish=EXCLUDED.paper_finish,
                counterfoil_required=EXCLUDED.counterfoil_required,
                official_mark_required=EXCLUDED.official_mark_required,
                source_document_id=EXCLUDED.source_document_id
        """, (
            spec_id,ELECTION_ID,pid,colour,colour_code,
            "IEBC ballot-paper specification fixture; verify against the applicable election standard.",
            "Election-specific", "Smooth; free from specified visible defects",
            ballot_source_document_id
        ))
        spec_id = cur.execute("""
            SELECT ballot_specification_id FROM ballot_specifications
            WHERE election_id=%s AND position_id=%s
        """,(ELECTION_ID,pid)).fetchone()["ballot_specification_id"]
        for feature_type,description,method in BALLOT_FEATURES:
            cur.execute("""
                INSERT INTO ballot_security_features(
                    ballot_specification_id,feature_type,description,verification_method,
                    required,source_document_id
                )
                VALUES(%s,%s,%s,%s,TRUE,%s)
                ON CONFLICT DO NOTHING
            """,(spec_id,feature_type,description,method,ballot_source_document_id))

        # Six polling stations receive independent serial ranges for each contest.
        for n,s in enumerate(STATIONS,1):
            start = n * 100000
            end = start + s.registered - 1
            cur.execute("""
                INSERT INTO ballot_stock_batches(
                    election_id,position_id,ballot_specification_id,polling_station_id,
                    serial_start,serial_end,quantity,source_document_id,allocation_status,notes
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'ALLOCATED','ETVS controlled serial-range fixture')
                ON CONFLICT DO NOTHING
            """,(
                ELECTION_ID,pid,spec_id,s.station_id,str(start),str(end),
                s.registered,ballot_source_document_id
            ))

        # One PASS observation per required feature at every station, attached to
        # the station's allocated batch. Serial-level observations are only seeded
        # for serialization, avoiding a row for every physical ballot.
        for s in STATIONS:
            batch=cur.execute("""
                SELECT ballot_batch_id FROM ballot_stock_batches
                WHERE election_id=%s AND position_id=%s AND polling_station_id=%s
            """,(ELECTION_ID,pid,s.station_id)).fetchone()
            features=cur.execute("""
                SELECT security_feature_id,feature_type FROM ballot_security_features
                WHERE ballot_specification_id=%s ORDER BY security_feature_id
            """,(spec_id,)).fetchall()
            for feat in features:
                serial = cur.execute("""
                    SELECT serial_start FROM ballot_stock_batches WHERE ballot_batch_id=%s
                """,(batch["ballot_batch_id"],)).fetchone()["serial_start"] if feat["feature_type"]=="SERIALIZATION" else None
                cur.execute("""
                    INSERT INTO ballot_security_observations(
                        election_id,polling_station_id,ballot_specification_id,ballot_batch_id,
                        security_feature_id,serial_number,observed_status,observed_value,
                        verification_method,source_document_id,source_reference
                    )
                    VALUES(%s,%s,%s,%s,%s,%s,'PASS',%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                """,(
                    ELECTION_ID,s.station_id,spec_id,batch["ballot_batch_id"],
                    feat["security_feature_id"],serial,
                    ("Green" if s.station_id=="PS006" and pid=="POS-PRESIDENT" else colour) if feat["feature_type"]=="PAPER" else "Expected security feature present in controlled fixture",
                    "ETVS fixture verification",ballot_source_document_id,
                    f"SEED-BALLOT-SECURITY-{s.station_id}-{pid}-{feat['feature_type']}"
                ))


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
        # Turnout is one voter count for the station, not six separate counts.
        t1=registered_at+timedelta(hours=3);t2=registered_at+timedelta(hours=7)
        initial=max(0,s.turnout-(5 if s.station_id=="PS005" else 0))
        for version,turnout,when in ((1,initial,t1),(2,s.turnout,t2)):
            ref=digest("TURNOUT",ELECTION_ID,s.station_id,version,turnout)
            cur.execute("""
                INSERT INTO turnout_observations(election_id,polling_station_id,observation_version,voters_turnout,source_document_id,source_reference,observed_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(election_id,polling_station_id,observation_version) DO UPDATE SET voters_turnout=EXCLUDED.voters_turnout,
                source_document_id=EXCLUDED.source_document_id,source_reference=EXCLUDED.source_reference,observed_at=EXCLUDED.observed_at
            """,(ELECTION_ID,s.station_id,version,turnout,source_document_id,ref,when))
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
    """Create candidate results separately for all six positions."""
    for s in STATIONS:
        for pid,*_ in POSITIONS:
            valid,_,_=BASE_ACCOUNTING[s.station_id]
            votes=votes_for(valid,VOTE_SPLITS[s.station_id])
            for n,base_votes in enumerate(votes,1):
                cid=f"{pid}-C{n:03d}"
                versions=(1,2) if s.station_id=="PS005" and pid=="POS-PRESIDENT" and n==1 else (1,)
                for version in versions:
                    final=base_votes+5 if version==2 else base_votes
                    # PS006 President deliberately becomes 660 > turnout 650.
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
        if level=="CONSTITUENCY" and gid=="CON001" and cid=="POS-MP-C001": value+=7
        cur.execute("""
            INSERT INTO published_aggregate_totals(election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric,reported_value)
            VALUES(%s,%s,%s,%s,%s,%s,'CANDIDATE_VOTES',%s)
            ON CONFLICT(election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric) DO UPDATE SET reported_value=EXCLUDED.reported_value
        """,(ELECTION_ID,source_document_id,level,gid,cid,pid,value))


def check(cur)->None:
    print("\nETVS SEED VERIFICATION\n"+"="*82)
    tables=("positions","elections","counties","constituencies","wards","registration_centres","polling_stations","registered_voter_observations","turnout_observations","ballot_accounting_observations","ballot_specifications","ballot_security_features","ballot_stock_batches","ballot_security_observations","candidates","result_submissions","published_aggregate_totals","audit_runs","audit_findings")
    for table in tables:
        try: print(f"{table:38}{cur.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n']:>7}")
        except psycopg.errors.UndefinedTable: print(f"{table:38} MISSING")
    rows=cur.execute("""
        SELECT ps.polling_station_id,rv.registered_voters,t.voters_turnout,
               COUNT(DISTINCT b.position_id) contests,MIN(b.valid_votes+b.rejected_votes) min_accounted,MAX(b.valid_votes+b.rejected_votes) max_accounted,
               COUNT(DISTINCT rs.position_id) result_positions
        FROM polling_stations ps
        LEFT JOIN registered_voter_observations rv ON rv.election_id=ps.election_id AND rv.polling_station_id=ps.polling_station_id AND rv.observation_version=(SELECT MAX(x.observation_version) FROM registered_voter_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id)
        LEFT JOIN turnout_observations t ON t.election_id=ps.election_id AND t.polling_station_id=ps.polling_station_id AND t.observation_version=(SELECT MAX(x.observation_version) FROM turnout_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id)
        LEFT JOIN ballot_accounting_observations b ON b.election_id=ps.election_id AND b.polling_station_id=ps.polling_station_id AND b.observation_version=(SELECT MAX(x.observation_version) FROM ballot_accounting_observations x WHERE x.election_id=ps.election_id AND x.polling_station_id=ps.polling_station_id AND x.position_id=b.position_id)
        LEFT JOIN result_submissions rs ON rs.election_id=ps.election_id AND rs.polling_station_id=ps.polling_station_id
        WHERE ps.election_id=%s GROUP BY ps.polling_station_id,rv.registered_voters,t.voters_turnout ORDER BY ps.polling_station_id
    """,(ELECTION_ID,)).fetchall()
    print("\nSTATION COVERAGE")
    for r in rows:print(f"{r['polling_station_id']}: registered={r['registered_voters']} turnout={r['voters_turnout']} contests={r['contests']} result_positions={r['result_positions']} accounting={r['min_accounted']}..{r['max_accounted']}")


def main()->int:
    p=argparse.ArgumentParser(description="Seed the ETVS PostgreSQL database.");p.add_argument("--reset",action="store_true");p.add_argument("--check",action="store_true");a=p.parse_args()
    try:
        with psycopg.connect(**db_kwargs()) as conn:
            with conn.cursor() as cur:
                ensure_schema(cur)
                if a.reset:reset_sample(cur)
                seed_positions(cur);source_doc,published_doc,ballot_doc=seed_sources(cur);seed_master_data(cur);seed_ballot_security(cur,ballot_doc);seed_observations(cur,source_doc);seed_results(cur,source_doc);seed_published_aggregates(cur,published_doc);ensure_reporting_views(cur);check(cur)
            conn.commit()
        print("\nSEED SUCCESS: PostgreSQL data committed successfully.");return 0
    except Exception as exc:print(f"\nSEED FAILED: {exc}");return 1


if __name__=="__main__":raise SystemExit(main())
