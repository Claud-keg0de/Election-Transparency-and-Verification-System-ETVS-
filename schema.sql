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
2. KENYA GEOGRAPHIC REGIONS
===============================================================================

ETVS keeps Kenya's eight traditional regions as a geographic reference layer.
They are NOT electoral seats and are deliberately kept outside the political
contest hierarchy (county -> constituency -> ward -> polling station).

A separate mapping table can associate counties with a region for geographic
reporting without making a region a political seat or contest level.
===============================================================================
*/

CREATE TABLE regions (
    region_id TEXT PRIMARY KEY,

    region_name TEXT NOT NULL UNIQUE,

    region_type TEXT NOT NULL DEFAULT 'FORMER_PROVINCE',

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT region_type_check
        CHECK (region_type IN ('FORMER_PROVINCE', 'REFERENCE_REGION', 'OTHER'))
);


/*
===============================================================================
3. COUNTIES
===============================================================================
*/

CREATE TABLE counties (
    county_id TEXT PRIMARY KEY,

    county_name TEXT NOT NULL UNIQUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE county_region_assignments (
    county_id TEXT PRIMARY KEY,

    region_id TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_county_region_county
        FOREIGN KEY (county_id)
        REFERENCES counties(county_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_county_region_region
        FOREIGN KEY (region_id)
        REFERENCES regions(region_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);


/*
===============================================================================
4. CONSTITUENCIES
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
5. WARDS
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
6. REGISTRATION CENTRES
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
7. SPECIAL VOTING AREAS
===============================================================================

Diaspora and prisons are not counties, constituencies, wards or political seats.
They are represented as special voting areas so the normal Kenya geographic
hierarchy is not distorted. Election-specific polling stations can later be
attached to these areas using official Gazette data.
===============================================================================
*/

CREATE TABLE special_voting_areas (
    special_voting_area_id TEXT PRIMARY KEY,
    election_id TEXT NOT NULL,
    area_code TEXT NOT NULL,
    area_name TEXT NOT NULL,
    voting_category TEXT NOT NULL,
    country_name TEXT,
    source_document_id BIGINT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_special_area_election
        FOREIGN KEY (election_id) REFERENCES elections(election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_special_area_source
        FOREIGN KEY (source_document_id) REFERENCES source_documents(document_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT special_voting_category_check
        CHECK (voting_category IN ('DIASPORA','PRISON')),

    CONSTRAINT unique_special_area
        UNIQUE (election_id, area_code, country_name)
);


CREATE INDEX idx_special_voting_areas_election
    ON special_voting_areas(election_id, voting_category);


/*
===============================================================================
7B. SPECIAL VOTING AREA SLOTS AND HISTORICAL REFERENCE STATIONS
===============================================================================

SPECIAL VOTING SLOTS
--------------------
Special voting locations are election-specific and may increase, decrease,
move, or be retired between elections. ETVS therefore does not hard-code the
number of active diaspora or prison polling stations into the election model.

A slot is a configurable place-holder for an election-specific special polling
station. Slots can be added or retired without changing the schema.

HISTORICAL REFERENCE STATIONS
-----------------------------
Historical IEBC station records are kept separately as source/reference data.
They are never automatically treated as the active configuration for a future
election.
===============================================================================
*/

CREATE TABLE special_voting_slots (
    special_voting_slot_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    election_id TEXT NOT NULL,

    special_voting_area_id TEXT NOT NULL,

    slot_code TEXT NOT NULL,

    slot_number INTEGER NOT NULL,

    slot_status TEXT NOT NULL DEFAULT 'PLANNED',

    location_label TEXT,

    country_name TEXT,

    official_polling_station_code TEXT,

    registered_voters INTEGER,

    source_document_id BIGINT,

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_special_slot_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_special_slot_area
        FOREIGN KEY (special_voting_area_id)
        REFERENCES special_voting_areas(special_voting_area_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_special_slot_source
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT special_slot_status_check
        CHECK (slot_status IN ('PLANNED','ACTIVE','SUSPENDED','RETIRED')),

    CONSTRAINT special_slot_number_positive
        CHECK (slot_number > 0),

    CONSTRAINT special_slot_registered_non_negative
        CHECK (registered_voters IS NULL OR registered_voters >= 0),

    CONSTRAINT unique_special_slot_code
        UNIQUE (election_id, slot_code),

    CONSTRAINT unique_special_slot_number
        UNIQUE (election_id, special_voting_area_id, slot_number),

    CONSTRAINT unique_special_slot_area_pair
        UNIQUE (special_voting_slot_id, special_voting_area_id)
);

CREATE INDEX idx_special_voting_slots_area
    ON special_voting_slots(election_id, special_voting_area_id, slot_status);


CREATE TABLE special_voting_area_reference_stations (
    reference_station_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    special_voting_area_id TEXT NOT NULL,

    reference_year INTEGER NOT NULL,

    registration_centre_code TEXT,

    polling_station_code TEXT NOT NULL,

    polling_station_name TEXT,

    registered_voters INTEGER,

    source_document_id BIGINT,

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_special_reference_area
        FOREIGN KEY (special_voting_area_id)
        REFERENCES special_voting_areas(special_voting_area_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_special_reference_source
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT special_reference_year_check
        CHECK (reference_year >= 2012),

    CONSTRAINT special_reference_voters_non_negative
        CHECK (registered_voters IS NULL OR registered_voters >= 0),

    CONSTRAINT unique_special_reference_station
        UNIQUE (special_voting_area_id, reference_year, polling_station_code)
);

CREATE INDEX idx_special_reference_station_area
    ON special_voting_area_reference_stations(special_voting_area_id, reference_year);


/*
===============================================================================
7. POLLING STATIONS
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

    registration_centre_id TEXT,

    special_voting_area_id TEXT,

    special_voting_slot_id BIGINT,

    location_type TEXT NOT NULL DEFAULT 'NORMAL',

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

    CONSTRAINT fk_polling_station_special_area
        FOREIGN KEY (special_voting_area_id)
        REFERENCES special_voting_areas(special_voting_area_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_polling_station_special_slot
        FOREIGN KEY (special_voting_slot_id)
        REFERENCES special_voting_slots(special_voting_slot_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_polling_station_special_slot_area
        FOREIGN KEY (special_voting_slot_id, special_voting_area_id)
        REFERENCES special_voting_slots(special_voting_slot_id, special_voting_area_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT polling_station_location_type_check
        CHECK (location_type IN ('NORMAL','SPECIAL')),

    CONSTRAINT polling_station_location_exclusivity
        CHECK (
            (location_type = 'NORMAL' AND registration_centre_id IS NOT NULL AND special_voting_area_id IS NULL)
            OR
            (location_type = 'SPECIAL' AND registration_centre_id IS NULL
             AND special_voting_area_id IS NOT NULL
             AND special_voting_slot_id IS NOT NULL)
        ),

    CONSTRAINT polling_station_registered_voters_non_negative
        CHECK (registered_voters >= 0),

    CONSTRAINT unique_polling_station_code_per_election
        UNIQUE (election_id, polling_station_code),

    CONSTRAINT unique_polling_station_election_pair
        UNIQUE (polling_station_id, election_id)
);


/*
===============================================================================
8. TURNOUT REPORTING INTERVAL CONFIGURATION
===============================================================================

Each polling station may define its own expected interval for entering turnout
observations. Configuration is election-specific and time-versioned so changing
a station's interval never rewrites historical configuration used by earlier
observations.

Only one current configuration may exist for a polling station at a time.
Historical configurations remain available for audit and provenance.
===============================================================================
*/

CREATE TABLE turnout_reporting_intervals (
    turnout_interval_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    election_id TEXT NOT NULL,

    polling_station_id TEXT NOT NULL,

    interval_minutes INTEGER NOT NULL,

    effective_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    effective_to TIMESTAMPTZ,

    reporting_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_turnout_interval_election
        FOREIGN KEY (election_id)
        REFERENCES elections(election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_turnout_interval_station_election
        FOREIGN KEY (polling_station_id, election_id)
        REFERENCES polling_stations(polling_station_id, election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT turnout_interval_positive
        CHECK (interval_minutes > 0),

    CONSTRAINT turnout_interval_effective_window
        CHECK (effective_to IS NULL OR effective_to > effective_from),

    CONSTRAINT unique_turnout_interval_start
        UNIQUE (election_id, polling_station_id, effective_from)
);


CREATE UNIQUE INDEX uq_turnout_interval_current
    ON turnout_reporting_intervals(election_id, polling_station_id)
    WHERE effective_to IS NULL;


CREATE INDEX idx_turnout_interval_history
    ON turnout_reporting_intervals(election_id, polling_station_id, effective_from DESC);


/*
===============================================================================
9. CANDIDATES
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


/*
===============================================================================
7A. SPECIAL-AREA CONTEST REFERENCE RULES
===============================================================================

This table stores historical or future eligibility rules independently from the
active election row. This is important because historical 2022 voting rules
must not be silently applied to the 2027 election.

For example, 2022 IEBC material records presidential voting for the diaspora
and prison special-voting categories. A future 2027 rule must be loaded as its
own reference-year record from the applicable official legal/Gazette material.
===============================================================================
*/

CREATE TABLE special_area_contest_rules (
    special_area_contest_rule_id BIGINT
        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    special_voting_area_id TEXT NOT NULL,

    position_id TEXT NOT NULL,

    reference_year INTEGER NOT NULL,

    eligibility_status TEXT NOT NULL,

    source_document_id BIGINT,

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_special_rule_area
        FOREIGN KEY (special_voting_area_id)
        REFERENCES special_voting_areas(special_voting_area_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_special_rule_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT fk_special_rule_source
        FOREIGN KEY (source_document_id)
        REFERENCES source_documents(document_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT special_rule_status_check
        CHECK (eligibility_status IN ('ALLOWED','NOT_ELIGIBLE')),

    CONSTRAINT special_rule_year_check
        CHECK (reference_year >= 2012),

    CONSTRAINT unique_special_area_contest_rule
        UNIQUE (special_voting_area_id, position_id, reference_year)
);

CREATE INDEX idx_special_area_contest_rules_year
    ON special_area_contest_rules(reference_year, special_voting_area_id);

CREATE TABLE political_parties (
    party_id TEXT PRIMARY KEY,

    party_name TEXT NOT NULL UNIQUE,

    party_abbreviation TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_party_abbreviation UNIQUE (party_abbreviation)
);


CREATE TABLE party_symbols (
    party_symbol_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    party_id TEXT NOT NULL,

    symbol_name TEXT NOT NULL,

    symbol_uri TEXT,

    approved BOOLEAN NOT NULL DEFAULT TRUE,

    effective_from DATE,

    effective_to DATE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_party_symbol_party
        FOREIGN KEY (party_id)
        REFERENCES political_parties(party_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT party_symbol_effective_window
        CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from),

    CONSTRAINT unique_party_symbol_name
        UNIQUE (party_id, symbol_name)
);


CREATE UNIQUE INDEX uq_party_symbol_current
    ON party_symbols(party_id)
    WHERE effective_to IS NULL;


CREATE TABLE candidates (
    candidate_id TEXT PRIMARY KEY,

    election_id TEXT NOT NULL,

    candidate_name TEXT NOT NULL,

    office TEXT NOT NULL,

    position_id TEXT,

    candidate_type TEXT NOT NULL DEFAULT 'PARTY',

    party_id TEXT,

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

    CONSTRAINT fk_candidate_party
        FOREIGN KEY (party_id)
        REFERENCES political_parties(party_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT candidate_type_check
        CHECK (candidate_type IN ('PARTY', 'INDEPENDENT')),

    CONSTRAINT candidate_party_affiliation_check
        CHECK ((candidate_type = 'PARTY' AND party_id IS NOT NULL)
            OR (candidate_type = 'INDEPENDENT' AND party_id IS NULL)),

    CONSTRAINT unique_candidate_election_pair
        UNIQUE (candidate_id, election_id)
);


CREATE TABLE independent_candidate_symbols (
    independent_symbol_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    candidate_id TEXT NOT NULL UNIQUE,

    election_id TEXT NOT NULL,

    symbol_name TEXT NOT NULL,

    symbol_uri TEXT,

    approved BOOLEAN NOT NULL DEFAULT TRUE,

    approved_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_independent_symbol_candidate
        FOREIGN KEY (candidate_id, election_id)
        REFERENCES candidates(candidate_id, election_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT independent_symbol_candidate_type_check
        CHECK (candidate_id IS NOT NULL)
);


/*
===============================================================================
8A. CANDIDATE ELECTORAL-AREA ASSIGNMENTS
===============================================================================

A candidate is contest-specific and electoral-area-specific. The Elections Act
and Elections (General) Regulations define an electoral area as a constituency,
county or ward; the presidential contest is national. ETVS therefore records
which area a candidate is nominated for instead of treating a candidate as
valid for every polling station in an election.

For party candidates, the same party may have one candidate slot per applicable
contest and electoral area. Independent candidates are also tied to their
specific contest and area, with no party slot.
===============================================================================
*/

CREATE TABLE candidate_electoral_areas (
    candidate_electoral_area_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    candidate_id TEXT NOT NULL,
    election_id TEXT NOT NULL,
    position_id TEXT NOT NULL,
    electoral_area_type TEXT NOT NULL,
    electoral_area_id TEXT NOT NULL,
    candidate_type TEXT NOT NULL,
    party_id TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_candidate_area_candidate
        FOREIGN KEY (candidate_id, election_id)
        REFERENCES candidates(candidate_id, election_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_candidate_area_position
        FOREIGN KEY (position_id)
        REFERENCES positions(position_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_candidate_area_party
        FOREIGN KEY (party_id)
        REFERENCES political_parties(party_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT candidate_area_type_check
        CHECK (electoral_area_type IN ('NATIONAL','COUNTY','CONSTITUENCY','WARD')),

    CONSTRAINT candidate_area_candidate_type_check
        CHECK (candidate_type IN ('PARTY','INDEPENDENT')),

    CONSTRAINT candidate_area_party_check
        CHECK ((candidate_type='PARTY' AND party_id IS NOT NULL)
            OR (candidate_type='INDEPENDENT' AND party_id IS NULL)),

    CONSTRAINT unique_candidate_area_assignment
        UNIQUE (candidate_id, election_id),

);

CREATE UNIQUE INDEX uq_party_candidate_slot
    ON candidate_electoral_areas(election_id, position_id, electoral_area_type, electoral_area_id, party_id)
    WHERE candidate_type='PARTY';

CREATE INDEX idx_candidate_area_lookup
    ON candidate_electoral_areas(election_id, position_id, electoral_area_type, electoral_area_id);

CREATE OR REPLACE FUNCTION validate_candidate_electoral_area()
RETURNS trigger
LANGUAGE plpgsql
AS $
DECLARE
    expected_geography TEXT;
    candidate_position TEXT;
    candidate_party TEXT;
    candidate_kind TEXT;
BEGIN
    SELECT p.geography_level, c.position_id, c.party_id, c.candidate_type
      INTO expected_geography, candidate_position, candidate_party, candidate_kind
      FROM candidates c
      JOIN positions p ON p.position_id=c.position_id
     WHERE c.candidate_id=NEW.candidate_id
       AND c.election_id=NEW.election_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Candidate % does not belong to election %', NEW.candidate_id, NEW.election_id;
    END IF;

    IF NEW.position_id <> candidate_position THEN
        RAISE EXCEPTION 'Candidate % is assigned to position %, not %', NEW.candidate_id, candidate_position, NEW.position_id;
    END IF;

    IF NEW.electoral_area_type <> expected_geography THEN
        RAISE EXCEPTION 'Position % requires % electoral area, not %', NEW.position_id, expected_geography, NEW.electoral_area_type;
    END IF;

    IF NEW.candidate_type <> candidate_kind OR NEW.party_id IS DISTINCT FROM candidate_party THEN
        RAISE EXCEPTION 'Candidate affiliation mismatch for %', NEW.candidate_id;
    END IF;

    IF NEW.electoral_area_type='NATIONAL' THEN
        IF NEW.electoral_area_id <> 'NATIONAL' THEN
            RAISE EXCEPTION 'National contests must use electoral area NATIONAL';
        END IF;
    ELSIF NEW.electoral_area_type='COUNTY' THEN
        IF NOT EXISTS (SELECT 1 FROM counties WHERE county_id=NEW.electoral_area_id) THEN
            RAISE EXCEPTION 'Unknown county electoral area %', NEW.electoral_area_id;
        END IF;
    ELSIF NEW.electoral_area_type='CONSTITUENCY' THEN
        IF NOT EXISTS (SELECT 1 FROM constituencies WHERE constituency_id=NEW.electoral_area_id) THEN
            RAISE EXCEPTION 'Unknown constituency electoral area %', NEW.electoral_area_id;
        END IF;
    ELSIF NEW.electoral_area_type='WARD' THEN
        IF NOT EXISTS (SELECT 1 FROM wards WHERE ward_id=NEW.electoral_area_id) THEN
            RAISE EXCEPTION 'Unknown ward electoral area %', NEW.electoral_area_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$;

CREATE TRIGGER trg_validate_candidate_electoral_area
BEFORE INSERT OR UPDATE ON candidate_electoral_areas
FOR EACH ROW EXECUTE FUNCTION validate_candidate_electoral_area();

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
10. TURNOUT OBSERVATIONS
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

    interval_configuration_id BIGINT,

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

    CONSTRAINT fk_turnout_interval_configuration
        FOREIGN KEY (interval_configuration_id)
        REFERENCES turnout_reporting_intervals(turnout_interval_id)
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

    observation_version INTEGER NOT NULL DEFAULT 1,

    valid_votes INTEGER NOT NULL,

    rejected_votes INTEGER NOT NULL,

    spoilt_ballots INTEGER NOT NULL,

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


/* Enforce that a result candidate is valid for the polling station's contest area. */
CREATE OR REPLACE FUNCTION validate_result_candidate_electoral_area()
RETURNS trigger
LANGUAGE plpgsql
AS $
DECLARE
    station_area_type TEXT;
    station_area_id TEXT;
    candidate_area_type TEXT;
    candidate_area_id TEXT;
BEGIN
    SELECT p.geography_level,
           CASE p.geography_level
             WHEN 'NATIONAL' THEN 'NATIONAL'
             WHEN 'COUNTY' THEN co.county_id
             WHEN 'CONSTITUENCY' THEN co2.constituency_id
             WHEN 'WARD' THEN w.ward_id
           END
      INTO station_area_type, station_area_id
      FROM polling_stations ps
      LEFT JOIN registration_centres rc ON rc.registration_centre_id=ps.registration_centre_id
      LEFT JOIN wards w ON w.ward_id=rc.ward_id
      LEFT JOIN constituencies co2 ON co2.constituency_id=w.constituency_id
      LEFT JOIN counties co ON co.county_id=co2.county_id
      JOIN positions p ON p.position_id=NEW.position_id
     WHERE ps.polling_station_id=NEW.polling_station_id
       AND ps.election_id=NEW.election_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Cannot resolve polling station % and position %', NEW.polling_station_id, NEW.position_id;
    END IF;

    IF station_area_type='NATIONAL' AND EXISTS (
        SELECT 1 FROM polling_stations WHERE polling_station_id=NEW.polling_station_id AND location_type='SPECIAL'
    ) THEN
        -- Special-area eligibility is separately modeled and remains configurable.
        RETURN NEW;
    END IF;

    SELECT cea.electoral_area_type, cea.electoral_area_id
      INTO candidate_area_type, candidate_area_id
      FROM candidate_electoral_areas cea
     WHERE cea.candidate_id=NEW.candidate_id
       AND cea.election_id=NEW.election_id
       AND cea.position_id=NEW.position_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Candidate % has no electoral-area assignment for position %', NEW.candidate_id, NEW.position_id;
    END IF;

    IF candidate_area_type <> station_area_type OR candidate_area_id <> station_area_id THEN
        RAISE EXCEPTION 'Candidate % is not nominated for polling station % area (%:%); candidate area is (%:%)',
            NEW.candidate_id, NEW.polling_station_id, station_area_type, station_area_id,
            candidate_area_type, candidate_area_id;
    END IF;

    RETURN NEW;
END;
$;

CREATE TRIGGER trg_validate_result_candidate_electoral_area
BEFORE INSERT OR UPDATE ON result_submissions
FOR EACH ROW EXECUTE FUNCTION validate_result_candidate_electoral_area();


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