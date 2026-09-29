-- ETVS authoritative PostgreSQL schema
-- PostgreSQL 18 compatible.
-- Source observations are immutable evidence; audit outputs are separate.
-- Normal source entry: polling-station details, turnout, contest results,
-- and contest ballot accounting. Geography/positions/candidates/security
-- reference data are controlled data.
--
-- Accounting contract:
--   valid_votes = SUM(latest candidate votes for a contest)
--   voters_turnout = valid_votes + rejected_votes
--   spoilt_ballots are separate and NEVER count as voters cast.
--
-- Cryptographic contract:
--   BLAKE3-256, represented as 64 lowercase hexadecimal characters.

BEGIN;

-- ---------------------------------------------------------------------------
-- Provenance
-- ---------------------------------------------------------------------------

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('OFFICIAL','MEDIA','CIVIL_SOCIETY','OTHER')),
    organization_name TEXT,
    description TEXT,
    source_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE source_documents (
    document_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    document_name TEXT NOT NULL,
    document_type TEXT NOT NULL,
    document_uri TEXT,
    content_hash TEXT NOT NULL,
    hash_algorithm TEXT NOT NULL DEFAULT 'BLAKE3-256',
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT source_documents_hash_algorithm_check CHECK (hash_algorithm='BLAKE3-256'),
    CONSTRAINT source_documents_hash_format CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT unique_source_document UNIQUE(source_id,document_name,content_hash)
);

-- ---------------------------------------------------------------------------
-- Election and six-region project geography
-- ---------------------------------------------------------------------------

CREATE TABLE elections (
    election_id TEXT PRIMARY KEY,
    election_name TEXT NOT NULL,
    election_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','CLOSED','ARCHIVED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE etvs_regions (
    region_id TEXT PRIMARY KEY,
    region_name TEXT NOT NULL UNIQUE,
    classification_type TEXT NOT NULL DEFAULT 'ETVS_OPERATIONAL',
    classification_note TEXT NOT NULL
);

INSERT INTO etvs_regions(region_id,region_name,classification_note) VALUES
('REG-01','Coastal Region','Project-level six-region classification; not a constitutional county hierarchy.'),
('REG-02','South Eastern Region','Project-level six-region classification; not a constitutional county hierarchy.'),
('REG-03','Mt Kenya Region','Project-level six-region classification; not a constitutional county hierarchy.'),
('REG-04','Northern Region','Project-level six-region classification; not a constitutional county hierarchy.'),
('REG-05','North Rift Valley Region','Project-level six-region classification; not a constitutional county hierarchy.'),
('REG-06','Western Region','Project-level six-region classification; not a constitutional county hierarchy.');

CREATE TABLE counties (
    county_id TEXT PRIMARY KEY,
    county_name TEXT NOT NULL UNIQUE,
    region_id TEXT NOT NULL REFERENCES etvs_regions(region_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE constituencies (
    constituency_id TEXT PRIMARY KEY,
    constituency_name TEXT NOT NULL,
    county_id TEXT NOT NULL REFERENCES counties(county_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_constituency_name_per_county UNIQUE(county_id,constituency_name)
);

CREATE TABLE wards (
    ward_id TEXT PRIMARY KEY,
    ward_name TEXT NOT NULL,
    constituency_id TEXT NOT NULL REFERENCES constituencies(constituency_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_ward_name_per_constituency UNIQUE(constituency_id,ward_name)
);

CREATE TABLE registration_centres (
    registration_centre_id TEXT PRIMARY KEY,
    registration_centre_name TEXT NOT NULL,
    ward_id TEXT NOT NULL REFERENCES wards(ward_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_registration_centre_name_per_ward UNIQUE(ward_id,registration_centre_name)
);

CREATE TABLE polling_stations (
    polling_station_id TEXT PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    registration_centre_id TEXT NOT NULL REFERENCES registration_centres(registration_centre_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_code TEXT NOT NULL,
    registered_voters INTEGER NOT NULL CHECK (registered_voters >= 0),
    turnout_reporting_interval_minutes INTEGER NOT NULL DEFAULT 30
        CHECK (turnout_reporting_interval_minutes BETWEEN 1 AND 1440),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_polling_station_code_per_election UNIQUE(election_id,polling_station_code),
    CONSTRAINT unique_polling_station_election_pair UNIQUE(polling_station_id,election_id)
);

-- ---------------------------------------------------------------------------
-- Positions and candidates
-- ---------------------------------------------------------------------------

CREATE TABLE positions (
    position_id TEXT PRIMARY KEY,
    position_name TEXT NOT NULL UNIQUE,
    election_level TEXT NOT NULL CHECK (election_level IN ('PRESIDENT','GOVERNOR','SENATOR','WOMEN_REP','MP','MCA')),
    geography_level TEXT NOT NULL CHECK (geography_level IN ('NATIONAL','COUNTY','CONSTITUENCY','WARD')),
    ballot_code TEXT,
    observation_sequence INTEGER,
    CONSTRAINT positions_observation_sequence_unique UNIQUE(observation_sequence)
);

CREATE TABLE candidates (
    candidate_id TEXT PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    candidate_name TEXT NOT NULL,
    office TEXT NOT NULL,
    position_id TEXT REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    party_affiliation_type TEXT,
    party_id TEXT,
    symbol_type TEXT,
    symbol_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_candidate_per_election UNIQUE(election_id,candidate_name,office),
    CONSTRAINT unique_candidate_election_pair UNIQUE(candidate_id,election_id),
    CONSTRAINT candidate_party_symbol_check CHECK (
        party_affiliation_type IS NULL OR party_affiliation_type IN ('PARTY','INDEPENDENT')
    ),
    CONSTRAINT candidate_symbol_type_check CHECK (
        symbol_type IS NULL OR symbol_type IN ('PARTY','INDEPENDENT')
    ),
    CONSTRAINT candidate_independent_party_check CHECK (
        party_affiliation_type <> 'INDEPENDENT' OR party_id IS NULL
    )
);

-- ---------------------------------------------------------------------------
-- Published/source submission layers
-- ---------------------------------------------------------------------------

CREATE TABLE source_submissions (
    source_submission_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    position_id TEXT REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    submission_level TEXT NOT NULL CHECK (submission_level IN ('NATIONAL','COUNTY','CONSTITUENCY','WARD','POLLING_STATION')),
    geography_id TEXT NOT NULL,
    candidate_id TEXT,
    payload JSONB NOT NULL,
    submission_hash TEXT NOT NULL,
    hash_algorithm TEXT NOT NULL DEFAULT 'BLAKE3-256',
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT source_submissions_hash_algorithm_check CHECK (hash_algorithm='BLAKE3-256'),
    CONSTRAINT source_submissions_hash_format CHECK (submission_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT unique_source_submission UNIQUE(election_id,source_document_id,submission_level,geography_id,candidate_id,submission_hash)
);

CREATE TABLE submission_validation_results (
    validation_result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_submission_id BIGINT NOT NULL UNIQUE REFERENCES source_submissions(source_submission_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('VALID','INVALID')),
    error_message TEXT,
    validated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT validation_message_check CHECK (
        (status='VALID' AND error_message IS NULL) OR
        (status='INVALID' AND error_message IS NOT NULL)
    )
);

CREATE TABLE published_aggregate_totals (
    published_aggregate_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    source_document_id BIGINT NOT NULL REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    aggregation_level TEXT NOT NULL CHECK(aggregation_level IN ('NATIONAL','COUNTY','CONSTITUENCY','WARD','POLLING_STATION')),
    geography_id TEXT NOT NULL,
    candidate_id TEXT,
    position_id TEXT REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    metric TEXT NOT NULL,
    reported_value INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_published_aggregate_candidate
        FOREIGN KEY(candidate_id,election_id) REFERENCES candidates(candidate_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT published_aggregate_metric_check CHECK (
        (metric='CANDIDATE_VOTES' AND candidate_id IS NOT NULL) OR
        (metric<>'CANDIDATE_VOTES')
    ),
    CONSTRAINT unique_published_aggregate
        UNIQUE NULLS NOT DISTINCT(election_id,source_document_id,aggregation_level,geography_id,candidate_id,position_id,metric)
);

-- ---------------------------------------------------------------------------
-- Ballot specifications, stock, serialized ballot/counterfoil evidence
-- ---------------------------------------------------------------------------

CREATE TABLE ballot_specifications (
    ballot_specification_id TEXT PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    position_id TEXT NOT NULL REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    colour_name TEXT,
    colour_code TEXT,
    paper_description TEXT,
    paper_size TEXT,
    paper_finish TEXT,
    counterfoil_required BOOLEAN NOT NULL DEFAULT TRUE,
    official_mark_required BOOLEAN NOT NULL DEFAULT TRUE,
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_ballot_specification UNIQUE(election_id,position_id)
);

CREATE TABLE ballot_security_features (
    security_feature_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ballot_specification_id TEXT NOT NULL REFERENCES ballot_specifications(ballot_specification_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    feature_type TEXT NOT NULL,
    feature_code TEXT,
    description TEXT NOT NULL,
    verification_method TEXT,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_ballot_security_feature UNIQUE(ballot_specification_id,feature_type),
    CONSTRAINT ballot_security_feature_type_check CHECK (
        feature_type IN ('WATERMARK','UV','ANTI_COPY','GUILLOCHE','MICROTEXT',
                         'SERIALIZATION','EMBOSSMENT','PERFORATION','OFFICIAL_MARK','PAPER')
    )
);

CREATE TABLE ballot_stock_batches (
    ballot_batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    position_id TEXT NOT NULL REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    ballot_specification_id TEXT NOT NULL REFERENCES ballot_specifications(ballot_specification_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT,
    serial_start TEXT NOT NULL,
    serial_end TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    allocation_status TEXT NOT NULL DEFAULT 'ALLOCATED'
        CHECK(allocation_status IN ('ALLOCATED','ISSUED','RETURNED','RECONCILED','CANCELLED')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ballot_stock_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT unique_ballot_stock_range
        UNIQUE(election_id,position_id,polling_station_id,serial_start,serial_end),
    CONSTRAINT unique_ballot_batch_context
        UNIQUE(ballot_batch_id,election_id,polling_station_id,position_id)
);

CREATE TABLE ballot_units (
    ballot_unit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    position_id TEXT NOT NULL REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    ballot_batch_id BIGINT NOT NULL,
    ballot_serial_number TEXT NOT NULL,
    counterfoil_serial_number TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ALLOCATED'
        CHECK(status IN ('ALLOCATED','ISSUED','CAST','COUNTED','UNUSED','REJECTED','SPOILT','CANCELLED')),
    issued_at TIMESTAMPTZ,
    cast_at TIMESTAMPTZ,
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ballot_unit_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_ballot_unit_batch_context
        FOREIGN KEY(ballot_batch_id,election_id,polling_station_id,position_id)
        REFERENCES ballot_stock_batches(ballot_batch_id,election_id,polling_station_id,position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ballot_unit_serials_present CHECK (
        length(trim(ballot_serial_number))>0 AND length(trim(counterfoil_serial_number))>0
    ),
    CONSTRAINT ballot_unit_counterfoil_match CHECK(ballot_serial_number=counterfoil_serial_number),
    CONSTRAINT unique_ballot_unit_serial UNIQUE(election_id,position_id,ballot_serial_number),
    CONSTRAINT unique_ballot_unit_counterfoil UNIQUE(election_id,position_id,counterfoil_serial_number)
);

CREATE TABLE ballot_security_observations (
    ballot_security_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    ballot_specification_id TEXT NOT NULL REFERENCES ballot_specifications(ballot_specification_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    ballot_batch_id BIGINT REFERENCES ballot_stock_batches(ballot_batch_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    security_feature_id BIGINT REFERENCES ballot_security_features(security_feature_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    serial_number TEXT,
    observed_status TEXT NOT NULL CHECK(observed_status IN ('PASS','FAIL','NOT_VERIFIED','NOT_PRESENT')),
    observed_value TEXT,
    verification_method TEXT,
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    source_reference TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ballot_security_observation_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_ballot_security_observation_specification
        FOREIGN KEY(ballot_specification_id)
        REFERENCES ballot_specifications(ballot_specification_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_ballot_security_observation_batch
        FOREIGN KEY(ballot_batch_id)
        REFERENCES ballot_stock_batches(ballot_batch_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------------
-- Station turnout and registered-voter evidence
-- ---------------------------------------------------------------------------

CREATE TABLE turnout_observations (
    turnout_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    observation_version INTEGER NOT NULL DEFAULT 1 CHECK(observation_version>0),
    voters_turnout INTEGER NOT NULL CHECK(voters_turnout>=0),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    source_reference TEXT,
    input_hash TEXT,
    hash_algorithm TEXT NOT NULL DEFAULT 'BLAKE3-256',
    CONSTRAINT fk_turnout_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT turnout_input_hash_format CHECK(input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT turnout_hash_algorithm_check CHECK(hash_algorithm='BLAKE3-256'),
    CONSTRAINT unique_turnout_observation_version
        UNIQUE(election_id,polling_station_id,observation_version)
);

CREATE TABLE registered_voter_observations (
    registered_voter_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    observation_version INTEGER NOT NULL DEFAULT 1 CHECK(observation_version>0),
    registered_voters INTEGER NOT NULL CHECK(registered_voters>=0),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_registered_voter_observation_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT unique_registered_voter_observation_version
        UNIQUE(election_id,polling_station_id,observation_version)
);

-- ---------------------------------------------------------------------------
-- Contest accounting and candidate results
-- ---------------------------------------------------------------------------

CREATE TABLE ballot_accounting_observations (
    ballot_accounting_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    position_id TEXT NOT NULL REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    observation_version INTEGER NOT NULL DEFAULT 1 CHECK(observation_version>0),
    valid_votes INTEGER NOT NULL CHECK(valid_votes>=0),
    rejected_votes INTEGER NOT NULL CHECK(rejected_votes>=0),
    spoilt_ballots INTEGER NOT NULL CHECK(spoilt_ballots>=0),
    turnout_observation_id BIGINT REFERENCES turnout_observations(turnout_observation_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    source_reference TEXT,
    input_hash TEXT,
    hash_algorithm TEXT NOT NULL DEFAULT 'BLAKE3-256',
    CONSTRAINT fk_ballot_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ballot_input_hash_format CHECK(input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ballot_hash_algorithm_check CHECK(hash_algorithm='BLAKE3-256'),
    CONSTRAINT unique_ballot_accounting_position_version
        UNIQUE(election_id,polling_station_id,position_id,observation_version)
);

CREATE TABLE result_submissions (
    result_submission_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    result_version INTEGER NOT NULL DEFAULT 1 CHECK(result_version>0),
    votes INTEGER NOT NULL CHECK(votes>=0),
    position_id TEXT REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    submission_hash TEXT,
    hash_algorithm TEXT NOT NULL DEFAULT 'BLAKE3-256',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_result_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_result_candidate_election
        FOREIGN KEY(candidate_id,election_id)
        REFERENCES candidates(candidate_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_result_position
        FOREIGN KEY(position_id) REFERENCES positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT result_submission_hash_algorithm_check CHECK(hash_algorithm='BLAKE3-256'),
    CONSTRAINT result_submission_hash_format CHECK(submission_hash IS NULL OR submission_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT unique_result_version UNIQUE(election_id,polling_station_id,candidate_id,result_version)
);

-- ---------------------------------------------------------------------------
-- Audit output
-- ---------------------------------------------------------------------------

CREATE TABLE audit_runs (
    audit_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'RUNNING' CHECK(status IN ('RUNNING','COMPLETED','FAILED')),
    findings_count INTEGER NOT NULL DEFAULT 0 CHECK(findings_count>=0),
    scope_level TEXT,
    scope_id TEXT,
    candidate_id TEXT,
    position_id TEXT REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_audit_run_candidate
        FOREIGN KEY(candidate_id,election_id)
        REFERENCES candidates(candidate_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT audit_scope_level_check CHECK(scope_level IS NULL OR scope_level IN ('COUNTY','CONSTITUENCY','WARD','POLLING_STATION')),
    CONSTRAINT completed_run_has_completion_time CHECK(status='RUNNING' OR completed_at IS NOT NULL)
);

CREATE TABLE audit_findings (
    audit_finding_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_run_id BIGINT NOT NULL REFERENCES audit_runs(audit_run_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    election_id TEXT NOT NULL REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    polling_station_id TEXT,
    candidate_id TEXT,
    position_id TEXT REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    geography_level TEXT,
    geography_id TEXT,
    rule_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PASSED','FAILED','WARNING')),
    actual_label TEXT NOT NULL DEFAULT 'Actual value',
    actual_value INTEGER,
    comparison_label TEXT NOT NULL DEFAULT 'Comparison value',
    comparison_value INTEGER,
    message TEXT NOT NULL,
    hash_algorithm TEXT NOT NULL DEFAULT 'BLAKE3-256',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    previous_hash TEXT,
    current_hash TEXT NOT NULL,
    CONSTRAINT fk_finding_station_election
        FOREIGN KEY(polling_station_id,election_id)
        REFERENCES polling_stations(polling_station_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_finding_candidate_election
        FOREIGN KEY(candidate_id,election_id)
        REFERENCES candidates(candidate_id,election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT audit_findings_hash_algorithm_check CHECK(hash_algorithm='BLAKE3-256'),
    CONSTRAINT current_hash_format CHECK(current_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT previous_hash_format CHECK(previous_hash IS NULL OR previous_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT actual_value_non_negative CHECK(actual_value IS NULL OR actual_value>=0),
    CONSTRAINT comparison_value_non_negative CHECK(comparison_value IS NULL OR comparison_value>=0)
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
    UNIQUE(audit_run_id,position_id)
);

-- ---------------------------------------------------------------------------
-- Input surface metadata
-- ---------------------------------------------------------------------------

CREATE TABLE etvs_input_scope (
    input_area TEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    description TEXT NOT NULL
);

INSERT INTO etvs_input_scope(input_area,enabled,description) VALUES
('POLLING_STATION_DETAILS',TRUE,'Election-specific polling-station configuration and registered-voter baseline.'),
('TURNOUT_OBSERVATION',TRUE,'One station-wide voters-cast observation at the configured ETVS reporting interval.'),
('RESULT_SUBMISSION',TRUE,'Candidate result values by polling station and contest after voting closes.'),
('BALLOT_ACCOUNTING',TRUE,'Contest-level ballot accounting linked to the station turnout observation after voting closes.'),
('GEOGRAPHY_REFERENCE',FALSE,'Counties, constituencies and wards are controlled reference data.'),
('CANDIDATE_REFERENCE',FALSE,'Candidates and positions are controlled reference data.'),
('BALLOT_SECURITY_REFERENCE',FALSE,'Ballot specifications, stock and security metadata are controlled reference data.'),
('AUDIT_RESULTS',FALSE,'Audit findings are generated by ETVS and are not direct user input.');

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX idx_counties_region ON counties(region_id);
CREATE INDEX idx_constituencies_county ON constituencies(county_id);
CREATE INDEX idx_wards_constituency ON wards(constituency_id);
CREATE INDEX idx_registration_centres_ward ON registration_centres(ward_id);
CREATE INDEX idx_polling_stations_election ON polling_stations(election_id);
CREATE INDEX idx_polling_stations_registration_centre ON polling_stations(registration_centre_id);
CREATE INDEX idx_polling_station_turnout_interval ON polling_stations(election_id,polling_station_id,turnout_reporting_interval_minutes);
CREATE INDEX idx_turnout_election_station ON turnout_observations(election_id,polling_station_id,observed_at);
CREATE INDEX idx_registered_voter_latest ON registered_voter_observations(election_id,polling_station_id,observation_version DESC);
CREATE INDEX idx_ballot_accounting_latest ON ballot_accounting_observations(election_id,polling_station_id,position_id,observation_version DESC);
CREATE INDEX idx_results_election_station ON result_submissions(election_id,polling_station_id);
CREATE INDEX idx_results_candidate ON result_submissions(candidate_id);
CREATE INDEX idx_results_position ON result_submissions(position_id);
CREATE INDEX idx_results_submission_hash ON result_submissions(submission_hash);
CREATE INDEX idx_ballot_security_features_spec ON ballot_security_features(ballot_specification_id);
CREATE INDEX idx_ballot_stock_batches_lookup ON ballot_stock_batches(election_id,position_id,polling_station_id);
CREATE INDEX idx_ballot_units_station_position ON ballot_units(election_id,polling_station_id,position_id);
CREATE INDEX idx_ballot_security_observations_station ON ballot_security_observations(election_id,polling_station_id);
CREATE INDEX idx_ballot_security_observations_serial ON ballot_security_observations(election_id,ballot_specification_id,serial_number);
CREATE INDEX idx_audit_runs_election ON audit_runs(election_id);
CREATE INDEX idx_audit_findings_run ON audit_findings(audit_run_id);
CREATE INDEX idx_audit_findings_election ON audit_findings(election_id);
CREATE INDEX idx_audit_findings_station ON audit_findings(election_id,polling_station_id);
CREATE INDEX idx_audit_findings_candidate ON audit_findings(election_id,candidate_id);
CREATE INDEX idx_source_comparisons_run ON source_comparisons(audit_run_id);

-- Stable reporting views used by the dashboard.
CREATE OR REPLACE VIEW v_audit_station_findings AS
SELECT f.audit_finding_id,f.audit_run_id,f.election_id,f.polling_station_id,
       ps.polling_station_code,f.position_id,f.rule_code,f.status,
       f.actual_label,f.actual_value,f.comparison_label,f.comparison_value,
       f.message,f.created_at
FROM audit_findings f
LEFT JOIN polling_stations ps ON ps.polling_station_id=f.polling_station_id
WHERE f.polling_station_id IS NOT NULL;

CREATE OR REPLACE VIEW v_audit_station_summary AS
SELECT audit_run_id,election_id,polling_station_id,
       COUNT(*)::INTEGER AS rules_checked,
       COUNT(*) FILTER(WHERE status='PASSED')::INTEGER AS passed_count,
       COUNT(*) FILTER(WHERE status='FAILED')::INTEGER AS failed_count,
       COUNT(*) FILTER(WHERE status='WARNING')::INTEGER AS warning_count,
       CASE WHEN COUNT(*) FILTER(WHERE status='FAILED')>0 THEN 'FAILED'
            WHEN COUNT(*) FILTER(WHERE status='WARNING')>0 THEN 'WARNING'
            ELSE 'PASSED' END AS station_status
FROM audit_findings
WHERE polling_station_id IS NOT NULL
GROUP BY audit_run_id,election_id,polling_station_id;

COMMIT;
