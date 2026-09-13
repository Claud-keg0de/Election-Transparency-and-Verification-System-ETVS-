"""Efficient PostgreSQL audit engine for ETVS.

The engine reads election source observations and writes ONLY audit output.
It never changes turnout, ballot-accounting, polling-station, candidate, or
result-submission source values.

Rules implemented:
    R001  Turnout <= registered voters
    R002  Candidate votes <= turnout
    R003  valid + rejected + spoilt == turnout
    R004  Candidate votes == valid votes
    R005  Result version changes are explainable
    R006  Ward published totals match station-derived totals
    R007  Constituency published totals match station-derived totals
    R008  County published totals match station-derived totals
    R009  National published totals match station-derived totals
    R010  Result submission hashes are valid

Every finding is linked to an audit run and protected by a SHA-256 chain.

Usage:
    py audit_engine.py
    py audit_engine.py KE-PRES-2027
    py audit_engine.py KE-PRES-2027 --county-id COUNTY001 --candidate-id CAND001
    py audit_engine.py KE-PRES-2027 --ward-id W001
    py audit_engine.py KE-PRES-2027 --position-id POS-PRESIDENT
    py audit_engine.py --verify-chain

Connection environment variables are the same as seed.py.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from getpass import getpass

import psycopg
from psycopg.rows import dict_row

DEFAULT_ELECTION_ID = "KE-PRES-2027"
GENESIS_HASH = "0" * 64
PASSED = "PASSED"
FAILED = "FAILED"
WARNING = "WARNING"
SCOPE_LEVELS = ("COUNTY", "CONSTITUENCY", "WARD", "POLLING_STATION")


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
    return {
        "host": os.getenv("ETVS_DB_HOST", "localhost"),
        "port": int(os.getenv("ETVS_DB_PORT", "5432")),
        "dbname": os.getenv("ETVS_DB_NAME", "etvs"),
        "user": os.getenv("ETVS_DB_USER", "postgres"),
        "password": password,
        "row_factory": dict_row,
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_record(previous_hash: str, values: list[object]) -> str:
    payload = previous_hash + "|" + "|".join("" if v is None else str(v) for v in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def latest_station_data(cur, election_id: str,
                        candidate_ids: list[str] | None = None):
    """Fetch all latest station observations in one SQL query.

    CTEs prevent row multiplication between turnout, ballot observations and
    candidate results, making the audit substantially cheaper than running a
    SELECT for every individual rule/station.
    """
    return cur.execute(
        """
        WITH latest_turnout AS (
            SELECT DISTINCT ON (election_id, polling_station_id)
                   election_id, polling_station_id,
                   turnout_observation_id, voters_turnout, observation_version
            FROM turnout_observations
            WHERE election_id = %s
            ORDER BY election_id, polling_station_id, observation_version DESC
        ),
        latest_ballot AS (
            SELECT DISTINCT ON (election_id, polling_station_id)
                   election_id, polling_station_id,
                   ballot_accounting_observation_id,
                   valid_votes, rejected_votes, spoilt_ballots,
                   observation_version
            FROM ballot_accounting_observations
            WHERE election_id = %s
            ORDER BY election_id, polling_station_id, observation_version DESC
        ),
        latest_result_versions AS (
            SELECT election_id, polling_station_id, candidate_id,
                   MAX(result_version) AS result_version
            FROM result_submissions
                        WHERE election_id = %s
                            AND (%s::text IS NULL OR candidate_id = ANY(%s::text[]))
            GROUP BY election_id, polling_station_id, candidate_id
        ),
        candidate_totals AS (
            SELECT rs.election_id, rs.polling_station_id,
                   SUM(rs.votes) AS candidate_votes,
                   COUNT(*) AS candidate_count,
                   MIN(rs.result_version) AS min_version,
                   MAX(rs.result_version) AS max_version
            FROM result_submissions rs
            JOIN latest_result_versions lv
              ON lv.election_id = rs.election_id
             AND lv.polling_station_id = rs.polling_station_id
             AND lv.candidate_id = rs.candidate_id
             AND lv.result_version = rs.result_version
            GROUP BY rs.election_id, rs.polling_station_id
        )
        SELECT
            ps.polling_station_id,
            ps.registered_voters,
            t.turnout_observation_id,
            t.voters_turnout,
            t.observation_version AS turnout_version,
            b.ballot_accounting_observation_id,
            b.valid_votes,
            b.rejected_votes,
            b.spoilt_ballots,
            b.observation_version AS ballot_version,
            ct.candidate_votes,
            ct.candidate_count,
            ct.min_version,
            ct.max_version
        FROM polling_stations ps
        LEFT JOIN latest_turnout t
          ON t.election_id = ps.election_id
         AND t.polling_station_id = ps.polling_station_id
        LEFT JOIN latest_ballot b
          ON b.election_id = ps.election_id
         AND b.polling_station_id = ps.polling_station_id
        LEFT JOIN candidate_totals ct
          ON ct.election_id = ps.election_id
         AND ct.polling_station_id = ps.polling_station_id
        WHERE ps.election_id = %s
        ORDER BY ps.polling_station_id
        """,
        (election_id, election_id, election_id,
         candidate_ids if candidate_ids else None, candidate_ids or [], election_id),
    ).fetchall()


def candidate_ids_for_scope(cur, election_id: str, scope: AuditScope) -> list[str] | None:
    if not scope.position_id:
        return [scope.candidate_id] if scope.candidate_id else None
    rows = cur.execute(
        """
        SELECT candidate_id FROM candidates
        WHERE election_id = %s AND position_id = %s
          AND (%s::text IS NULL OR candidate_id = %s::text)
        ORDER BY candidate_id
        """,
        (election_id, scope.position_id, scope.candidate_id, scope.candidate_id),
    ).fetchall()
    return [row["candidate_id"] for row in rows]


def ensure_submissions_validated(cur, election_id: str) -> None:
    """Reject the audit only when source submissions exist and are not valid."""
    pending = cur.execute(
        """
        SELECT s.source_submission_id
        FROM source_submissions s
        LEFT JOIN submission_validation_results v
          ON v.source_submission_id = s.source_submission_id
        WHERE s.election_id = %s
          AND (v.source_submission_id IS NULL OR v.status <> 'VALID')
        LIMIT 1
        """,
        (election_id,),
    ).fetchone()

    if pending:
        raise ValueError(
            f"Source submission {pending['source_submission_id']} is missing or failed validation."
        )


def scoped_station_ids(cur, election_id: str, scope: AuditScope) -> set[str]:
    rows = cur.execute(
        """
        SELECT ps.polling_station_id
        FROM polling_stations ps
        JOIN registration_centres rc ON rc.registration_centre_id = ps.registration_centre_id
        JOIN wards w ON w.ward_id = rc.ward_id
        JOIN constituencies c ON c.constituency_id = w.constituency_id
        JOIN counties co ON co.county_id = c.county_id
        WHERE ps.election_id = %s
          AND (%s IS NULL OR co.county_id = %s)
          AND (%s IS NULL OR c.constituency_id = %s)
          AND (%s IS NULL OR w.ward_id = %s)
          AND (%s IS NULL OR ps.polling_station_id = %s)
        """,
        (election_id,
         scope.geography_id if scope.level == "COUNTY" else None,
         scope.geography_id if scope.level == "COUNTY" else None,
         scope.geography_id if scope.level == "CONSTITUENCY" else None,
         scope.geography_id if scope.level == "CONSTITUENCY" else None,
         scope.geography_id if scope.level == "WARD" else None,
         scope.geography_id if scope.level == "WARD" else None,
         scope.geography_id if scope.level == "POLLING_STATION" else None,
         scope.geography_id if scope.level == "POLLING_STATION" else None),
    ).fetchall()
    return {row["polling_station_id"] for row in rows}


def scoped_geographies(cur, election_id: str, station_ids: set[str]) -> set[tuple[str, str]]:
    if not station_ids:
        return set()
    rows = cur.execute(
        """
        SELECT DISTINCT w.ward_id, c.constituency_id, co.county_id
        FROM polling_stations ps
        JOIN registration_centres rc ON rc.registration_centre_id = ps.registration_centre_id
        JOIN wards w ON w.ward_id = rc.ward_id
        JOIN constituencies c ON c.constituency_id = w.constituency_id
        JOIN counties co ON co.county_id = c.county_id
        WHERE ps.election_id = %s AND ps.polling_station_id = ANY(%s)
        """,
        (election_id, list(station_ids)),
    ).fetchall()
    allowed = {("NATIONAL", "NATIONAL")}
    for row in rows:
        allowed.update({
            ("WARD", row["ward_id"]),
            ("CONSTITUENCY", row["constituency_id"]),
            ("COUNTY", row["county_id"]),
        })
    return allowed


def aggregate_findings(cur, election_id: str, scope: AuditScope,
                       station_ids: set[str],
                       allowed_geographies: set[tuple[str, str]]) -> list[Finding]:
    """Compare published aggregate evidence with independent station sums."""
    rows = cur.execute(
        """
        WITH latest_turnout AS (
            SELECT DISTINCT ON (election_id, polling_station_id)
                   election_id, polling_station_id, voters_turnout
            FROM turnout_observations
            WHERE election_id = %s
            ORDER BY election_id, polling_station_id, observation_version DESC
        ), latest_results AS (
            SELECT rs.* FROM result_submissions rs JOIN (
                SELECT election_id, polling_station_id, candidate_id,
                       MAX(result_version) AS result_version
                FROM result_submissions
                WHERE election_id = %s
                GROUP BY election_id, polling_station_id, candidate_id
            ) x
              ON x.election_id = rs.election_id
             AND x.polling_station_id = rs.polling_station_id
             AND x.candidate_id = rs.candidate_id
             AND x.result_version = rs.result_version
        ), station_values AS (
            SELECT ps.polling_station_id, w.ward_id, c.constituency_id,
                   county.county_id, COALESCE(t.voters_turnout, 0) AS turnout,
                   lr.candidate_id, lr.position_id, COALESCE(lr.votes, 0) AS votes
            FROM polling_stations ps
            JOIN registration_centres rc ON rc.registration_centre_id = ps.registration_centre_id
            JOIN wards w ON w.ward_id = rc.ward_id
            JOIN constituencies c ON c.constituency_id = w.constituency_id
            JOIN counties county ON county.county_id = c.county_id
            LEFT JOIN latest_turnout t ON t.election_id = ps.election_id
             AND t.polling_station_id = ps.polling_station_id
            LEFT JOIN latest_results lr
              ON lr.election_id = ps.election_id
             AND lr.polling_station_id = ps.polling_station_id
                        WHERE ps.election_id = %s
                            AND ps.polling_station_id = ANY(%s)
        ), station_turnout AS (
            SELECT DISTINCT polling_station_id, ward_id, constituency_id,
                            county_id, turnout
            FROM station_values
        ), derived AS (
                 SELECT 'WARD' AS level, ward_id AS geography_id, NULL::TEXT AS candidate_id,
                     NULL::TEXT AS position_id, 'TURNOUT' AS metric, SUM(turnout)::INTEGER AS value
            FROM station_turnout GROUP BY ward_id
            UNION ALL
            SELECT 'WARD', ward_id, candidate_id, position_id, 'CANDIDATE_VOTES', SUM(votes)::INTEGER
            FROM station_values WHERE candidate_id IS NOT NULL GROUP BY ward_id, candidate_id
            UNION ALL
            SELECT 'CONSTITUENCY', constituency_id, NULL, NULL, 'TURNOUT', SUM(turnout)::INTEGER
            FROM station_turnout GROUP BY constituency_id
            UNION ALL
            SELECT 'CONSTITUENCY', constituency_id, candidate_id, position_id, 'CANDIDATE_VOTES', SUM(votes)::INTEGER
            FROM station_values WHERE candidate_id IS NOT NULL GROUP BY constituency_id, candidate_id
            UNION ALL
            SELECT 'COUNTY', county_id, NULL, NULL, 'TURNOUT', SUM(turnout)::INTEGER
            FROM station_turnout GROUP BY county_id
            UNION ALL
            SELECT 'COUNTY', county_id, candidate_id, position_id, 'CANDIDATE_VOTES', SUM(votes)::INTEGER
            FROM station_values WHERE candidate_id IS NOT NULL GROUP BY county_id, candidate_id
            UNION ALL
            SELECT 'NATIONAL', 'NATIONAL', NULL, NULL, 'TURNOUT', SUM(turnout)::INTEGER
            FROM station_turnout
            UNION ALL
            SELECT 'NATIONAL', 'NATIONAL', candidate_id, position_id, 'CANDIDATE_VOTES', SUM(votes)::INTEGER
            FROM station_values WHERE candidate_id IS NOT NULL GROUP BY candidate_id
        )
        SELECT p.aggregation_level, p.geography_id, p.candidate_id, p.position_id, p.metric,
               d.value AS derived_value, p.reported_value
        FROM published_aggregate_totals p
        LEFT JOIN derived d ON d.level = p.aggregation_level
          AND d.geography_id = p.geography_id
          AND d.candidate_id IS NOT DISTINCT FROM p.candidate_id
          AND d.position_id IS NOT DISTINCT FROM p.position_id
          AND d.metric = p.metric
        WHERE p.election_id = %s
        ORDER BY p.aggregation_level, p.geography_id, p.metric, p.candidate_id NULLS FIRST
        """,
        (election_id, election_id, election_id, list(station_ids)),
    ).fetchall()

    findings: list[Finding] = []
    for row in rows:
        observed = row["derived_value"]
        reported = row["reported_value"]
        status = PASSED if observed is not None and observed == reported else FAILED
        rule_code = {
            "WARD": "R006", "CONSTITUENCY": "R007",
            "COUNTY": "R008", "NATIONAL": "R009",
        }[row["aggregation_level"]]
        label = f"{row['aggregation_level'].title()} {row['geography_id']}"
        metric = row["metric"].lower().replace("_", " ")
        if scope.geography_id and (row["aggregation_level"], row["geography_id"]) not in allowed_geographies:
            continue
        if scope.candidate_id and row["candidate_id"] not in (None, scope.candidate_id):
            continue
        if scope.position_id and row["position_id"] not in (None, scope.position_id):
            continue
        findings.append(
            Finding(
                rule_code,
                status,
                f"{label} {metric}: derived {observed}, published {reported}.",
                observed, reported,
                None,
                row["candidate_id"],
                row["aggregation_level"],
                row["geography_id"],
                row["position_id"],
            )
        )
    return findings


def submission_hash(election_id: str, station_id: str, candidate_id: str,
                    version: int, votes: int) -> str:
    payload = "|".join(str(value) for value in
                       ("RESULT", election_id, station_id, candidate_id, version, votes))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def result_change_findings(cur, election_id: str, scope: AuditScope,
                           station_ids: set[str],
                           candidate_ids: list[str] | None) -> list[Finding]:
    rows = cur.execute(
        """
        SELECT polling_station_id, candidate_id,
               MIN(result_version) AS first_version,
               MAX(result_version) AS latest_version,
               (ARRAY_AGG(votes ORDER BY result_version))[1] AS first_votes,
               (ARRAY_AGG(votes ORDER BY result_version))[COUNT(*)::INTEGER] AS latest_votes
        FROM result_submissions
        WHERE election_id = %s
        GROUP BY polling_station_id, candidate_id
        HAVING COUNT(*) > 1
        ORDER BY polling_station_id, candidate_id
        """,
        (election_id,),
    ).fetchall()
    findings = []
    for row in rows:
        if row["polling_station_id"] not in station_ids:
            continue
        if candidate_ids is not None and row["candidate_id"] not in candidate_ids:
            continue
        change = row["latest_votes"] - row["first_votes"]
        findings.append(
            Finding(
                "R005",
                WARNING,
                f"Candidate {row['candidate_id']} changed from {row['first_votes']} "
                f"(version {row['first_version']}) to {row['latest_votes']} "
                f"(version {row['latest_version']}); difference {change:+d}.",
                row["latest_votes"], row["first_votes"], row["polling_station_id"],
                row["candidate_id"], "POLLING_STATION", row["polling_station_id"],
                scope.position_id,
            )
        )
    return findings


def submission_integrity_findings(cur, election_id: str, scope: AuditScope,
                                  station_ids: set[str],
                                  candidate_ids: list[str] | None) -> list[Finding]:
    rows = cur.execute(
        """
        SELECT result_submission_id, polling_station_id, candidate_id,
               result_version, votes, submission_hash
        FROM result_submissions
        WHERE election_id = %s
        ORDER BY result_submission_id
        """,
        (election_id,),
    ).fetchall()
    findings = []
    for row in rows:
        if row["polling_station_id"] not in station_ids:
            continue
        if candidate_ids is not None and row["candidate_id"] not in candidate_ids:
            continue
        expected = submission_hash(
            election_id, row["polling_station_id"], row["candidate_id"],
            row["result_version"], row["votes"],
        )
        valid = row["submission_hash"] == expected
        findings.append(
            Finding(
                "R010",
                PASSED if valid else FAILED,
                f"Submission {row['result_submission_id']} hash is "
                f"{'valid' if valid else 'invalid or missing'}.",
                1 if valid else 0, 1, row["polling_station_id"],
                row["candidate_id"], "POLLING_STATION", row["polling_station_id"],
                scope.position_id,
            )
        )
    return findings


def make_station_findings(row, candidate_id: str | None = None) -> list[Finding]:
    station = row["polling_station_id"]
    registered = row["registered_voters"]
    turnout = row["voters_turnout"]
    valid = row["valid_votes"]
    rejected = row["rejected_votes"]
    spoilt = row["spoilt_ballots"]
    candidate_votes = row["candidate_votes"]

    findings: list[Finding] = []

    # R001: turnout must not exceed the election-specific registered voters.
    if turnout is None:
        findings.append(Finding("R001", FAILED, "No turnout observation is available.", None, registered, station, actual_label="Voter Turnout", comparison_label="Registered Voters"))
    else:
        status = PASSED if turnout <= registered else FAILED
        findings.append(
            Finding(
                "R001", status,
                f"Turnout {turnout} {'is' if status == PASSED else 'exceeds'} registered voters {registered}.",
                turnout, registered, station, actual_label="Voter Turnout", comparison_label="Registered Voters",
            )
        )

    # R002: total votes assigned to candidates cannot exceed turnout.
    if turnout is None or candidate_votes is None:
        findings.append(Finding("R002", FAILED, "Candidate results or turnout are missing.", candidate_votes, turnout, station, actual_label="Candidate Votes", comparison_label="Voter Turnout"))
    else:
        status = PASSED if candidate_votes <= turnout else FAILED
        findings.append(
            Finding(
                "R002", status,
                f"Candidate votes {candidate_votes} {'are' if status == PASSED else 'exceed'} turnout {turnout}.",
                candidate_votes, turnout, station, actual_label="Candidate Votes", comparison_label="Voter Turnout",
            )
        )

    # R003: independent ballot categories must reconcile to turnout.
    if None in (turnout, valid, rejected, spoilt):
        findings.append(Finding("R003", FAILED, "Ballot accounting or turnout is missing.", None, turnout, station, actual_label="Ballots Accounted For", comparison_label="Voter Turnout"))
    else:
        calculated = valid + rejected + spoilt
        status = PASSED if calculated == turnout else FAILED
        findings.append(
            Finding(
                "R003", status,
                f"Ballots accounted for = {calculated}; voter turnout = {turnout}.",
                calculated, turnout, station, actual_label="Ballots Accounted For", comparison_label="Voter Turnout",
            )
        )

    # R004: the complete contest result should reconcile to valid votes.
    # A candidate-scoped audit must not compare one candidate's votes with the
    # station's total valid votes, so R004 is omitted from that narrow scope.
    if candidate_id is None:
        if candidate_votes is None or valid is None:
            findings.append(
                Finding(
                    "R004",
                    FAILED,
                    "Candidate results or valid votes are missing.",
                    candidate_votes,
                    valid,
                    station,
                )
            )
        else:
            status = PASSED if candidate_votes == valid else FAILED
            findings.append(
                Finding(
                    "R004",
                    status,
                    f"Candidate votes = {candidate_votes}; valid votes = {valid}.",
                    candidate_votes,
                    valid,
                    station,
                )
            )

    # R005 is evaluated separately so the finding includes the actual change.
    min_version = row["min_version"]
    max_version = row["max_version"]
    if min_version is None:
        pass
    else:
        # Keep station-level coverage without claiming that multiple versions
        # are themselves proof of an invalid result.
        findings.append(Finding("R005", PASSED, f"Result submissions available through version {max_version}.", max_version, min_version, station, candidate_id, "POLLING_STATION", station, actual_label="Latest Result Version", comparison_label="Earliest Result Version"))

    return findings


def write_findings(cur, run_id: int, election_id: str,
                   findings: list[Finding], position_id: str | None = None) -> None:
    """Append findings to the global SHA-256 chain in deterministic order."""
    # Serialize audit writers so concurrent runs cannot fork the hash chain.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('ETVS_AUDIT_CHAIN'))")

    previous = cur.execute(
        "SELECT current_hash FROM audit_findings ORDER BY audit_finding_id DESC LIMIT 1"
    ).fetchone()
    previous_hash = previous["current_hash"] if previous else GENESIS_HASH

    created_at = now_utc()
    for index, finding in enumerate(findings, start=1):
        # Include stable run/index/rule data in the hash payload. Timestamp is
        # included as an audit event attribute and is captured once per run.
        current_hash = hash_record(
            previous_hash,
            [
                run_id,
                index,
                election_id,
                finding.polling_station_id,
                finding.rule_code,
                finding.status,
                finding.actual_label,
                finding.actual_value,
                finding.comparison_label,
                finding.comparison_value,
                finding.message,
                finding.candidate_id,
                finding.geography_level,
                finding.geography_id,
                finding.position_id,
                created_at.isoformat(),
            ],
        )
        cur.execute(
            """
            INSERT INTO audit_findings
                (audit_run_id, election_id, polling_station_id, candidate_id,
                 geography_level, geography_id, position_id, rule_code,
                 status, actual_label, actual_value, comparison_label, comparison_value, message, created_at,
                 previous_hash, current_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id, election_id, finding.polling_station_id, finding.candidate_id,
                finding.geography_level, finding.geography_id, finding.position_id,
                finding.rule_code,
                finding.status, finding.actual_label, finding.actual_value, finding.comparison_label, finding.comparison_value,
                finding.message, created_at, previous_hash, current_hash,
            ),
        )
        if finding.status in (PASSED, FAILED):
            table = "audit_passed_results" if finding.status == PASSED else "audit_failed_results"
            cur.execute(
                f"""
                INSERT INTO {table}
                    (audit_finding_id, audit_run_id, election_id, candidate_id,
                     position_id, geography_level, geography_id, polling_station_id, rule_code,
                     message, actual_label, actual_value, comparison_label, comparison_value)
                SELECT audit_finding_id, audit_run_id, election_id, candidate_id,
                       position_id, geography_level, geography_id, polling_station_id, rule_code,
                       message, actual_label, actual_value, comparison_label, comparison_value
                FROM audit_findings
                WHERE audit_finding_id = (SELECT MAX(audit_finding_id) FROM audit_findings WHERE audit_run_id = %s)
                """,
                (run_id,),
            )
        if finding.rule_code in ("R006", "R007", "R008", "R009"):
            docs = cur.execute(
                """
                SELECT
                    MAX(document_id) FILTER (WHERE source_id = 'SRC-PUBLISHED-AGGREGATES') AS published_id,
                    MAX(document_id) FILTER (WHERE source_id = 'SRC-ETVS-SAMPLE') AS derived_id
                FROM source_documents
                """
            ).fetchone()
            cur.execute(
                """
                INSERT INTO source_comparisons
                    (audit_run_id, election_id, published_document_id,
                     derived_source_document_id, aggregation_level, geography_id,
                     candidate_id, position_id, metric, published_value, derived_value,
                     difference, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, election_id, docs["published_id"], docs["derived_id"],
                 finding.geography_level, finding.geography_id, finding.candidate_id, finding.position_id,
                 "TURNOUT" if finding.candidate_id is None else "CANDIDATE_VOTES",
                 finding.comparison_value, finding.actual_value,
                 (finding.actual_value - finding.comparison_value)
                 if finding.actual_value is not None and finding.comparison_value is not None else None,
                 finding.status),
            )
        previous_hash = current_hash

    if position_id:
        counts = {status: sum(1 for finding in findings if finding.status == status)
                  for status in (PASSED, FAILED, WARNING)}
        cur.execute(
            """
            INSERT INTO audit_position_results
                (audit_run_id, election_id, position_id,
                 passed_count, failed_count, warning_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (audit_run_id, position_id) DO UPDATE SET
                passed_count = EXCLUDED.passed_count,
                failed_count = EXCLUDED.failed_count,
                warning_count = EXCLUDED.warning_count
            """,
            (run_id, election_id, position_id, counts[PASSED],
             counts[FAILED], counts[WARNING]),
        )


def audit_election(election_id: str, scope: AuditScope) -> tuple[int, list[dict], bool, int | None]:
    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:
            if not cur.execute("SELECT 1 FROM elections WHERE election_id = %s", (election_id,)).fetchone():
                raise ValueError(f"Election {election_id!r} does not exist.")
            ensure_submissions_validated(cur, election_id)

            # The psycopg connection context supplies the transaction.
            # The run is committed atomically after all findings are written.
            station_ids = scoped_station_ids(cur, election_id, scope)
            if not station_ids:
                raise ValueError("The selected audit scope contains no polling stations.")
            allowed_geographies = scoped_geographies(cur, election_id, station_ids)
            run = cur.execute(
                """
                INSERT INTO audit_runs
                    (election_id, scope_level, scope_id, candidate_id, position_id)
                VALUES (%s, %s, %s, %s, %s) RETURNING audit_run_id
                """,
                (election_id, scope.level, scope.geography_id, scope.candidate_id, scope.position_id),
            ).fetchone()
            run_id = int(run["audit_run_id"])
            candidate_ids = candidate_ids_for_scope(cur, election_id, scope)
            if scope.position_id and not candidate_ids:
                raise ValueError(
                    f"No candidates are registered for position {scope.position_id!r}."
                )

            all_findings: list[Finding] = []
            for row in latest_station_data(cur, election_id, candidate_ids):
                if row["polling_station_id"] in station_ids:
                    station_findings = make_station_findings(row, scope.candidate_id)
                    all_findings.extend(
                        replace(f, geography_level="POLLING_STATION",
                            geography_id=row["polling_station_id"],
                            candidate_id=scope.candidate_id,
                            position_id=scope.position_id)
                        for f in station_findings
                    )
            all_findings.extend(result_change_findings(cur, election_id, scope, station_ids, candidate_ids))
            all_findings.extend(submission_integrity_findings(cur, election_id, scope, station_ids, candidate_ids))
            all_findings.extend(aggregate_findings(cur, election_id, scope, station_ids, allowed_geographies))

            write_findings(cur, run_id, election_id, all_findings, scope.position_id)

            completed = now_utc()
            cur.execute(
                """
                UPDATE audit_runs
                SET completed_at = %s,
                    status = 'COMPLETED',
                    findings_count = %s
                WHERE audit_run_id = %s
                """,
                (completed, len(all_findings), run_id),
            )
            conn.commit()

            rows = cur.execute(
                """
                       SELECT audit_finding_id, polling_station_id, candidate_id,
                       position_id, geography_level, geography_id, rule_code,
                       status, actual_label, actual_value, comparison_label, comparison_value, message
                FROM audit_findings
                WHERE audit_run_id = %s
                ORDER BY audit_finding_id
                """,
                (run_id,),
            ).fetchall()
            valid, bad_id = verify_chain_cursor(cur)
            return run_id, rows, valid, bad_id


def verify_chain_cursor(cur) -> tuple[bool, int | None]:
    rows = cur.execute(
        """
        SELECT audit_finding_id, previous_hash, current_hash,
               audit_run_id, election_id, polling_station_id,
                             candidate_id, geography_level, geography_id, position_id,
                             rule_code, status, actual_value, comparison_value,
               message, created_at
        FROM audit_findings
        ORDER BY audit_finding_id
        """
    ).fetchall()

    previous = GENESIS_HASH
    current_run = None
    run_index = 0
    for row in rows:
        if row["previous_hash"] != previous:
            return False, row["audit_finding_id"]

        if row["audit_run_id"] != current_run:
            current_run = row["audit_run_id"]
            run_index = 1
        else:
            run_index += 1

        expected = hash_record(
            previous,
            [
                row["audit_run_id"],
                run_index,
                row["election_id"],
                row["polling_station_id"],
                row["rule_code"],
                row["status"],
                row["actual_label"],
                row["actual_value"],
                row["comparison_label"],
                row["comparison_value"],
                row["message"],
                row["candidate_id"],
                row["geography_level"],
                row["geography_id"],
                row["position_id"],
                row["created_at"].isoformat(),
            ],
        )
        if row["current_hash"] != expected:
            return False, row["audit_finding_id"]
        previous = row["current_hash"]
    return True, None


def verify_chain() -> tuple[bool, int | None]:
    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:
            return verify_chain_cursor(cur)


def print_summary(run_id: int, rows: list[dict]) -> None:
    counts = {PASSED: 0, FAILED: 0, WARNING: 0}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    station_groups: dict[str, list[dict]] = {}
    aggregate_rows: list[dict] = []
    for row in rows:
        if row.get("polling_station_id"):
            station_groups.setdefault(row["polling_station_id"], []).append(row)
        else:
            aggregate_rows.append(row)

    print("\n" + "=" * 78)
    print(f"ETVS AUDIT RUN {run_id}")
    print("=" * 78)
    print(f"Findings | PASSED: {counts.get(PASSED, 0)} | FAILED: {counts.get(FAILED, 0)} | WARNING: {counts.get(WARNING, 0)}")

    print("\nPOLLING STATION AUDIT RESULTS")
    print("-" * 78)
    for station_id, findings in station_groups.items():
        station_status = FAILED if any(f["status"] == FAILED for f in findings) else WARNING if any(f["status"] == WARNING for f in findings) else PASSED
        passed = sum(f["status"] == PASSED for f in findings)
        failed = sum(f["status"] == FAILED for f in findings)
        warnings = sum(f["status"] == WARNING for f in findings)
        print(f"\n{station_id} [{station_status}]  Rules: {len(findings)} | Passed: {passed} | Failed: {failed} | Warnings: {warnings}")
        for row in findings:
            actual = f"{row['actual_label']}: {row['actual_value']}" if row.get('actual_value') is not None else f"{row['actual_label']}: N/A"
            comparison = f"{row['comparison_label']}: {row['comparison_value']}" if row.get('comparison_value') is not None else f"{row['comparison_label']}: N/A"
            print(f"  {row['rule_code']} {row['status']:<7} | {actual} | {comparison}")
            print(f"       {row['message']}")

    if aggregate_rows:
        print("\nAGGREGATE / GEOGRAPHIC FINDINGS")
        print("-" * 78)
        for row in aggregate_rows:
            actual = f"{row['actual_label']}: {row['actual_value']}" if row.get('actual_value') is not None else f"{row['actual_label']}: N/A"
            comparison = f"{row['comparison_label']}: {row['comparison_value']}" if row.get('comparison_value') is not None else f"{row['comparison_label']}: N/A"
            location = row.get("geography_id") or "AGGREGATE"
            print(f"{location:18} {row['rule_code']:4} {row['status']:<7} | {actual} | {comparison}")
            print(f"  {row['message']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ETVS PostgreSQL audit engine.")
    parser.add_argument("election_id", nargs="?", default=DEFAULT_ELECTION_ID)
    parser.add_argument("--verify-chain", action="store_true")
    parser.add_argument("--county-id")
    parser.add_argument("--constituency-id")
    parser.add_argument("--ward-id")
    parser.add_argument("--polling-station-id")
    parser.add_argument("--candidate-id")
    parser.add_argument("--position-id")
    args = parser.parse_args()

    try:
        if args.verify_chain:
            valid, bad_id = verify_chain()
            if valid:
                print("Audit hash chain: VALID")
                return 0
            print(f"Audit hash chain: INVALID at audit finding {bad_id}")
            return 1

        selected = [
            ("COUNTY", args.county_id),
            ("CONSTITUENCY", args.constituency_id),
            ("WARD", args.ward_id),
            ("POLLING_STATION", args.polling_station_id),
        ]
        active = [(level, value) for level, value in selected if value]
        if len(active) > 1:
            raise ValueError("Select only one geographic scope at a time.")
        level, geography_id = active[0] if active else (None, None)
        scope = AuditScope(level, geography_id, args.candidate_id, args.position_id)
        run_id, rows, valid, bad_id = audit_election(args.election_id, scope)
        print_summary(run_id, rows)
        print("-" * 72)
        print("Audit hash chain:", "VALID" if valid else f"INVALID at {bad_id}")
        return 0 if valid else 1
    except Exception as exc:
        print(f"AUDIT FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
