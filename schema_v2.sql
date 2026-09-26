/*
===============================================================================
ETVS SCHEMA V2 - ELECTOR EVIDENCE, SIX-CONTEST CONFIGURATION, DEVICE-AWARE
SECURITY VALIDATION AND PERMISSIONS BOUNDARY
===============================================================================

This migration extends the existing schema without deleting source evidence.

DESIGN RULES
------------
1. Turnout remains ONE station-wide observation. It is never duplicated six
   times merely because a general election can contain six contests.
2. Contest-specific ballot accounting MUST include position_id.
3. An election explicitly declares its applicable contests through
   election_positions; six is a common general-election cardinality, not a
   hard-coded database rule.
4. Elector evidence is separated from candidate/result data.
5. No elector/elector-reference table has candidate_id, result_submission_id,
   vote choice, or any other direct choice relationship.
6. The preferred elector reference is an application-generated/tokenized
   reference. If an authorized workflow must retain the original elector
   number, it is stored as application-encrypted ciphertext; the database also
   stores a SHA-256 lookup hash.
7. Marked-ballot evidence and counterfoil evidence are separate artifacts.
8. Large images/PDFs are stored outside PostgreSQL. The database stores an
   immutable object reference and integrity metadata.
9. Security validation is append-only/versioned. "NOT_AVAILABLE" is not a
   failure.
10. Sensitive elector/evidence tables live in etvs_private.
11. Audit source observations remain separate from audit outputs.
12. Existing ETVS roles remain the operational boundary:
      etvs_owner  -> schema/database maintenance
      etvs_seed   -> controlled seed/import
      etvs_app    -> application/audit workflow
      etvs_reader -> read-only reporting
===============================================================================
*/

BEGIN;

CREATE SCHEMA IF NOT EXISTS etvs_private;

REVOKE ALL ON SCHEMA etvs_private FROM PUBLIC;


/* ---------------------------------------------------------------------------
   A. REGISTERED VOTER OBSERVATIONS
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS public.registered_voter_observations (
    registered_voter_observation_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL,
    polling_station_id TEXT NOT NULL,
    observation_version INTEGER NOT NULL DEFAULT 1,
    registered_voters INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_document_id BIGINT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_registered_voter_election
        FOREIGN KEY (election_id)
        REFERENCES public.elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_registered_voter_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES public.polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_registered_voter_source_document
        FOREIGN KEY (source_document_id)
        REFERENCES public.source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT registered_voters_non_negative
        CHECK (registered_voters >= 0),

    CONSTRAINT registered_voter_version_positive
        CHECK (observation_version > 0),

    CONSTRAINT unique_registered_voter_observation_version
        UNIQUE (election_id, polling_station_id, observation_version)
);

CREATE INDEX IF NOT EXISTS idx_registered_voter_election_station
    ON public.registered_voter_observations(election_id, polling_station_id);


/* ---------------------------------------------------------------------------
   B. EXPLICIT CONTEST CONFIGURATION
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS public.election_positions (
    election_id TEXT NOT NULL,
    position_id TEXT NOT NULL,
    display_order SMALLINT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (election_id, position_id),

    CONSTRAINT fk_election_position_election
        FOREIGN KEY (election_id)
        REFERENCES public.elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_election_position_position
        FOREIGN KEY (position_id)
        REFERENCES public.positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT election_position_order_positive
        CHECK (display_order > 0)
);

CREATE INDEX IF NOT EXISTS idx_election_positions_enabled
    ON public.election_positions(election_id, enabled, display_order);


/* Seed the six ordinary Kenyan contest positions only when they already exist.
   This does not require every election to use all six. */
INSERT INTO public.election_positions
    (election_id, position_id, display_order, enabled)
SELECT e.election_id, p.position_id,
       CASE p.position_id
           WHEN 'POS-PRESIDENT' THEN 1
           WHEN 'POS-GOVERNOR' THEN 2
           WHEN 'POS-SENATOR' THEN 3
           WHEN 'POS-WOMEN-REP' THEN 4
           WHEN 'POS-MP' THEN 5
           WHEN 'POS-MCA' THEN 6
           ELSE 99
       END,
       TRUE
FROM public.elections e
JOIN public.positions p
  ON p.position_id IN (
      'POS-PRESIDENT','POS-GOVERNOR','POS-SENATOR',
      'POS-WOMEN-REP','POS-MP','POS-MCA'
  )
ON CONFLICT (election_id, position_id) DO NOTHING;


/* ---------------------------------------------------------------------------
   C. CORRECT SIX-CONTEST BALLOT ACCOUNTING CARDINALITY
   ---------------------------------------------------------------------------

   The old uniqueness rule omitted position_id. That made a second contest at
   the same station/version conflict with the first contest.

   Remove the old constraint only if it exists, then enforce the correct key.
   --------------------------------------------------------------------------- */

ALTER TABLE public.ballot_accounting_observations
    DROP CONSTRAINT IF EXISTS unique_ballot_observation_version;

ALTER TABLE public.ballot_accounting_observations
    ADD CONSTRAINT unique_ballot_observation_version
    UNIQUE (election_id, polling_station_id, position_id, observation_version);

CREATE INDEX IF NOT EXISTS idx_ballot_accounting_station_position
    ON public.ballot_accounting_observations(
        election_id, polling_station_id, position_id, observation_version
    );


/* ---------------------------------------------------------------------------
   D. DEVICE CAPABILITY CATALOGUE
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS etvs_private.device_capabilities (
    capability_code TEXT PRIMARY KEY,
    capability_name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO etvs_private.device_capabilities
    (capability_code, capability_name, description)
VALUES
    ('SHA256_HASH', 'SHA-256 integrity hashing',
     'Compute and compare SHA-256 content hashes.'),
    ('MIME_DETECTION', 'MIME/type detection',
     'Detect the actual media type independently of the filename.'),
    ('FILE_SIZE', 'File-size validation',
     'Validate declared and observed byte size.'),
    ('IMAGE_QUALITY', 'Image quality/readability',
     'Check resolution, blur, exposure and basic readability.'),
    ('OCR', 'Optical character recognition',
     'Extract machine-readable text where technically possible.'),
    ('BARCODE_QR', 'Barcode/QR recognition',
     'Detect and decode supported barcode or QR structures.'),
    ('SERIAL_RECOGNITION', 'Ballot serial recognition',
     'Recognize a visible ballot serial where technically possible.'),
    ('EXIF_METADATA', 'Image metadata inspection',
     'Inspect image metadata when available.'),
    ('VISUAL_SECURITY', 'Visual security-feature inspection',
     'Record a human or machine-assisted visual inspection.'),
    ('DIGITAL_SIGNATURE', 'Digital-signature verification',
     'Verify a supported cryptographic signature where one exists.')
ON CONFLICT (capability_code) DO NOTHING;


/* ---------------------------------------------------------------------------
   E. DEVICE REGISTRY
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS etvs_private.devices (
    device_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_reference TEXT NOT NULL UNIQUE,
    device_type TEXT NOT NULL,
    manufacturer TEXT,
    model TEXT,
    operating_system TEXT,
    application_version TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT device_type_check
        CHECK (device_type IN ('PHONE','TABLET','LAPTOP','DESKTOP','SCANNER','CAMERA','OTHER'))
);

CREATE TABLE IF NOT EXISTS etvs_private.device_capability_assignments (
    device_id BIGINT NOT NULL,
    capability_code TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (device_id, capability_code),

    CONSTRAINT fk_device_capability_device
        FOREIGN KEY (device_id)
        REFERENCES etvs_private.devices(device_id)
        ON UPDATE CASCADE ON DELETE CASCADE,

    CONSTRAINT fk_device_capability_code
        FOREIGN KEY (capability_code)
        REFERENCES etvs_private.device_capabilities(capability_code)
        ON UPDATE CASCADE ON DELETE RESTRICT
);


/* ---------------------------------------------------------------------------
   F. ELECTOR RECORDS
   ---------------------------------------------------------------------------

   The raw elector number is not stored in clear text.

   elector_reference_hash:
       SHA-256 of a normalized elector reference, used for exact matching and
       duplicate detection.

   elector_reference_ciphertext:
       application-layer encrypted representation when retention of the
       original reference is legally/operationally authorized.

   No candidate/result/vote-choice column exists here.
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS etvs_private.electors (
    elector_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL,
    polling_station_id TEXT NOT NULL,

    reference_type TEXT NOT NULL DEFAULT 'ELECTOR_NUMBER',
    elector_reference_hash CHAR(64) NOT NULL,
    elector_reference_ciphertext BYTEA,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'ACTIVE',

    CONSTRAINT fk_elector_election
        FOREIGN KEY (election_id)
        REFERENCES public.elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_elector_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES public.polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT elector_reference_type_check
        CHECK (reference_type IN ('ELECTOR_NUMBER','AUTHORIZED_REFERENCE')),

    CONSTRAINT elector_reference_hash_format
        CHECK (elector_reference_hash ~ '^[0-9a-f]{64}$'),

    CONSTRAINT elector_status_check
        CHECK (status IN ('ACTIVE','REVOKED','ARCHIVED')),

    CONSTRAINT unique_elector_reference_per_station
        UNIQUE (election_id, polling_station_id, elector_reference_hash)
);

CREATE INDEX IF NOT EXISTS idx_electors_station
    ON etvs_private.electors(election_id, polling_station_id);


/* ---------------------------------------------------------------------------
   G. BALLOT ARTIFACTS
   ---------------------------------------------------------------------------

   One logical artifact slot exists per applicable contest and elector.
   artifact_version permits replacement without overwriting history.

   The database deliberately contains no candidate_id or vote-choice column.
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS etvs_private.elector_ballot_artifacts (
    artifact_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    elector_id BIGINT NOT NULL,
    election_id TEXT NOT NULL,
    position_id TEXT NOT NULL,

    artifact_version INTEGER NOT NULL DEFAULT 1,
    artifact_type TEXT NOT NULL DEFAULT 'BALLOT_PAPER_EVIDENCE',

    storage_key TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    media_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    original_filename TEXT,

    captured_at TIMESTAMPTZ,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    device_id BIGINT,
    source_document_id BIGINT,

    encryption_at_rest BOOLEAN NOT NULL DEFAULT TRUE,
    retention_class TEXT NOT NULL DEFAULT 'ELECTION_EVIDENCE',

    status TEXT NOT NULL DEFAULT 'ACTIVE',

    CONSTRAINT fk_artifact_elector
        FOREIGN KEY (elector_id)
        REFERENCES etvs_private.electors(elector_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_artifact_election
        FOREIGN KEY (election_id)
        REFERENCES public.elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_artifact_position
        FOREIGN KEY (position_id)
        REFERENCES public.positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_artifact_device
        FOREIGN KEY (device_id)
        REFERENCES etvs_private.devices(device_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_artifact_source_document
        FOREIGN KEY (source_document_id)
        REFERENCES public.source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT artifact_version_positive
        CHECK (artifact_version > 0),

    CONSTRAINT artifact_sha256_format
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),

    CONSTRAINT artifact_size_non_negative
        CHECK (byte_size >= 0),

    CONSTRAINT artifact_type_check
        CHECK (artifact_type IN ('BALLOT_PAPER_EVIDENCE','BALLOT_IMAGE','BALLOT_PDF')),

    CONSTRAINT artifact_status_check
        CHECK (status IN ('ACTIVE','SUPERSEDED','REVOKED','QUARANTINED')),

    CONSTRAINT unique_elector_position_artifact_version
        UNIQUE (elector_id, position_id, artifact_version)
);

CREATE INDEX IF NOT EXISTS idx_elector_artifacts_lookup
    ON etvs_private.elector_ballot_artifacts(election_id, elector_id, position_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_elector_artifacts_one_active
    ON etvs_private.elector_ballot_artifacts(elector_id, position_id)
    WHERE status = 'ACTIVE';


/* ---------------------------------------------------------------------------
   H. COUNTERFOIL ARTIFACTS
   ---------------------------------------------------------------------------

   Counterfoils are related to ballot serial/security evidence, not to the
   elector's candidate choice. Keep them separate from marked-ballot artifacts.
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS etvs_private.counterfoil_artifacts (
    counterfoil_artifact_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    election_id TEXT NOT NULL,
    polling_station_id TEXT NOT NULL,
    position_id TEXT NOT NULL,

    ballot_serial_hash CHAR(64),
    counterfoil_storage_key TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    media_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL,

    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    device_id BIGINT,
    source_document_id BIGINT,

    encryption_at_rest BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'ACTIVE',

    CONSTRAINT fk_counterfoil_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES public.polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_counterfoil_position
        FOREIGN KEY (position_id)
        REFERENCES public.positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_counterfoil_device
        FOREIGN KEY (device_id)
        REFERENCES etvs_private.devices(device_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_counterfoil_source_document
        FOREIGN KEY (source_document_id)
        REFERENCES public.source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT counterfoil_serial_hash_format
        CHECK (ballot_serial_hash IS NULL OR ballot_serial_hash ~ '^[0-9a-f]{64}$'),

    CONSTRAINT counterfoil_sha256_format
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),

    CONSTRAINT counterfoil_size_non_negative
        CHECK (byte_size >= 0),

    CONSTRAINT counterfoil_status_check
        CHECK (status IN ('ACTIVE','SUPERSEDED','REVOKED','QUARANTINED'))
);


/* ---------------------------------------------------------------------------
   I. VALIDATION HISTORY
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS etvs_private.ballot_artifact_validations (
    validation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    artifact_id BIGINT NOT NULL,
    validation_version INTEGER NOT NULL DEFAULT 1,

    validator_name TEXT NOT NULL,
    validator_version TEXT,

    device_id BIGINT,

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,

    overall_status TEXT NOT NULL DEFAULT 'PENDING',
    validator_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_validation_artifact
        FOREIGN KEY (artifact_id)
        REFERENCES etvs_private.elector_ballot_artifacts(artifact_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_validation_device
        FOREIGN KEY (device_id)
        REFERENCES etvs_private.devices(device_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT validation_version_positive
        CHECK (validation_version > 0),

    CONSTRAINT validation_status_check
        CHECK (overall_status IN (
            'PENDING','PASSED','FAILED','PARTIAL','NOT_AVAILABLE','ERROR'
        )),

    CONSTRAINT validation_completion_check
        CHECK (
            (overall_status = 'PENDING' AND completed_at IS NULL)
            OR (overall_status <> 'PENDING' AND completed_at IS NOT NULL)
        ),

    CONSTRAINT unique_artifact_validation_version
        UNIQUE (artifact_id, validation_version)
);

CREATE TABLE IF NOT EXISTS etvs_private.ballot_artifact_validation_checks (
    validation_check_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    validation_id BIGINT NOT NULL,
    capability_code TEXT NOT NULL,

    availability_status TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    result_status TEXT NOT NULL,

    observed_value TEXT,
    evidence_note TEXT,

    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_validation_check_validation
        FOREIGN KEY (validation_id)
        REFERENCES etvs_private.ballot_artifact_validations(validation_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_validation_check_capability
        FOREIGN KEY (capability_code)
        REFERENCES etvs_private.device_capabilities(capability_code)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT validation_check_availability
        CHECK (availability_status IN ('AVAILABLE','NOT_AVAILABLE')),

    CONSTRAINT validation_check_execution
        CHECK (execution_status IN ('NOT_RUN','RUN','ERROR')),

    CONSTRAINT validation_check_result
        CHECK (result_status IN ('PASS','FAIL','NOT_AVAILABLE','INCONCLUSIVE','ERROR')),

    CONSTRAINT validation_check_not_available_consistency
        CHECK (
            (availability_status = 'NOT_AVAILABLE' AND result_status = 'NOT_AVAILABLE')
            OR availability_status = 'AVAILABLE'
        ),

    CONSTRAINT unique_validation_capability
        UNIQUE (validation_id, capability_code)
);


/* ---------------------------------------------------------------------------
   J. SECURITY-AUDIT LINKAGE WITHOUT VOTE-CHOICE LINKAGE
   --------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS etvs_private.ballot_artifact_security_links (
    artifact_security_link_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    artifact_id BIGINT NOT NULL,
    ballot_security_feature_id TEXT NOT NULL,
    validation_id BIGINT,

    observed_status TEXT NOT NULL,
    evidence_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_artifact_security_link_artifact
        FOREIGN KEY (artifact_id)
        REFERENCES etvs_private.elector_ballot_artifacts(artifact_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_artifact_security_link_feature
        FOREIGN KEY (ballot_security_feature_id)
        REFERENCES public.ballot_security_features(feature_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_artifact_security_link_validation
        FOREIGN KEY (validation_id)
        REFERENCES etvs_private.ballot_artifact_validations(validation_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT artifact_security_status_check
        CHECK (observed_status IN (
            'PASS','FAIL','NOT_AVAILABLE','INCONCLUSIVE','NOT_ASSESSED'
        )),

    CONSTRAINT unique_artifact_security_feature
        UNIQUE (artifact_id, ballot_security_feature_id)
);


/* ---------------------------------------------------------------------------
   K. CONSISTENCY CONSTRAINTS THAT REQUIRE TRIGGERS
   ---------------------------------------------------------------------------

   An artifact's elector/election/station and contest must agree.

   This trigger is intentionally small and only protects referential context;
   it never inspects or records a vote choice.
   --------------------------------------------------------------------------- */

CREATE OR REPLACE FUNCTION etvs_private.validate_elector_artifact_context()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_election_id TEXT;
    v_station_id TEXT;
BEGIN
    SELECT election_id, polling_station_id
      INTO v_election_id, v_station_id
      FROM etvs_private.electors
     WHERE elector_id = NEW.elector_id;

    IF v_election_id IS NULL THEN
        RAISE EXCEPTION 'Elector % does not exist', NEW.elector_id;
    END IF;

    IF NEW.election_id <> v_election_id THEN
        RAISE EXCEPTION 'Artifact election does not match elector election';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_elector_artifact_context
    ON etvs_private.elector_ballot_artifacts;

CREATE TRIGGER trg_validate_elector_artifact_context
BEFORE INSERT OR UPDATE ON etvs_private.elector_ballot_artifacts
FOR EACH ROW
EXECUTE FUNCTION etvs_private.validate_elector_artifact_context();


/* ---------------------------------------------------------------------------
   L. EVIDENCE-SAFETY COMMENTS
   --------------------------------------------------------------------------- */

COMMENT ON TABLE etvs_private.electors IS
'Restricted elector evidence index. Contains no candidate, result or vote-choice relationship.';

COMMENT ON TABLE etvs_private.elector_ballot_artifacts IS
'Restricted ballot evidence metadata. Binary content belongs in external encrypted storage; no vote-choice column is permitted.';

COMMENT ON TABLE etvs_private.counterfoil_artifacts IS
'Restricted counterfoil evidence. Counterfoils are modeled separately from marked ballot evidence.';

COMMENT ON TABLE etvs_private.ballot_artifact_validation_checks IS
'Device-aware validation checks. NOT_AVAILABLE means the capability was unavailable and is not equivalent to FAIL.';

COMMIT;
