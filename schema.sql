/*
===============================================================================
ETVS - ELECTRONIC TRANSPARENCY & VERIFICATION SYSTEM
HARDENED POSTGRESQL DATABASE SCHEMA
===============================================================================

PURPOSE
-------
This schema creates the PostgreSQL database for the ETVS independent election
verification and auditing system.

CORE DESIGN PRINCIPLES
----------------------

1. Source election observations are stored separately from audit results.

2. The audit engine READS source observations.

3. The audit engine DOES NOT modify source observations.

4. Audit results are stored separately in audit_runs and audit_findings.

5. Audit findings use meaningful actual/comparison labels instead of generic value names.

6. PostgreSQL constraints protect source-data integrity.

7. TIMESTAMPTZ is used for timestamps.

8. Election counts use INTEGER because voters, ballots and votes are whole
   numbers.

9. Real ETVS identifiers use readable TEXT identifiers.

10. Generated database record IDs use PostgreSQL identity columns.

11. Registration centres represent relatively stable registration locations.

12. Polling stations represent election-specific use of registration centres.

13. Registered-voter counts are stored at the election/polling-station level
    so historical election values are preserved.

14. Composite foreign keys enforce consistency between an election and the
    polling station or candidate associated with a record.

15. The audit engine produces findings without changing source evidence.

===============================================================================


DATABASE HIERARCHY
------------------

County
   |
   +-- Constituency
          |
          +-- Ward
                 |
                 +-- Registration Centre
                        |
                        +-- Election-specific Polling Station
                               |
                               +-- Turnout Observation
                               |
                               +-- Ballot Accounting Observation
                               |
                               +-- Result Submission
                                      |
                                      +-- Candidate

Election provides the temporal context for polling stations, candidates,
observations and results.


AUDIT FLOW
----------

Source observations
        |
        v
   Audit Engine
        |
        +--> Rule 1: Turnout <= Registered Voters
        |
        +--> Rule 2: Candidate Votes <= Turnout
        |
        +--> Rule 3: Ballot Accounting
        |
        +--> Rule 4: Aggregate Consistency
        |
        +--> Rule 5: Submission/Version Checks
        |
        v
   Audit Findings
        |
        v
   SHA-256 Hash Chain

===============================================================================
*/


/*
===============================================================================
0. SOURCE PROVENANCE
===============================================================================

Sources identify the organization or publication that supplied election data.
Source documents identify the specific file or record package retrieved from a
source. Observation tables retain source_reference for backwards compatibility,
while source_document_id provides a structured provenance link.
===============================================================================
*/

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,

    source_name TEXT NOT NULL,

    source_type TEXT NOT NULL,

    organization_name TEXT,

    description TEXT,

    source_url TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT sources_type_check
        CHECK (source_type IN ('OFFICIAL', 'MEDIA', 'CIVIL_SOCIETY', 'OTHER'))
);


CREATE TABLE source_documents (
    document_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    source_id TEXT NOT NULL,

    document_name TEXT NOT NULL,

    document_type TEXT NOT NULL,

    document_uri TEXT,

    content_hash TEXT NOT NULL,

    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_source_document_source
        FOREIGN KEY (source_id)
        REFERENCES sources(source_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT source_document_hash_format
        CHECK (content_hash ~ '^[0-9a-f]{64}$'),

    CONSTRAINT unique_source_document
        UNIQUE (source_id, document_name, content_hash)
);


CREATE INDEX idx_source_documents_source
    ON source_documents(source_id);


/*
===============================================================================
1. ELECTIONS
===============================================================================
*/

CREATE TABLE elections (
    election_id TEXT PRIMARY KEY,

    election_name TEXT NOT NULL,

    election_date DATE NOT NULL,

    status TEXT NOT NULL DEFAULT 'ACTIVE',

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT elections_status_check
        CHECK (status IN ('ACTIVE', 'CLOSED', 'ARCHIVED'))
);


/*
===============================================================================
2. COUNTIES
===============================================================================
*/

CREATE TABLE counties (
    county_id TEXT PRIMARY KEY,

    county_name TEXT NOT NULL UNIQUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


/*
===============================================================================
3. CONSTITUENCIES
===============================================================================
*/

CREATE TABLE constituencies (
    constituency_id TEXT PRIMARY KEY,

    constituency_name TEXT NOT NULL,

    county_id TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_constituency_county
        FOREIGN KEY (county_id)
        REFERENCES counties(county_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT unique_constituency_name_per_county
        UNIQUE (county_id, constituency_name)
);


/*
===============================================================================
4. WARDS
===============================================================================
*/

CREATE TABLE wards (
    ward_id TEXT PRIMARY KEY,

    ward_name TEXT NOT NULL,

    constituency_id TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_ward_constituency
        FOREIGN KEY (constituency_id)
        REFERENCES constituencies(constituency_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT unique_ward_name_per_constituency
        UNIQUE (constituency_id, ward_name)
);


/*
===============================================================================
5. REGISTRATION CENTRES
===============================================================================

A registration centre represents the relatively stable administrative or
physical location associated with voter registration.

IMPORTANT
---------

The registration centre does NOT store an election-specific registered-voter
count.

The same registration centre may participate in multiple elections, and its
registered-voter population can change between elections.

Example:

    RC001
    Juja Primary School
    Ward W001

    2022 -> used for polling
    2027 -> used for polling
    2032 -> used for polling

Historical voter counts therefore belong to the election-specific polling
station record.

A registration centre may also contain multiple polling stations during one
election if the electoral configuration requires it.
===============================================================================
*/

CREATE TABLE registration_centres (
    registration_centre_id TEXT PRIMARY KEY,

    registration_centre_name TEXT NOT NULL,

    ward_id TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_registration_centre_ward
        FOREIGN KEY (ward_id)
        REFERENCES wards(ward_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT unique_registration_centre_name_per_ward
        UNIQUE (ward_id, registration_centre_name)
);


/*
===============================================================================
6. POLLING STATIONS
===============================================================================

A polling station represents the election-specific use/assignment of a
registration centre.

RELATIONSHIP
------------

Registration Centre
        |
        +-- Election 2027
        |      |
        |      +-- PS001
        |      +-- PS002
        |
        +-- Election 2032
               |
               +-- PS001

The polling station stores registered_voters because this value belongs to
the specific election configuration.

This preserves historical voter-registration figures.

IMPORTANT
---------

polling_station_id is globally unique within ETVS.

The pair:

    (polling_station_id, election_id)

is also declared UNIQUE so that other tables can enforce election/station
consistency through composite foreign keys.
===============================================================================
*/

CREATE TABLE polling_stations (
    polling_station_id TEXT PRIMARY KEY,

    election_id TEXT NOT NULL,

    registration_centre_id TEXT NOT NULL,

    polling_station_code TEXT NOT NULL,

    registered_voters INTEGER NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_polling_station_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_polling_station_registration_centre
        FOREIGN KEY (registration_centre_id)
        REFERENCES registration_centres(registration_centre_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT polling_station_registered_voters_non_negative
        CHECK (registered_voters >= 0),

    CONSTRAINT unique_polling_station_code_per_election
        UNIQUE (election_id, polling_station_code),

    CONSTRAINT unique_polling_station_election_pair
        UNIQUE (polling_station_id, election_id)
);


/*
===============================================================================
7. CANDIDATES
===============================================================================

Candidates belong to a particular election.

candidate_id identifies the ETVS candidate record.

The pair:

    (candidate_id, election_id)

is declared UNIQUE so result submissions can enforce that the candidate belongs
to the same election as the submitted result.
===============================================================================
*/

CREATE TABLE positions (
    position_id TEXT PRIMARY KEY,

    position_name TEXT NOT NULL UNIQUE,

    election_level TEXT NOT NULL,

    geography_level TEXT NOT NULL,

    CONSTRAINT position_election_level_check
        CHECK (election_level IN ('PRESIDENT', 'GOVERNOR', 'SENATOR',
                                  'WOMEN_REP', 'MP', 'MCA')),

    CONSTRAINT position_geography_level_check
        CHECK (geography_level IN ('NATIONAL', 'COUNTY', 'CONSTITUENCY', 'WARD'))
);

CREATE TABLE candidates (
    candidate_id TEXT PRIMARY KEY,

    election_id TEXT NOT NULL,

    candidate_name TEXT NOT NULL,

    office TEXT NOT NULL,

    position_id TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_candidate_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_candidate_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT unique_candidate_per_election
        UNIQUE (election_id, candidate_name, office),

    CONSTRAINT unique_candidate_election_pair
        UNIQUE (candidate_id, election_id)
);


CREATE TABLE source_submissions (
    source_submission_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    position_id TEXT REFERENCES positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    submission_level TEXT NOT NULL,
    geography_id TEXT NOT NULL,
    candidate_id TEXT,
    payload JSONB NOT NULL,
    submission_hash TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT source_submission_level_check
        CHECK (submission_level IN ('NATIONAL', 'COUNTY', 'CONSTITUENCY', 'WARD', 'POLLING_STATION')),
    CONSTRAINT source_submission_hash_check
        CHECK (submission_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT unique_source_submission
        UNIQUE (election_id, source_document_id, submission_level,
                geography_id, candidate_id, submission_hash)
);


CREATE TABLE submission_validation_results (
    validation_result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_submission_id BIGINT NOT NULL REFERENCES source_submissions(source_submission_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    status TEXT NOT NULL,
    error_message TEXT,
    validated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT submission_validation_status_check CHECK (status IN ('VALID', 'INVALID')),
    CONSTRAINT validation_message_check
        CHECK ((status = 'VALID' AND error_message IS NULL)
            OR (status = 'INVALID' AND error_message IS NOT NULL)),
    UNIQUE (source_submission_id)
);


CREATE TABLE published_aggregate_totals (
    published_aggregate_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL,
    source_document_id BIGINT NOT NULL,
    aggregation_level TEXT NOT NULL,
    geography_id TEXT NOT NULL,
    candidate_id TEXT,

    position_id TEXT,
    metric TEXT NOT NULL,
    reported_value INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_published_aggregate_election
        FOREIGN KEY (election_id) REFERENCES elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_published_aggregate_source_document
        FOREIGN KEY (source_document_id) REFERENCES source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_published_aggregate_candidate
        FOREIGN KEY (candidate_id, election_id)
        REFERENCES candidates(candidate_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_published_aggregate_position
        FOREIGN KEY (position_id) REFERENCES positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT published_aggregate_level_check
        CHECK (aggregation_level IN ('WARD', 'CONSTITUENCY', 'COUNTY', 'NATIONAL')),
    CONSTRAINT published_aggregate_metric_check
        CHECK (metric IN ('TURNOUT', 'CANDIDATE_VOTES')),
    CONSTRAINT published_aggregate_candidate_check
        CHECK ((metric = 'TURNOUT' AND candidate_id IS NULL)
            OR (metric = 'CANDIDATE_VOTES' AND candidate_id IS NOT NULL)),
    CONSTRAINT published_aggregate_value_non_negative CHECK (reported_value >= 0),
    CONSTRAINT unique_published_aggregate
        UNIQUE NULLS NOT DISTINCT (election_id, source_document_id,
                aggregation_level, geography_id, candidate_id, position_id, metric)
);


CREATE INDEX idx_published_aggregate_lookup
    ON published_aggregate_totals(election_id, aggregation_level, geography_id);



/*
===============================================================================
8. BALLOT SECURITY, SPECIFICATION AND STOCK CONTROL
===============================================================================

This layer models ballot-paper security independently from vote results.

IMPORTANT
---------
1. ballot_specifications describe what the authoritative election-specific
   specification requires.
2. ballot_security_features describe individual expected security controls.
3. ballot_stock_batches record controlled ballot stock by serial range.
4. ballot_security_observations record what an auditor/source actually observed.
5. No table links a ballot serial number to a voter.

The audit engine compares specification/stock expectations with observations.
It does not modify source observations.
===============================================================================
*/

CREATE TABLE ballot_specifications (
    ballot_specification_id TEXT PRIMARY KEY,

    election_id TEXT NOT NULL,

    position_id TEXT NOT NULL,

    colour_name TEXT,
    colour_code TEXT,

    paper_description TEXT,
    paper_size TEXT,
    paper_finish TEXT,

    counterfoil_required BOOLEAN NOT NULL DEFAULT TRUE,
    official_mark_required BOOLEAN NOT NULL DEFAULT TRUE,

    source_document_id BIGINT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_ballot_specification_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_specification_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_specification_source
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT unique_ballot_specification
        UNIQUE (election_id, position_id)
);


CREATE TABLE ballot_security_features (
    security_feature_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    ballot_specification_id TEXT NOT NULL,

    feature_type TEXT NOT NULL,

    feature_code TEXT,

    description TEXT NOT NULL,

    verification_method TEXT,

    required BOOLEAN NOT NULL DEFAULT TRUE,

    source_document_id BIGINT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_ballot_security_feature_specification
        FOREIGN KEY (ballot_specification_id)
        REFERENCES ballot_specifications(ballot_specification_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_security_feature_source
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT unique_ballot_security_feature_type
        UNIQUE (ballot_specification_id, feature_type),

    CONSTRAINT ballot_security_feature_type_check
        CHECK (feature_type IN (
            'WATERMARK',
            'UV',
            'ANTI_COPY',
            'GUILLOCHE',
            'MICROTEXT',
            'SERIALIZATION',
            'EMBOSSMENT',
            'PERFORATION',
            'OFFICIAL_MARK',
            'PAPER'
        ))
);


CREATE INDEX idx_ballot_security_features_spec
    ON ballot_security_features(ballot_specification_id);


CREATE TABLE ballot_stock_batches (
    ballot_batch_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    election_id TEXT NOT NULL,

    position_id TEXT NOT NULL,

    ballot_specification_id TEXT NOT NULL,

    polling_station_id TEXT,

    serial_start TEXT NOT NULL,

    serial_end TEXT NOT NULL,

    quantity INTEGER NOT NULL,

    source_document_id BIGINT,

    allocation_status TEXT NOT NULL DEFAULT 'ALLOCATED',

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_ballot_batch_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_batch_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_batch_specification
        FOREIGN KEY (ballot_specification_id)
        REFERENCES ballot_specifications(ballot_specification_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_batch_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_batch_source
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT ballot_batch_quantity_positive
        CHECK (quantity > 0),

    CONSTRAINT ballot_batch_serials_present
        CHECK (length(trim(serial_start)) > 0 AND length(trim(serial_end)) > 0),

    CONSTRAINT unique_ballot_stock_batch
        UNIQUE (election_id, position_id, polling_station_id, serial_start, serial_end),

    CONSTRAINT ballot_batch_status_check
        CHECK (allocation_status IN (
            'ALLOCATED',
            'ISSUED',
            'RETURNED',
            'RECONCILED',
            'CANCELLED'
        ))
);


CREATE INDEX idx_ballot_stock_batches_lookup
    ON ballot_stock_batches(election_id, position_id, polling_station_id);


CREATE TABLE ballot_security_observations (
    ballot_security_observation_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    election_id TEXT NOT NULL,

    polling_station_id TEXT NOT NULL,

    ballot_specification_id TEXT NOT NULL,

    ballot_batch_id BIGINT,

    security_feature_id BIGINT,

    serial_number TEXT,

    observed_status TEXT NOT NULL,

    observed_value TEXT,

    verification_method TEXT,

    source_document_id BIGINT,

    source_reference TEXT,

    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_ballot_security_observation_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_security_observation_station
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_security_observation_specification
        FOREIGN KEY (ballot_specification_id)
        REFERENCES ballot_specifications(ballot_specification_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_security_observation_batch
        FOREIGN KEY (ballot_batch_id)
        REFERENCES ballot_stock_batches(ballot_batch_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_security_observation_feature
        FOREIGN KEY (security_feature_id)
        REFERENCES ballot_security_features(security_feature_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_security_observation_source
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT unique_ballot_security_observation_reference
        UNIQUE (source_reference),

    CONSTRAINT ballot_security_observation_status_check
        CHECK (observed_status IN (
            'PASS',
            'FAIL',
            'NOT_VERIFIED',
            'NOT_PRESENT'
        )),

    CONSTRAINT ballot_security_observation_serial_check
        CHECK (
            security_feature_id IS NULL
            OR serial_number IS NOT NULL
            OR observed_status IN ('NOT_VERIFIED', 'NOT_PRESENT')
        )
);


CREATE INDEX idx_ballot_security_observations_station
    ON ballot_security_observations(election_id, polling_station_id);

CREATE INDEX idx_ballot_security_observations_serial
    ON ballot_security_observations(election_id, ballot_specification_id, serial_number);


/*
===============================================================================
9. TURNOUT OBSERVATIONS
===============================================================================

INDEPENDENT SOURCE OBSERVATION

This table contains independently obtained turnout observations.

The audit engine READS these records.

The audit engine MUST NOT overwrite the source values.

The composite foreign key ensures that the observation's election and polling
station belong together.

Example:

    Election: KE-PRES-2027
    Polling Station: PS001
    Turnout: 800

===============================================================================
*/

CREATE TABLE turnout_observations (
    turnout_observation_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    election_id TEXT NOT NULL,

    polling_station_id TEXT NOT NULL,

    observation_version INTEGER NOT NULL DEFAULT 1,

    voters_turnout INTEGER NOT NULL,

    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    source_document_id BIGINT,

    source_reference TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_turnout_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_turnout_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(
            polling_station_id,
            election_id
        )
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_turnout_source_document
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT turnout_non_negative
        CHECK (voters_turnout >= 0),

    CONSTRAINT turnout_version_positive
        CHECK (observation_version > 0),

    CONSTRAINT unique_turnout_observation_version
        UNIQUE (
            election_id,
            polling_station_id,
            observation_version
        )
);


/*
===============================================================================
9. BALLOT ACCOUNTING OBSERVATIONS
===============================================================================

INDEPENDENT SOURCE OBSERVATION

Stores the independently observed ballot categories.

The audit engine calculates:

    calculated_ballots =
        valid_votes
        + rejected_votes
        + spoilt_ballots

The calculated value is then compared against turnout.

The original source values remain unchanged.

===============================================================================
*/

CREATE TABLE ballot_accounting_observations (
    ballot_accounting_observation_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    election_id TEXT NOT NULL,

    polling_station_id TEXT NOT NULL,

    position_id TEXT,

    observation_version INTEGER NOT NULL DEFAULT 1,

    valid_votes INTEGER NOT NULL,

    rejected_votes INTEGER NOT NULL,

    spoilt_ballots INTEGER NOT NULL,

    turnout_observation_id BIGINT,

    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    source_document_id BIGINT,

    source_reference TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_ballot_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(
            polling_station_id,
            election_id
        )
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_source_document
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_ballot_turnout_observation
        FOREIGN KEY (turnout_observation_id)
        REFERENCES turnout_observations(turnout_observation_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT ballot_position_not_null
        CHECK (position_id IS NOT NULL),

    CONSTRAINT valid_votes_non_negative
        CHECK (valid_votes >= 0),

    CONSTRAINT rejected_votes_non_negative
        CHECK (rejected_votes >= 0),

    CONSTRAINT spoilt_ballots_non_negative
        CHECK (spoilt_ballots >= 0),

    CONSTRAINT ballot_version_positive
        CHECK (observation_version > 0),

    CONSTRAINT unique_ballot_observation_version
        UNIQUE (
            election_id,
            polling_station_id,
            position_id,
            observation_version
        )
);


/*
===============================================================================
10. RESULT SUBMISSIONS
===============================================================================

A result submission records the reported votes for one candidate at one
polling station.

Multiple versions are deliberately permitted.

This allows ETVS to detect changes instead of silently overwriting earlier
submissions.

The composite foreign keys enforce:

    result election
        =
    polling station election

and:

    result election
        =
    candidate election
===============================================================================
*/

CREATE TABLE result_submissions (
    result_submission_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    election_id TEXT NOT NULL,

    polling_station_id TEXT NOT NULL,

    candidate_id TEXT NOT NULL,

    result_version INTEGER NOT NULL DEFAULT 1,

    votes INTEGER NOT NULL,

    position_id TEXT,

    submission_hash TEXT,

    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    source_document_id BIGINT,

    source_reference TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_result_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_result_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(
            polling_station_id,
            election_id
        )
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_result_candidate_election
        FOREIGN KEY (candidate_id, election_id)
        REFERENCES candidates(
            candidate_id,
            election_id
        )
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_result_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_result_source_document
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT result_votes_non_negative
        CHECK (votes >= 0),

    CONSTRAINT result_submission_hash_format
        CHECK (submission_hash IS NULL OR submission_hash ~ '^[0-9a-f]{64}$'),

    CONSTRAINT result_version_positive
        CHECK (result_version > 0),

    CONSTRAINT unique_result_version
        UNIQUE (
            election_id,
            polling_station_id,
            candidate_id,
            result_version
        )
);


/*
===============================================================================
11. AUDIT RUNS
===============================================================================

Each execution of the audit engine creates one audit run.

The run identifies the election being audited.

Example:

    audit_run_id = 1
    election_id  = KE-PRES-2027
    status       = COMPLETED

===============================================================================
*/

CREATE TABLE audit_runs (
    audit_run_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    election_id TEXT NOT NULL,

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    completed_at TIMESTAMPTZ,

    status TEXT NOT NULL DEFAULT 'RUNNING',

    findings_count INTEGER NOT NULL DEFAULT 0,

    scope_level TEXT,

    scope_id TEXT,

    candidate_id TEXT,

    position_id TEXT,

    CONSTRAINT fk_audit_run_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_audit_run_candidate
        FOREIGN KEY (candidate_id, election_id)
        REFERENCES candidates(candidate_id, election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_audit_run_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT audit_scope_level_check
        CHECK (scope_level IS NULL OR scope_level IN (
            'COUNTY', 'CONSTITUENCY', 'WARD', 'POLLING_STATION'
        )),

    CONSTRAINT audit_run_status_check
        CHECK (
            status IN (
                'RUNNING',
                'COMPLETED',
                'FAILED'
            )
        ),

    CONSTRAINT findings_count_non_negative
        CHECK (findings_count >= 0),

    CONSTRAINT completed_run_has_completion_time
        CHECK (
            status = 'RUNNING'
            OR completed_at IS NOT NULL
        )
);


/*
===============================================================================
12. AUDIT FINDINGS
===============================================================================

This table stores AUDIT OUTPUT.

The audit engine writes findings here.

It does NOT modify:

    turnout_observations
    ballot_accounting_observations
    result_submissions

The audit output uses actual_value and comparison_value with meaningful labels.

Examples:
    R001: Voter Turnout compared with Registered Voters.
    R003: Ballots Accounted For compared with Voter Turnout.

For an upper-bound rule:

    actual_value <= comparison_value

For equality or other rules where an upper bound does not apply:

    comparison_value may be NULL.

===============================================================================
*/

CREATE TABLE audit_findings (
    audit_finding_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    audit_run_id BIGINT NOT NULL,

    election_id TEXT NOT NULL,

    polling_station_id TEXT,

    candidate_id TEXT,

    position_id TEXT,

    geography_level TEXT,

    geography_id TEXT,

    rule_code TEXT NOT NULL,

    status TEXT NOT NULL,

    actual_label TEXT NOT NULL DEFAULT 'Actual value',

    actual_value INTEGER,

    comparison_label TEXT NOT NULL DEFAULT 'Comparison value',

    comparison_value INTEGER,

    message TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    previous_hash TEXT,

    current_hash TEXT NOT NULL,

    CONSTRAINT fk_finding_audit_run
        FOREIGN KEY (audit_run_id)
        REFERENCES audit_runs(audit_run_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_finding_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_finding_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(
            polling_station_id,
            election_id
        )
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_finding_candidate_election
        FOREIGN KEY (candidate_id, election_id)
        REFERENCES candidates(candidate_id, election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_finding_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT audit_status_check
        CHECK (
            status IN (
                'PASSED',
                'FAILED',
                'WARNING'
            )
        ),

    CONSTRAINT actual_value_non_negative
        CHECK (
            actual_value IS NULL
            OR actual_value >= 0
        ),

    CONSTRAINT comparison_value_non_negative
        CHECK (
            comparison_value IS NULL
            OR comparison_value >= 0
        ),

    CONSTRAINT current_hash_format
        CHECK (
            current_hash ~ '^[0-9a-f]{64}$'
        ),

    CONSTRAINT previous_hash_format
        CHECK (
            previous_hash IS NULL
            OR previous_hash ~ '^[0-9a-f]{64}$'
        )
);


CREATE TABLE audit_passed_results (
    audit_passed_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_finding_id BIGINT NOT NULL UNIQUE REFERENCES audit_findings(audit_finding_id),
    audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id),
    election_id TEXT NOT NULL REFERENCES elections(election_id),
    candidate_id TEXT,
    position_id TEXT,
    geography_level TEXT,
    geography_id TEXT,
    polling_station_id TEXT,
    rule_code TEXT NOT NULL,
    message TEXT NOT NULL,
    actual_label TEXT NOT NULL DEFAULT 'Actual value',
    actual_value INTEGER,
    comparison_label TEXT NOT NULL DEFAULT 'Comparison value',
    comparison_value INTEGER,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE audit_failed_results (
    audit_failed_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_finding_id BIGINT NOT NULL UNIQUE REFERENCES audit_findings(audit_finding_id),
    audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id),
    election_id TEXT NOT NULL REFERENCES elections(election_id),
    candidate_id TEXT,
    position_id TEXT,
    geography_level TEXT,
    geography_id TEXT,
    polling_station_id TEXT,
    rule_code TEXT NOT NULL,
    message TEXT NOT NULL,
    actual_label TEXT NOT NULL DEFAULT 'Actual value',
    actual_value INTEGER,
    comparison_label TEXT NOT NULL DEFAULT 'Comparison value',
    comparison_value INTEGER,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE source_comparisons (
    source_comparison_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id),
    election_id TEXT NOT NULL REFERENCES elections(election_id),
    published_document_id BIGINT NOT NULL REFERENCES source_documents(document_id),
    derived_source_document_id BIGINT REFERENCES source_documents(document_id),
    aggregation_level TEXT NOT NULL,
    geography_id TEXT NOT NULL,
    candidate_id TEXT,
    position_id TEXT,
    metric TEXT NOT NULL,
    published_value INTEGER,
    derived_value INTEGER,
    difference INTEGER,
    status TEXT NOT NULL,
    compared_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE audit_position_results (
    audit_position_result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id),
    election_id TEXT NOT NULL REFERENCES elections(election_id),
    position_id TEXT NOT NULL REFERENCES positions(position_id),
    passed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (audit_run_id, position_id)
);


CREATE INDEX idx_audit_failed_station ON audit_failed_results(election_id, polling_station_id);
CREATE INDEX idx_audit_failed_geography ON audit_failed_results(election_id, geography_level, geography_id);
CREATE INDEX idx_source_comparisons_run ON source_comparisons(audit_run_id);
CREATE INDEX idx_audit_findings_candidate ON audit_findings(election_id, candidate_id);
CREATE INDEX idx_audit_findings_geography ON audit_findings(election_id, geography_level, geography_id);


/*
===============================================================================
13. INDEXES
===============================================================================

Indexes improve lookup and audit-engine performance.

They do not modify source data.

===============================================================================
*/

CREATE INDEX idx_constituencies_county
    ON constituencies(county_id);


CREATE INDEX idx_wards_constituency
    ON wards(constituency_id);


CREATE INDEX idx_registration_centres_ward
    ON registration_centres(ward_id);


CREATE INDEX idx_polling_stations_election
    ON polling_stations(election_id);


CREATE INDEX idx_polling_stations_registration_centre
    ON polling_stations(registration_centre_id);


CREATE INDEX idx_polling_stations_election_centre
    ON polling_stations(election_id, registration_centre_id);


CREATE INDEX idx_turnout_election_station
    ON turnout_observations(
        election_id,
        polling_station_id
    );


CREATE INDEX idx_turnout_source_document
    ON turnout_observations(source_document_id);


CREATE INDEX idx_ballot_election_station
    ON ballot_accounting_observations(
        election_id,
        polling_station_id
    );


CREATE INDEX idx_ballot_source_document
    ON ballot_accounting_observations(source_document_id);


CREATE INDEX idx_results_election_station
    ON result_submissions(
        election_id,
        polling_station_id
    );


CREATE INDEX idx_results_candidate
    ON result_submissions(candidate_id);


CREATE INDEX idx_results_position
    ON result_submissions(position_id);


CREATE INDEX idx_results_source_document
    ON result_submissions(source_document_id);


CREATE INDEX idx_results_submission_hash
    ON result_submissions(submission_hash);


CREATE INDEX idx_audit_runs_election
    ON audit_runs(election_id);


CREATE INDEX idx_audit_findings_run
    ON audit_findings(audit_run_id);


CREATE INDEX idx_audit_findings_election
    ON audit_findings(election_id);


CREATE INDEX idx_audit_findings_station
    ON audit_findings(
        election_id,
        polling_station_id
    );


/*
===============================================================================
14. FINAL SCHEMA VERIFICATION
===============================================================================

After successfully executing this schema, run:

    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_type = 'BASE TABLE'
    ORDER BY table_name;

Expected tables:

    audit_findings
    audit_failed_results
    audit_passed_results
    audit_position_results
    audit_runs
    ballot_accounting_observations
    candidates
    positions
    constituencies
    counties
    elections
    polling_stations
    registration_centres
    result_submissions
    source_documents
    sources
    source_comparisons
    source_submissions
    submission_validation_results
    published_aggregate_totals
    registered_voter_observations
    turnout_observations
    wards

===============================================================================
*/


/*
===============================================================================
15. FOREIGN KEY VERIFICATION
===============================================================================

Run this after creating the schema:

    SELECT
        tc.table_name,
        kcu.column_name,
        ccu.table_name AS referenced_table,
        ccu.column_name AS referenced_column
    FROM information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
        ON tc.constraint_name = kcu.constraint_name
       AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage AS ccu
        ON ccu.constraint_name = tc.constraint_name
       AND ccu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema = 'public'
    ORDER BY tc.table_name, kcu.column_name;

===============================================================================
*/


/*
===============================================================================
END OF ETVS POSTGRESQL SCHEMA
===============================================================================
*/

