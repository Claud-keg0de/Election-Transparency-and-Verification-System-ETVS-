-- ETVS migration 003: ballot security validation
-- Run after migrations 001 and 002 on an existing PostgreSQL database.

CREATE TABLE ballot_security_features (
    feature_id TEXT PRIMARY KEY,
    election_id TEXT NOT NULL,
    feature_code TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    feature_type TEXT NOT NULL,
    description TEXT,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_security_feature_election FOREIGN KEY (election_id)
        REFERENCES elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT unique_security_feature_per_election UNIQUE (election_id, feature_code)
);
CREATE INDEX idx_ballot_security_features_election ON ballot_security_features(election_id);

CREATE TABLE ballot_security_observations (
    ballot_security_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL,
    polling_station_id TEXT NOT NULL,
    position_id TEXT NOT NULL,
    observation_version INTEGER NOT NULL DEFAULT 1,
    ballots_checked INTEGER NOT NULL,
    security_valid_ballots INTEGER NOT NULL,
    security_rejected_ballots INTEGER NOT NULL,
    spoilt_ballots INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_security_observation_station FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_security_observation_position FOREIGN KEY (position_id)
        REFERENCES positions(position_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_security_observation_source FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT security_observation_counts_non_negative CHECK (
        ballots_checked >= 0 AND security_valid_ballots >= 0
        AND security_rejected_ballots >= 0 AND spoilt_ballots >= 0
    ),
    CONSTRAINT security_observation_identity CHECK (
        security_valid_ballots + security_rejected_ballots = ballots_checked
    ),
    CONSTRAINT security_observation_version_positive CHECK (observation_version > 0),
    CONSTRAINT unique_security_observation_version
        UNIQUE (election_id, polling_station_id, position_id, observation_version)
);
CREATE INDEX idx_ballot_security_observations_latest
    ON ballot_security_observations(election_id, polling_station_id, position_id, observation_version DESC);

CREATE TABLE ballot_security_feature_checks (
    feature_check_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ballot_security_observation_id BIGINT NOT NULL,
    feature_id TEXT NOT NULL,
    ballots_checked INTEGER NOT NULL,
    passed_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    evidence_note TEXT,
    CONSTRAINT fk_security_feature_check_observation FOREIGN KEY (ballot_security_observation_id)
        REFERENCES ballot_security_observations(ballot_security_observation_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_security_feature_check_feature FOREIGN KEY (feature_id)
        REFERENCES ballot_security_features(feature_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT security_feature_check_counts_non_negative CHECK (
        ballots_checked >= 0 AND passed_count >= 0 AND failed_count >= 0
    ),
    CONSTRAINT security_feature_check_identity CHECK (passed_count + failed_count = ballots_checked),
    CONSTRAINT unique_security_feature_check UNIQUE (ballot_security_observation_id, feature_id)
);
CREATE INDEX idx_ballot_security_feature_checks_feature ON ballot_security_feature_checks(feature_id);

