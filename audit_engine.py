"""ETVS PostgreSQL audit engine.

Design rules:
    R001  One station turnout cannot exceed registered voters.
    R002  Candidate total for ONE contest cannot exceed station turnout.
    R003  For ONE contest: valid + rejected = turnout; spoilt is tracked separately.
    R004  Candidate total for ONE contest must equal valid votes for that contest.
    R005  Result version changes are reported as warnings, never silently ignored.
    R006  Ward-level published totals match derived station totals.
    R007  Constituency-level published totals match derived station totals.
    R008  County-level published totals match derived station totals.
    R009  National-level published totals match derived station totals.
    R010  Every result submission SHA-256 fingerprint is valid.
    R011  Registered-voter observations precede turnout observations.
    R012  Turnout observation precedes contest ballot accounting.
    R013  Contest ballot accounting precedes candidate result publication.
    R014  Successive turnout observations respect the station-specific reporting interval.

Important: turnout is deliberately NOT duplicated into six independent turnout
figures. Every contest at a polling station references the same final turnout
observation. Contest-specific valid/rejected/spoilt counts are audited separately.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from getpass import getpass

import psycopg
from psycopg.rows import dict_row

DEFAULT_ELECTION_ID = "KE-PRES-2027"
GENESIS_HASH = "0" * 64
PASSED, FAILED, WARNING = "PASSED", "FAILED", "WARNING"


@dataclass(frozen=True)
class AuditScope:
    level: str | None = None
    geography_id: str | None = None
    candidate_id: str | None = None
    position_id: str | None = None


@dataclass(frozen=True)
class Finding:
    rule_code: str
    status: str
    message: str
    actual_value: int | None = None
    comparison_value: int | None = None
    polling_station_id: str | None = None
    candidate_id: str | None = None
    geography_level: str | None = None
    geography_id: str | None = None
    position_id: str | None = None
    actual_label: str = "Actual value"
    comparison_label: str = "Comparison value"


def db_kwargs() -> dict:
    password = os.getenv("ETVS_DB_PASSWORD")
    if password is None:
        password = getpass("PostgreSQL password for user postgres: ")
    return {"host": os.getenv("ETVS_DB_HOST", "localhost"),
            "port": int(os.getenv("ETVS_DB_PORT", "5432")),
            "dbname": os.getenv("ETVS_DB_NAME", "etvs"),
            "user": os.getenv("ETVS_DB_USER", "postgres"),
            "password": password, "row_factory": dict_row}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def digest(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def result_hash(election_id: str, station_id: str, candidate_id: str, version: int, votes: int) -> str:
    return digest("RESULT", election_id, station_id, candidate_id, version, votes)


def ensure_runtime_columns(cur) -> None:
    """Keep old local databases executable while schema.sql/migrations catch up."""
    cur.execute("ALTER TABLE polling_stations ADD COLUMN IF NOT EXISTS turnout_reporting_interval_minutes INTEGER NOT NULL DEFAULT 30")
    cur.execute("ALTER TABLE turnout_observations ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE turnout_observations ADD COLUMN IF NOT EXISTS source_document_id BIGINT")
    cur.execute("ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS source_document_id BIGINT")
    cur.execute("ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE ballot_accounting_observations ADD COLUMN IF NOT EXISTS turnout_observation_id BIGINT")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS source_document_id BIGINT")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE result_submissions ADD COLUMN IF NOT EXISTS submission_hash TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS scope_level TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS scope_id TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS candidate_id TEXT")
    cur.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS candidate_id TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS geography_level TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS geography_id TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS position_id TEXT")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS actual_label TEXT NOT NULL DEFAULT 'Actual value'")
    cur.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS comparison_label TEXT NOT NULL DEFAULT 'Comparison value'")
    cur.execute("""CREATE TABLE IF NOT EXISTS ballot_security_features (
        feature_id TEXT PRIMARY KEY, election_id TEXT NOT NULL REFERENCES elections(election_id),
        feature_code TEXT NOT NULL, feature_name TEXT NOT NULL, feature_type TEXT NOT NULL,
        description TEXT, required BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (election_id, feature_code)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS ballot_security_observations (
        ballot_security_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        election_id TEXT NOT NULL, polling_station_id TEXT NOT NULL,
        position_id TEXT NOT NULL REFERENCES positions(position_id),
        observation_version INTEGER NOT NULL DEFAULT 1,
        ballots_checked INTEGER NOT NULL, security_valid_ballots INTEGER NOT NULL,
        security_rejected_ballots INTEGER NOT NULL, spoilt_ballots INTEGER NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        source_document_id BIGINT, source_reference TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (election_id,polling_station_id,position_id,observation_version),
        CHECK (security_valid_ballots + security_rejected_ballots = ballots_checked)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS ballot_security_feature_checks (
        feature_check_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        ballot_security_observation_id BIGINT NOT NULL REFERENCES ballot_security_observations(ballot_security_observation_id) ON DELETE CASCADE,
        feature_id TEXT NOT NULL REFERENCES ballot_security_features(feature_id),
        ballots_checked INTEGER NOT NULL, passed_count INTEGER NOT NULL, failed_count INTEGER NOT NULL,
        evidence_note TEXT,
        UNIQUE (ballot_security_observation_id,feature_id),
        CHECK (passed_count + failed_count = ballots_checked)
    )""")


def scoped_station_ids(cur, election_id: str, scope: AuditScope) -> set[str]:
    """Resolve the selected audit scope to polling stations.

    PostgreSQL cannot infer the type of a NULL parameter in expressions such as
    ``%s IS NULL``. Explicit TEXT casts keep both the unscoped (NULL) and scoped
    cases valid when psycopg sends a Python None value.
    """
    rows = cur.execute("""
        SELECT ps.polling_station_id
        FROM polling_stations ps
        JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
        JOIN wards w ON w.ward_id=rc.ward_id
        JOIN constituencies c ON c.constituency_id=w.constituency_id
        JOIN counties co ON co.county_id=c.county_id
        WHERE ps.election_id=%s
          AND (%s::TEXT IS NULL OR co.county_id=%s::TEXT)
          AND (%s::TEXT IS NULL OR c.constituency_id=%s::TEXT)
          AND (%s::TEXT IS NULL OR w.ward_id=%s::TEXT)
          AND (%s::TEXT IS NULL OR ps.polling_station_id=%s::TEXT)
    """, (election_id,
          scope.geography_id if scope.level=="COUNTY" else None, scope.geography_id if scope.level=="COUNTY" else None,
          scope.geography_id if scope.level=="CONSTITUENCY" else None, scope.geography_id if scope.level=="CONSTITUENCY" else None,
          scope.geography_id if scope.level=="WARD" else None, scope.geography_id if scope.level=="WARD" else None,
          scope.geography_id if scope.level=="POLLING_STATION" else None, scope.geography_id if scope.level=="POLLING_STATION" else None)).fetchall()
    return {r["polling_station_id"] for r in rows}


def allowed_geographies(cur, election_id: str, station_ids: set[str]) -> set[tuple[str,str]]:
    if not station_ids:
        return set()
    rows=cur.execute("""
        SELECT DISTINCT w.ward_id,c.constituency_id,co.county_id
        FROM polling_stations ps
        JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
        JOIN wards w ON w.ward_id=rc.ward_id
        JOIN constituencies c ON c.constituency_id=w.constituency_id
        JOIN counties co ON co.county_id=c.county_id
        WHERE ps.election_id=%s AND ps.polling_station_id=ANY(%s)
    """,(election_id,list(station_ids))).fetchall()
    out={("NATIONAL","NATIONAL")}
    for r in rows:
        out.update({("WARD",r["ward_id"]),("CONSTITUENCY",r["constituency_id"]),("COUNTY",r["county_id"])})
    return out


def latest_station_contests(cur, election_id: str, station_ids: set[str]) -> list[dict]:
    """Return one row per station and contest, never mixing positions."""
    if not station_ids:
        return []
    return cur.execute("""
        WITH registered AS (
            SELECT DISTINCT ON(election_id,polling_station_id) polling_station_id,registered_voters,observed_at
            FROM registered_voter_observations
            WHERE election_id=%s ORDER BY election_id,polling_station_id,observation_version DESC
        ), turnout AS (
            SELECT DISTINCT ON(election_id,polling_station_id) polling_station_id,turnout_observation_id,
                   voters_turnout,observation_version,observed_at
            FROM turnout_observations WHERE election_id=%s
            ORDER BY election_id,polling_station_id,observation_version DESC
        ), ballot AS (
            SELECT DISTINCT ON(election_id,polling_station_id,position_id)
                   polling_station_id,position_id,ballot_accounting_observation_id,valid_votes,rejected_votes,
                   spoilt_ballots,turnout_observation_id,observation_version,observed_at
            FROM ballot_accounting_observations
            WHERE election_id=%s AND position_id IS NOT NULL
            ORDER BY election_id,polling_station_id,position_id,observation_version DESC
        ), results AS (
            SELECT DISTINCT ON(election_id,polling_station_id,candidate_id)
                   polling_station_id,candidate_id,position_id,votes,result_version,observed_at,submission_hash
            FROM result_submissions WHERE election_id=%s
            ORDER BY election_id,polling_station_id,candidate_id,result_version DESC
        ), totals AS (
            SELECT polling_station_id,position_id,SUM(votes)::INTEGER candidate_votes,
                   COUNT(*)::INTEGER candidate_count
            FROM results GROUP BY polling_station_id,position_id
        )
        SELECT ps.polling_station_id,ps.polling_station_code,
               COALESCE(r.registered_voters,ps.registered_voters) registered_voters,
               r.observed_at registered_at,t.turnout_observation_id,t.voters_turnout,t.observed_at turnout_at,
               b.position_id,b.valid_votes,b.rejected_votes,b.spoilt_ballots,b.turnout_observation_id ballot_turnout_id,
               b.observed_at ballot_at,tot.candidate_votes,tot.candidate_count
        FROM polling_stations ps
        LEFT JOIN registered r ON r.polling_station_id=ps.polling_station_id
        LEFT JOIN turnout t ON t.polling_station_id=ps.polling_station_id
        LEFT JOIN ballot b ON b.polling_station_id=ps.polling_station_id
        LEFT JOIN totals tot ON tot.polling_station_id=b.polling_station_id AND tot.position_id=b.position_id
        WHERE ps.election_id=%s AND ps.polling_station_id=ANY(%s)
        ORDER BY ps.polling_station_id,b.position_id
    """,(election_id,election_id,election_id,election_id,election_id,list(station_ids))).fetchall()


def result_changes(cur,election_id:str,station_ids:set[str],position_id:str|None,candidate_id:str|None)->list[Finding]:
    rows=cur.execute("""
        SELECT polling_station_id,candidate_id,position_id,
               MIN(result_version) first_version,MAX(result_version) latest_version,
               (ARRAY_AGG(votes ORDER BY result_version))[1] first_votes,
               (ARRAY_AGG(votes ORDER BY result_version))[COUNT(*)::INTEGER] latest_votes
        FROM result_submissions WHERE election_id=%s
        GROUP BY polling_station_id,candidate_id,position_id HAVING COUNT(*)>1
        ORDER BY polling_station_id,position_id,candidate_id
    """,(election_id,)).fetchall()
    out=[]
    for r in rows:
        if r["polling_station_id"] not in station_ids: continue
        if position_id and r["position_id"]!=position_id: continue
        if candidate_id and r["candidate_id"]!=candidate_id: continue
        diff=r["latest_votes"]-r["first_votes"]
        out.append(Finding("R005",WARNING,
            f"{r['polling_station_id']} {r['position_id']} {r['candidate_id']}: result changed from {r['first_votes']} (version {r['first_version']}) to {r['latest_votes']} (version {r['latest_version']}); difference {diff:+d}.",
            r["latest_votes"],r["first_votes"],r["polling_station_id"],r["candidate_id"],"POLLING_STATION",r["polling_station_id"],r["position_id"],"Latest Result Votes","First Result Votes"))
    return out


def turnout_interval_findings(cur,election_id:str,station_ids:set[str])->list[Finding]:
    """Enforce each polling station's configured minimum turnout interval."""
    if not station_ids:
        return []
    stations=cur.execute("""
        SELECT polling_station_id,turnout_reporting_interval_minutes
        FROM polling_stations
        WHERE election_id=%s AND polling_station_id=ANY(%s)
        ORDER BY polling_station_id
    """,(election_id,list(station_ids))).fetchall()
    observations=cur.execute("""
        SELECT polling_station_id,observation_version,voters_turnout,observed_at
        FROM turnout_observations
        WHERE election_id=%s AND polling_station_id=ANY(%s)
        ORDER BY polling_station_id,observed_at,observation_version
    """,(election_id,list(station_ids))).fetchall()
    by_station={}
    for row in observations:
        by_station.setdefault(row["polling_station_id"],[]).append(row)
    out=[]
    for st in stations:
        sid=st["polling_station_id"]; interval=st["turnout_reporting_interval_minutes"]
        obs=by_station.get(sid,[])
        if interval is None or interval < 1:
            out.append(Finding("R014",FAILED,
                f"{sid}: turnout reporting interval is missing or invalid ({interval}).",
                interval,1,sid,None,"POLLING_STATION",sid,None,
                "Configured Interval (minutes)","Minimum Allowed (minutes)"))
            continue
        violations=[]
        for previous,current in zip(obs,obs[1:]):
            if previous["observed_at"] is None or current["observed_at"] is None:
                violations.append("missing observation timestamp")
                continue
            elapsed=(current["observed_at"]-previous["observed_at"]).total_seconds()/60
            if elapsed < interval:
                violations.append(f"{previous['observation_version']}→{current['observation_version']} elapsed {elapsed:g} minutes")
        ok=not violations
        out.append(Finding("R014",PASSED if ok else FAILED,
            f"{sid}: successive turnout observations {'respect' if ok else 'violate'} the configured minimum interval of {interval} minutes."
            + ("" if ok else " Violations: "+", ".join(violations)+"."),
            interval,interval,sid,None,"POLLING_STATION",sid,None,
            "Configured Interval (minutes)","Required Minimum Interval (minutes)"))
    return out


def chronology_findings(rows:list[dict],position_id:str|None)->list[Finding]:
    out=[]
    seen=set()
    for r in rows:
        pid=r["position_id"]
        if position_id and pid!=position_id: continue
        key=(r["polling_station_id"],pid)
        if key in seen: continue
        seen.add(key)
        station=r["polling_station_id"]
        reg,turn,ballot=r["registered_at"],r["turnout_at"],r["ballot_at"]
        # R011: registration must exist and precede turnout.
        ok=reg is not None and turn is not None and reg<=turn
        out.append(Finding("R011",PASSED if ok else FAILED,
            f"{station}: registered-voter observation {('precedes' if ok else 'does not precede')} turnout.",
            1 if ok else 0,1,station,None,"POLLING_STATION",station,pid,"Chronology Check","Required Order"))
        # R012: every contest ballot observation must use the same turnout stream and occur after it.
        ok=turn is not None and ballot is not None and turn<=ballot and r["ballot_turnout_id"]==r["turnout_observation_id"]
        out.append(Finding("R012",PASSED if ok else FAILED,
            f"{station} {pid}: ballot accounting {('references and follows' if ok else 'does not correctly reference/follow')} the final station turnout observation.",
            1 if ok else 0,1,station,None,"POLLING_STATION",station,pid,"Chronology Check","Shared Turnout Reference"))
    return out


def station_findings(rows:list[dict],position_id:str|None)->list[Finding]:
    out=[]
    for r in rows:
        pid=r["position_id"]
        if position_id and pid!=position_id: continue
        s=r["polling_station_id"]; reg=r["registered_voters"]; turn=r["voters_turnout"]
        valid,rejected,spoilt=r["valid_votes"],r["rejected_votes"],r["spoilt_ballots"]
        cand=r["candidate_votes"]
        # R001 is station-wide and is emitted once, using the first contest row.
        if pid == "POS-MCA" or position_id:
            ok=turn is not None and reg is not None and turn<=reg
            out.append(Finding("R001",PASSED if ok else FAILED,
                f"{s}: voter turnout is {turn if turn is not None else 'missing'} and registered voters are {reg if reg is not None else 'missing'}." + ("" if ok else f" Difference: {(turn-reg) if turn is not None and reg is not None else 'unknown'}") ,
                turn,reg,s,None,"POLLING_STATION",s,pid,"Voter Turnout","Registered Voters"))
        # R002-R004 are contest-specific. Spoilt ballots never enter the turnout identity.
        ok=turn is not None and cand is not None and cand<=turn
        out.append(Finding("R002",PASSED if ok else FAILED,
            f"{s} {pid}: candidate votes total {cand if cand is not None else 'missing'} versus turnout {turn if turn is not None else 'missing'}.",
            cand,turn,s,None,"POLLING_STATION",s,pid,"Candidate Votes","Voter Turnout"))
        ok=all(x is not None for x in (turn,valid,rejected,spoilt)) and valid+rejected==turn
        if ok:
            msg=f"{s} {pid}: valid {valid} + rejected {rejected} = turnout {turn}; spoilt ballots recorded separately: {spoilt}."
        else:
            accounted=(valid+rejected) if valid is not None and rejected is not None else None
            msg=f"{s} {pid}: valid {valid} + rejected {rejected} = {accounted}; turnout = {turn}; spoilt ballots are excluded from turnout ({spoilt})."
        out.append(Finding("R003",PASSED if ok else FAILED,msg,(valid+rejected) if valid is not None and rejected is not None else None,turn,s,None,"POLLING_STATION",s,pid,"Valid + Rejected","Voter Turnout"))
        ok=cand is not None and valid is not None and cand==valid
        out.append(Finding("R004",PASSED if ok else FAILED,
            f"{s} {pid}: candidate votes total {cand if cand is not None else 'missing'} versus valid votes {valid if valid is not None else 'missing'}.",cand,valid,s,None,"POLLING_STATION",s,pid,"Candidate Votes","Valid Votes"))
        # R013 checks that results exist and are published after ballot accounting.
        result_time=cur_result_time(rows,r)  # populated by helper below
        ok=r["ballot_at"] is not None and result_time is not None and r["ballot_at"]<=result_time
        out.append(Finding("R013",PASSED if ok else FAILED,
            f"{s} {pid}: contest ballot accounting {('precedes' if ok else 'does not precede')} the latest candidate result.",
            1 if ok else 0,1,s,None,"POLLING_STATION",s,pid,"Chronology Check","Required Order"))
    return out


def cur_result_time(rows:list[dict],row:dict):
    """The station query intentionally does not multiply rows by candidates.
    Look up the latest result timestamp in a later batched query when needed."""
    return row.get("latest_result_at")


def add_latest_result_times(cur,election_id:str,rows:list[dict])->None:
    ids={r["polling_station_id"] for r in rows}
    if not ids:return
    data=cur.execute("""
        SELECT polling_station_id,position_id,MAX(observed_at) latest_result_at
        FROM result_submissions WHERE election_id=%s AND polling_station_id=ANY(%s)
        GROUP BY polling_station_id,position_id
    """,(election_id,list(ids))).fetchall()
    lookup={(r["polling_station_id"],r["position_id"]):r["latest_result_at"] for r in data}
    for r in rows:r["latest_result_at"]=lookup.get((r["polling_station_id"],r["position_id"]))


def integrity_findings(cur,election_id:str,station_ids:set[str],position_id:str|None,candidate_id:str|None)->list[Finding]:
    rows=cur.execute("""
        SELECT result_submission_id,polling_station_id,candidate_id,position_id,result_version,votes,submission_hash
        FROM result_submissions WHERE election_id=%s ORDER BY result_submission_id
    """,(election_id,)).fetchall()
    out=[]
    for r in rows:
        if r["polling_station_id"] not in station_ids:continue
        if position_id and r["position_id"]!=position_id:continue
        if candidate_id and r["candidate_id"]!=candidate_id:continue
        expected=result_hash(election_id,r["polling_station_id"],r["candidate_id"],r["result_version"],r["votes"])
        ok=r["submission_hash"]==expected
        out.append(Finding("R010",PASSED if ok else FAILED,
            f"{r['polling_station_id']} {r['position_id']} submission {r['result_submission_id']} hash is {'valid' if ok else 'invalid or missing'}.",
            1 if ok else 0,1,r["polling_station_id"],r["candidate_id"],"POLLING_STATION",r["polling_station_id"],r["position_id"],"Hash Validity","Required"))
    return out


def security_findings(cur,election_id:str,station_ids:set[str],position_id:str|None)->list[Finding]:
    """R015: valid ballots must pass every required security feature."""
    rows=cur.execute("""SELECT DISTINCT ON (b.polling_station_id,b.position_id)
        b.ballot_security_observation_id,b.polling_station_id,b.position_id,
        b.ballots_checked,b.security_valid_ballots,b.security_rejected_ballots,b.spoilt_ballots
        FROM ballot_security_observations b
        WHERE b.election_id=%s AND b.polling_station_id=ANY(%s)
          AND (%s::TEXT IS NULL OR b.position_id=%s::TEXT)
        ORDER BY b.polling_station_id,b.position_id,b.observation_version DESC""",
        (election_id,list(station_ids),position_id,position_id)).fetchall()
    required=cur.execute("""SELECT feature_id,feature_code FROM ballot_security_features
        WHERE election_id=%s AND required=TRUE ORDER BY feature_code""",(election_id,)).fetchall()
    out=[]
    for r in rows:
        checks=cur.execute("""SELECT f.feature_id,c.ballots_checked,c.passed_count,c.failed_count
            FROM ballot_security_feature_checks c
            JOIN ballot_security_features f ON f.feature_id=c.feature_id
            WHERE c.ballot_security_observation_id=%s AND f.required=TRUE""",
            (r["ballot_security_observation_id"],)).fetchall()
        cmap={c["feature_id"]:c for c in checks}
        missing=[f["feature_code"] for f in required if f["feature_id"] not in cmap]
        inconsistent=[]
        for f in required:
            c=cmap.get(f["feature_id"])
            if c and (c["ballots_checked"]!=r["ballots_checked"]
                      or c["passed_count"]!=r["security_valid_ballots"]
                      or c["passed_count"]+c["failed_count"]!=c["ballots_checked"]):
                inconsistent.append(f["feature_code"])
        ballot=cur.execute("""SELECT valid_votes,rejected_votes,spoilt_ballots
            FROM ballot_accounting_observations
            WHERE election_id=%s AND polling_station_id=%s AND position_id=%s
            ORDER BY observation_version DESC LIMIT 1""",
            (election_id,r["polling_station_id"],r["position_id"])).fetchone()
        ok=bool(required) and not missing and not inconsistent and ballot is not None            and r["security_valid_ballots"]==ballot["valid_votes"]            and r["security_rejected_ballots"]==ballot["rejected_votes"]            and r["spoilt_ballots"]==ballot["spoilt_ballots"]            and r["ballots_checked"]==r["security_valid_ballots"]+r["security_rejected_ballots"]
        msg=(f"{r['polling_station_id']} {r['position_id']}: {r['security_valid_ballots']} ballots passed every required security feature; "
             f"{r['security_rejected_ballots']} failed security and are rejected; "
             f"{r['spoilt_ballots']} damaged/spoilt ballots are excluded from votes cast.")
        if missing: msg+=f" Missing feature checks: {', '.join(missing)}."
        if inconsistent: msg+=f" Inconsistent feature checks: {', '.join(inconsistent)}."
        out.append(Finding("R015",PASSED if ok else FAILED,msg,r["security_valid_ballots"],
            ballot["valid_votes"] if ballot else None,r["polling_station_id"],None,"POLLING_STATION",
            r["polling_station_id"],r["position_id"],"Security-Valid Ballots","Valid Votes"))
    return out


def aggregate_findings(cur,election_id:str,scope:AuditScope,station_ids:set[str],allowed:set[tuple[str,str]])->list[Finding]:
    """Compare each contest only at its own geography; turnout is checked at all levels."""
    rows=cur.execute("""
        WITH latest_turnout AS (
            SELECT DISTINCT ON(election_id,polling_station_id) polling_station_id,voters_turnout
            FROM turnout_observations WHERE election_id=%s ORDER BY election_id,polling_station_id,observation_version DESC
        ), latest_results AS (
            SELECT DISTINCT ON(election_id,polling_station_id,candidate_id)
                   polling_station_id,candidate_id,position_id,votes
            FROM result_submissions WHERE election_id=%s
            ORDER BY election_id,polling_station_id,candidate_id,result_version DESC
        ), base AS (
            SELECT ps.polling_station_id,w.ward_id,c.constituency_id,co.county_id,
                   COALESCE(t.voters_turnout,0) turnout,lr.candidate_id,lr.position_id,COALESCE(lr.votes,0) votes
            FROM polling_stations ps
            JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
            JOIN wards w ON w.ward_id=rc.ward_id
            JOIN constituencies c ON c.constituency_id=w.constituency_id
            JOIN counties co ON co.county_id=c.county_id
            LEFT JOIN latest_turnout t ON t.polling_station_id=ps.polling_station_id
            LEFT JOIN latest_results lr ON lr.polling_station_id=ps.polling_station_id
            WHERE ps.election_id=%s AND ps.polling_station_id=ANY(%s)
        ), station_turnout AS (
            SELECT DISTINCT polling_station_id,ward_id,constituency_id,county_id,turnout FROM base
        ), derived AS (
            SELECT 'WARD' level,ward_id geography_id,NULL::text candidate_id,NULL::text position_id,'TURNOUT' metric,SUM(turnout)::int value FROM station_turnout GROUP BY ward_id
            UNION ALL SELECT 'CONSTITUENCY',constituency_id,NULL,NULL,'TURNOUT',SUM(turnout)::int FROM station_turnout GROUP BY constituency_id
            UNION ALL SELECT 'COUNTY',county_id,NULL,NULL,'TURNOUT',SUM(turnout)::int FROM station_turnout GROUP BY county_id
            UNION ALL SELECT 'NATIONAL','NATIONAL',NULL,NULL,'TURNOUT',SUM(turnout)::int FROM station_turnout
            UNION ALL SELECT 'WARD',ward_id,candidate_id,position_id,'CANDIDATE_VOTES',SUM(votes)::int FROM base WHERE position_id='POS-MCA' GROUP BY ward_id,candidate_id,position_id
            UNION ALL SELECT 'CONSTITUENCY',constituency_id,candidate_id,position_id,'CANDIDATE_VOTES',SUM(votes)::int FROM base WHERE position_id='POS-MP' GROUP BY constituency_id,candidate_id,position_id
            UNION ALL SELECT 'COUNTY',county_id,candidate_id,position_id,'CANDIDATE_VOTES',SUM(votes)::int FROM base WHERE position_id IN('POS-WOMEN-REP','POS-SENATOR','POS-GOVERNOR') GROUP BY county_id,candidate_id,position_id
            UNION ALL SELECT 'NATIONAL','NATIONAL',candidate_id,position_id,'CANDIDATE_VOTES',SUM(votes)::int FROM base WHERE position_id='POS-PRESIDENT' GROUP BY candidate_id,position_id
        )
        SELECT p.aggregation_level,p.geography_id,p.candidate_id,p.position_id,p.metric,
               d.value derived_value,p.reported_value
        FROM published_aggregate_totals p LEFT JOIN derived d
          ON d.level=p.aggregation_level AND d.geography_id=p.geography_id
         AND d.candidate_id IS NOT DISTINCT FROM p.candidate_id
         AND d.position_id IS NOT DISTINCT FROM p.position_id AND d.metric=p.metric
        WHERE p.election_id=%s
        ORDER BY p.aggregation_level,p.geography_id,p.metric,p.position_id,p.candidate_id
    """,(election_id,election_id,election_id,list(station_ids),election_id)).fetchall()
    codes={"WARD":"R006","CONSTITUENCY":"R007","COUNTY":"R008","NATIONAL":"R009"}
    out=[]
    for r in rows:
        level,gid,pid=r["aggregation_level"],r["geography_id"],r["position_id"]
        if (level,gid) not in allowed:continue
        if scope.position_id and pid not in (None,scope.position_id):continue
        if scope.candidate_id and r["candidate_id"] not in (None,scope.candidate_id):continue
        derived,published=r["derived_value"],r["reported_value"]
        ok=derived is not None and derived==published
        subject=f"{level.title()} {gid}"
        if pid:subject+=f" {pid}"
        metric=r["metric"].replace("_"," ").title()
        out.append(Finding(codes[level],PASSED if ok else FAILED,
            f"{subject}: derived {metric.lower()} {derived if derived is not None else 'missing'}; published {published}.",
            derived,published,None,r["candidate_id"],level,gid,pid,"Derived Value","Published Value"))
    return out


def write_findings(cur,run_id:int,election_id:str,findings:list[Finding],position_id:str|None)->None:
    """Append findings to the global tamper-evident chain in deterministic order."""
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('ETVS_AUDIT_CHAIN'))")
    previous=cur.execute("SELECT current_hash FROM audit_findings ORDER BY audit_finding_id DESC LIMIT 1").fetchone()
    previous_hash=previous["current_hash"] if previous else GENESIS_HASH
    created=now_utc()
    for index,f in enumerate(findings,1):
        current= digest(previous_hash,run_id,index,election_id,f.polling_station_id,f.candidate_id,f.position_id,
                        f.geography_level,f.geography_id,f.rule_code,f.status,f.actual_label,f.actual_value,
                        f.comparison_label,f.comparison_value,f.message,created.isoformat())
        cur.execute("""
            INSERT INTO audit_findings(audit_run_id,election_id,polling_station_id,candidate_id,geography_level,geography_id,position_id,
                rule_code,status,actual_label,actual_value,comparison_label,comparison_value,message,created_at,previous_hash,current_hash)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING audit_finding_id
        """,(run_id,election_id,f.polling_station_id,f.candidate_id,f.geography_level,f.geography_id,f.position_id,
              f.rule_code,f.status,f.actual_label,f.actual_value,f.comparison_label,f.comparison_value,f.message,created,previous_hash,current))
        fid=cur.fetchone()["audit_finding_id"]
        # Keep the denormalized pass/fail tables useful to the dashboard.
        if f.status in (PASSED,FAILED):
            table="audit_passed_results" if f.status==PASSED else "audit_failed_results"
            cur.execute(f"""
                INSERT INTO {table}(audit_finding_id,audit_run_id,election_id,candidate_id,position_id,geography_level,geography_id,polling_station_id,rule_code,message,actual_label,actual_value,comparison_label,comparison_value)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,(fid,run_id,election_id,f.candidate_id,f.position_id,f.geography_level,f.geography_id,f.polling_station_id,f.rule_code,f.message,f.actual_label,f.actual_value,f.comparison_label,f.comparison_value))
        if f.rule_code in ("R006","R007","R008","R009") and f.geography_level:
            docs=cur.execute("""
                SELECT MAX(document_id) FILTER(WHERE source_id='SRC-PUBLISHED-AGGREGATES') published_id,
                       MAX(document_id) FILTER(WHERE source_id='SRC-ETVS-SAMPLE') derived_id FROM source_documents
            """).fetchone()
            if docs["published_id"]:
                cur.execute("""
                    INSERT INTO source_comparisons(audit_run_id,election_id,published_document_id,derived_source_document_id,
                        aggregation_level,geography_id,candidate_id,position_id,metric,published_value,derived_value,difference,status)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,(run_id,election_id,docs["published_id"],docs["derived_id"],f.geography_level,f.geography_id,f.candidate_id,f.position_id,
                      "TURNOUT" if f.candidate_id is None else "CANDIDATE_VOTES",f.comparison_value,f.actual_value,
                      f.actual_value-f.comparison_value if f.actual_value is not None and f.comparison_value is not None else None,f.status))
        previous_hash=current
    if position_id:
        counts={s:sum(x.status==s for x in findings) for s in (PASSED,FAILED,WARNING)}
        cur.execute("""
            INSERT INTO audit_position_results(audit_run_id,election_id,position_id,passed_count,failed_count,warning_count)
            VALUES(%s,%s,%s,%s,%s,%s)
            ON CONFLICT(audit_run_id,position_id) DO UPDATE SET passed_count=EXCLUDED.passed_count,failed_count=EXCLUDED.failed_count,warning_count=EXCLUDED.warning_count
        """,(run_id,election_id,position_id,counts[PASSED],counts[FAILED],counts[WARNING]))


def verify_chain_cursor(cur)->tuple[bool,int|None]:
    rows=cur.execute("""
        SELECT audit_finding_id,previous_hash,current_hash,audit_run_id,election_id,polling_station_id,candidate_id,
               geography_level,geography_id,position_id,rule_code,status,actual_label,actual_value,comparison_label,comparison_value,message,created_at
        FROM audit_findings ORDER BY audit_finding_id
    """).fetchall()
    previous=GENESIS_HASH; run=None; index=0
    for r in rows:
        if r["previous_hash"]!=previous:return False,r["audit_finding_id"]
        if r["audit_run_id"]!=run:run=r["audit_run_id"];index=1
        else:index+=1
        expected=digest(previous,r["audit_run_id"],index,r["election_id"],r["polling_station_id"],r["candidate_id"],r["position_id"],
                        r["geography_level"],r["geography_id"],r["rule_code"],r["status"],r["actual_label"],r["actual_value"],
                        r["comparison_label"],r["comparison_value"],r["message"],r["created_at"].isoformat())
        if r["current_hash"]!=expected:return False,r["audit_finding_id"]
        previous=r["current_hash"]
    return True,None


def audit_election(election_id:str,scope:AuditScope)->tuple[int,list[dict],bool,int|None]:
    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:
            ensure_runtime_columns(cur)
            if not cur.execute("SELECT 1 FROM elections WHERE election_id=%s",(election_id,)).fetchone():
                raise ValueError(f"Election {election_id!r} does not exist.")
            stations=scoped_station_ids(cur,election_id,scope)
            if not stations:raise ValueError("The selected audit scope contains no polling stations.")
            geos=allowed_geographies(cur,election_id,stations)
            run=cur.execute("""
                INSERT INTO audit_runs(election_id,scope_level,scope_id,candidate_id,position_id)
                VALUES(%s,%s,%s,%s,%s) RETURNING audit_run_id
            """,(election_id,scope.level,scope.geography_id,scope.candidate_id,scope.position_id)).fetchone()
            run_id=int(run["audit_run_id"])
            rows=latest_station_contests(cur,election_id,stations)
            if not rows:raise ValueError("No contest-specific ballot observations were found.")
            add_latest_result_times(cur,election_id,rows)
            findings=station_findings(rows,scope.position_id)
            findings.extend(security_findings(cur,election_id,stations,scope.position_id))
            findings.extend(turnout_interval_findings(cur,election_id,stations))
            findings.extend(chronology_findings(rows,scope.position_id))
            findings.extend(result_changes(cur,election_id,stations,scope.position_id,scope.candidate_id))
            findings.extend(integrity_findings(cur,election_id,stations,scope.position_id,scope.candidate_id))
            findings.extend(aggregate_findings(cur,election_id,scope,stations,geos))
            write_findings(cur,run_id,election_id,findings,scope.position_id)
            cur.execute("UPDATE audit_runs SET completed_at=%s,status='COMPLETED',findings_count=%s WHERE audit_run_id=%s",(now_utc(),len(findings),run_id))
            conn.commit()
            output=cur.execute("""
                SELECT audit_finding_id,polling_station_id,candidate_id,position_id,geography_level,geography_id,rule_code,status,
                       actual_label,actual_value,comparison_label,comparison_value,message
                FROM audit_findings WHERE audit_run_id=%s ORDER BY audit_finding_id
            """,(run_id,)).fetchall()
            valid,bad=verify_chain_cursor(cur)
            return run_id,output,valid,bad


def verify_chain()->tuple[bool,int|None]:
    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:return verify_chain_cursor(cur)


def print_summary(run_id:int,rows:list[dict])->None:
    counts={PASSED:0,FAILED:0,WARNING:0}
    for r in rows:counts[r["status"]]=counts.get(r["status"],0)+1
    print("\n"+"="*82);print(f"ETVS AUDIT RUN {run_id}");print("="*82)
    print(f"Findings | PASSED: {counts[PASSED]} | FAILED: {counts[FAILED]} | WARNING: {counts[WARNING]}")
    groups={}
    for r in rows:
        if r["polling_station_id"]:groups.setdefault(r["polling_station_id"],[]).append(r)
    for station,items in groups.items():
        status=FAILED if any(x["status"]==FAILED for x in items) else WARNING if any(x["status"]==WARNING for x in items) else PASSED
        print(f"\n{station} [{status}]  {len(items)} findings")
        for r in items:
            actual=f"{r['actual_label']}={r['actual_value']}" if r['actual_value'] is not None else f"{r['actual_label']}=N/A"
            comp=f"{r['comparison_label']}={r['comparison_value']}" if r['comparison_value'] is not None else f"{r['comparison_label']}=N/A"
            contest=f" [{r['position_id']}]" if r.get('position_id') else ""
            print(f"  {r['rule_code']} {r['status']:<7}{contest} | {actual} | {comp}")
            print(f"       {r['message']}")
    aggregate=[r for r in rows if not r["polling_station_id"]]
    if aggregate:
        print("\nGEOGRAPHIC / PUBLISHED COMPARISONS")
        for r in aggregate:
            print(f"  {r['rule_code']} {r['status']:<7} {r['geography_level']} {r['geography_id']} {r.get('position_id') or ''} | {r['message']}")


def main()->int:
    p=argparse.ArgumentParser(description="Run the ETVS PostgreSQL audit engine.")
    p.add_argument("election_id",nargs="?",default=DEFAULT_ELECTION_ID)
    p.add_argument("--verify-chain",action="store_true")
    p.add_argument("--county-id");p.add_argument("--constituency-id");p.add_argument("--ward-id");p.add_argument("--polling-station-id")
    p.add_argument("--candidate-id");p.add_argument("--position-id")
    a=p.parse_args()
    try:
        if a.verify_chain:
            ok,bad=verify_chain();print("Audit hash chain:","VALID" if ok else f"INVALID at finding {bad}");return 0 if ok else 1
        selected=[("COUNTY",a.county_id),("CONSTITUENCY",a.constituency_id),("WARD",a.ward_id),("POLLING_STATION",a.polling_station_id)]
        active=[x for x in selected if x[1]]
        if len(active)>1:raise ValueError("Select only one geographic scope at a time.")
        level,gid=active[0] if active else (None,None)
        run,rows,ok,bad=audit_election(a.election_id,AuditScope(level,gid,a.candidate_id,a.position_id))
        print_summary(run,rows);print("\nAudit hash chain:","VALID" if ok else f"INVALID at finding {bad}")
        return 0 if ok else 1
    except Exception as exc:
        print(f"AUDIT FAILED: {exc}");return 1


if __name__=="__main__":raise SystemExit(main())
