--
-- PostgreSQL database dump
--

\restrict dPjJKxbdYuNvHoEVTEmj5FC1osUkpLdrQjm10KDLQgE8ENqa64ywyjMSpL2m036

-- Dumped from database version 18.6
-- Dumped by pg_dump version 18.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: postgres
--

-- *not* creating schema, since initdb creates it


ALTER SCHEMA public OWNER TO postgres;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: postgres
--

COMMENT ON SCHEMA public IS '';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_failed_results; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_failed_results (
    audit_failed_id bigint NOT NULL,
    audit_finding_id bigint NOT NULL,
    audit_run_id bigint NOT NULL,
    election_id text NOT NULL,
    candidate_id text,
    geography_level text,
    geography_id text,
    polling_station_id text,
    rule_code text NOT NULL,
    message text NOT NULL,
    observed_value integer,
    maximum_value integer,
    recorded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.audit_failed_results OWNER TO postgres;

--
-- Name: audit_failed_results_audit_failed_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.audit_failed_results ALTER COLUMN audit_failed_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.audit_failed_results_audit_failed_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_findings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_findings (
    audit_finding_id bigint NOT NULL,
    audit_run_id bigint NOT NULL,
    election_id text NOT NULL,
    polling_station_id text,
    rule_code text NOT NULL,
    status text NOT NULL,
    observed_value integer,
    maximum_value integer,
    message text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    previous_hash text,
    current_hash text NOT NULL,
    candidate_id text,
    geography_level text,
    geography_id text,
    CONSTRAINT audit_status_check CHECK ((status = ANY (ARRAY['PASSED'::text, 'FAILED'::text, 'WARNING'::text]))),
    CONSTRAINT current_hash_format CHECK ((current_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT maximum_value_non_negative CHECK (((maximum_value IS NULL) OR (maximum_value >= 0))),
    CONSTRAINT observed_value_non_negative CHECK (((observed_value IS NULL) OR (observed_value >= 0))),
    CONSTRAINT previous_hash_format CHECK (((previous_hash IS NULL) OR (previous_hash ~ '^[0-9a-f]{64}$'::text)))
);


ALTER TABLE public.audit_findings OWNER TO postgres;

--
-- Name: audit_findings_audit_finding_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.audit_findings ALTER COLUMN audit_finding_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.audit_findings_audit_finding_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_passed_results; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_passed_results (
    audit_passed_id bigint NOT NULL,
    audit_finding_id bigint NOT NULL,
    audit_run_id bigint NOT NULL,
    election_id text NOT NULL,
    candidate_id text,
    geography_level text,
    geography_id text,
    polling_station_id text,
    rule_code text NOT NULL,
    message text NOT NULL,
    observed_value integer,
    maximum_value integer,
    recorded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.audit_passed_results OWNER TO postgres;

--
-- Name: audit_passed_results_audit_passed_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.audit_passed_results ALTER COLUMN audit_passed_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.audit_passed_results_audit_passed_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_runs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_runs (
    audit_run_id bigint NOT NULL,
    election_id text NOT NULL,
    started_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    completed_at timestamp with time zone,
    status text DEFAULT 'RUNNING'::text NOT NULL,
    findings_count integer DEFAULT 0 NOT NULL,
    scope_level text,
    scope_id text,
    candidate_id text,
    CONSTRAINT audit_run_status_check CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text]))),
    CONSTRAINT completed_run_has_completion_time CHECK (((status = 'RUNNING'::text) OR (completed_at IS NOT NULL))),
    CONSTRAINT findings_count_non_negative CHECK ((findings_count >= 0))
);


ALTER TABLE public.audit_runs OWNER TO postgres;

--
-- Name: audit_runs_audit_run_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.audit_runs ALTER COLUMN audit_run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.audit_runs_audit_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ballot_accounting_observations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ballot_accounting_observations (
    ballot_accounting_observation_id bigint CONSTRAINT ballot_accounting_observati_ballot_accounting_observat_not_null NOT NULL,
    election_id text NOT NULL,
    polling_station_id text NOT NULL,
    observation_version integer DEFAULT 1 NOT NULL,
    valid_votes integer NOT NULL,
    rejected_votes integer NOT NULL,
    spoilt_ballots integer NOT NULL,
    observed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    source_reference text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    source_document_id bigint,
    CONSTRAINT ballot_version_positive CHECK ((observation_version > 0)),
    CONSTRAINT rejected_votes_non_negative CHECK ((rejected_votes >= 0)),
    CONSTRAINT spoilt_ballots_non_negative CHECK ((spoilt_ballots >= 0)),
    CONSTRAINT valid_votes_non_negative CHECK ((valid_votes >= 0))
);


ALTER TABLE public.ballot_accounting_observations OWNER TO postgres;

--
-- Name: ballot_accounting_observation_ballot_accounting_observation_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.ballot_accounting_observations ALTER COLUMN ballot_accounting_observation_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.ballot_accounting_observation_ballot_accounting_observation_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: candidates; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.candidates (
    candidate_id text NOT NULL,
    election_id text NOT NULL,
    candidate_name text NOT NULL,
    office text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.candidates OWNER TO postgres;

--
-- Name: constituencies; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.constituencies (
    constituency_id text NOT NULL,
    constituency_name text NOT NULL,
    county_id text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.constituencies OWNER TO postgres;

--
-- Name: counties; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.counties (
    county_id text NOT NULL,
    county_name text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.counties OWNER TO postgres;

--
-- Name: elections; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.elections (
    election_id text NOT NULL,
    election_name text NOT NULL,
    election_date date NOT NULL,
    status text DEFAULT 'ACTIVE'::text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT elections_status_check CHECK ((status = ANY (ARRAY['ACTIVE'::text, 'CLOSED'::text, 'ARCHIVED'::text])))
);


ALTER TABLE public.elections OWNER TO postgres;

--
-- Name: polling_stations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.polling_stations (
    polling_station_id text NOT NULL,
    election_id text NOT NULL,
    registration_centre_id text NOT NULL,
    polling_station_code text NOT NULL,
    registered_voters integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT polling_station_registered_voters_non_negative CHECK ((registered_voters >= 0))
);


ALTER TABLE public.polling_stations OWNER TO postgres;

--
-- Name: published_aggregate_totals; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.published_aggregate_totals (
    published_aggregate_id bigint NOT NULL,
    election_id text NOT NULL,
    source_document_id bigint NOT NULL,
    aggregation_level text NOT NULL,
    geography_id text NOT NULL,
    candidate_id text,
    metric text NOT NULL,
    reported_value integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.published_aggregate_totals OWNER TO postgres;

--
-- Name: published_aggregate_totals_published_aggregate_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.published_aggregate_totals ALTER COLUMN published_aggregate_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.published_aggregate_totals_published_aggregate_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: registration_centres; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.registration_centres (
    registration_centre_id text NOT NULL,
    registration_centre_name text NOT NULL,
    ward_id text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.registration_centres OWNER TO postgres;

--
-- Name: result_submissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.result_submissions (
    result_submission_id bigint NOT NULL,
    election_id text NOT NULL,
    polling_station_id text NOT NULL,
    candidate_id text NOT NULL,
    result_version integer DEFAULT 1 NOT NULL,
    votes integer NOT NULL,
    submitted_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    source_reference text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    source_document_id bigint,
    submission_hash text,
    CONSTRAINT result_version_positive CHECK ((result_version > 0)),
    CONSTRAINT result_votes_non_negative CHECK ((votes >= 0))
);


ALTER TABLE public.result_submissions OWNER TO postgres;

--
-- Name: result_submissions_result_submission_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.result_submissions ALTER COLUMN result_submission_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.result_submissions_result_submission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: source_comparisons; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.source_comparisons (
    source_comparison_id bigint NOT NULL,
    audit_run_id bigint NOT NULL,
    election_id text NOT NULL,
    published_document_id bigint NOT NULL,
    derived_source_document_id bigint,
    aggregation_level text NOT NULL,
    geography_id text NOT NULL,
    candidate_id text,
    metric text NOT NULL,
    published_value integer,
    derived_value integer,
    difference integer,
    status text NOT NULL,
    compared_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.source_comparisons OWNER TO postgres;

--
-- Name: source_comparisons_source_comparison_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.source_comparisons ALTER COLUMN source_comparison_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.source_comparisons_source_comparison_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: source_documents; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.source_documents (
    document_id bigint NOT NULL,
    source_id text NOT NULL,
    document_name text NOT NULL,
    document_type text NOT NULL,
    document_uri text,
    content_hash text NOT NULL,
    retrieved_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT source_document_hash_format CHECK ((content_hash ~ '^[0-9a-f]{64}$'::text))
);


ALTER TABLE public.source_documents OWNER TO postgres;

--
-- Name: source_documents_document_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.source_documents ALTER COLUMN document_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.source_documents_document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: sources; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sources (
    source_id text NOT NULL,
    source_name text NOT NULL,
    source_type text NOT NULL,
    organization_name text,
    description text,
    source_url text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT sources_type_check CHECK ((source_type = ANY (ARRAY['OFFICIAL'::text, 'MEDIA'::text, 'CIVIL_SOCIETY'::text, 'OTHER'::text])))
);


ALTER TABLE public.sources OWNER TO postgres;

--
-- Name: turnout_observations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.turnout_observations (
    turnout_observation_id bigint NOT NULL,
    election_id text NOT NULL,
    polling_station_id text NOT NULL,
    observation_version integer DEFAULT 1 NOT NULL,
    voters_turnout integer NOT NULL,
    observed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    source_reference text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    source_document_id bigint,
    CONSTRAINT turnout_non_negative CHECK ((voters_turnout >= 0)),
    CONSTRAINT turnout_version_positive CHECK ((observation_version > 0))
);


ALTER TABLE public.turnout_observations OWNER TO postgres;

--
-- Name: turnout_observations_turnout_observation_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.turnout_observations ALTER COLUMN turnout_observation_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.turnout_observations_turnout_observation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: wards; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.wards (
    ward_id text NOT NULL,
    ward_name text NOT NULL,
    constituency_id text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.wards OWNER TO postgres;

--
-- Data for Name: audit_failed_results; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.audit_failed_results (audit_failed_id, audit_finding_id, audit_run_id, election_id, candidate_id, geography_level, geography_id, polling_station_id, rule_code, message, observed_value, maximum_value, recorded_at) FROM stdin;
\.


--
-- Data for Name: audit_findings; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.audit_findings (audit_finding_id, audit_run_id, election_id, polling_station_id, rule_code, status, observed_value, maximum_value, message, created_at, previous_hash, current_hash, candidate_id, geography_level, geography_id) FROM stdin;
\.


--
-- Data for Name: audit_passed_results; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.audit_passed_results (audit_passed_id, audit_finding_id, audit_run_id, election_id, candidate_id, geography_level, geography_id, polling_station_id, rule_code, message, observed_value, maximum_value, recorded_at) FROM stdin;
\.


--
-- Data for Name: audit_runs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.audit_runs (audit_run_id, election_id, started_at, completed_at, status, findings_count, scope_level, scope_id, candidate_id) FROM stdin;
\.


--
-- Data for Name: ballot_accounting_observations; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.ballot_accounting_observations (ballot_accounting_observation_id, election_id, polling_station_id, observation_version, valid_votes, rejected_votes, spoilt_ballots, observed_at, source_reference, created_at, source_document_id) FROM stdin;
37	KE-PRES-2027	PS001	1	680	15	5	2026-09-11 18:15:18.031568+07	SEED-BALLOT-PS001	2026-09-11 18:15:18.031568+07	4
38	KE-PRES-2027	PS002	1	480	15	5	2026-09-11 18:15:18.031568+07	SEED-BALLOT-PS002	2026-09-11 18:15:18.031568+07	4
39	KE-PRES-2027	PS003	1	960	25	15	2026-09-11 18:15:18.031568+07	SEED-BALLOT-PS003	2026-09-11 18:15:18.031568+07	4
40	KE-PRES-2027	PS004	1	850	30	20	2026-09-11 18:15:18.031568+07	SEED-BALLOT-PS004	2026-09-11 18:15:18.031568+07	4
41	KE-PRES-2027	PS005	1	420	15	5	2026-09-11 18:15:18.031568+07	SEED-BALLOT-PS005	2026-09-11 18:15:18.031568+07	4
42	KE-PRES-2027	PS006	1	650	30	0	2026-09-11 18:15:18.031568+07	SEED-BALLOT-PS006	2026-09-11 18:15:18.031568+07	4
\.


--
-- Data for Name: candidates; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.candidates (candidate_id, election_id, candidate_name, office, created_at) FROM stdin;
CAND001	KE-PRES-2027	Amina Njeri	PRESIDENT	2026-09-11 18:15:18.031568+07
CAND002	KE-PRES-2027	Brian Wanyonyi	PRESIDENT	2026-09-11 18:15:18.031568+07
CAND003	KE-PRES-2027	David Mwangi	PRESIDENT	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: constituencies; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.constituencies (constituency_id, constituency_name, county_id, created_at) FROM stdin;
CON001	Greenfield Constituency	COUNTY001	2026-09-11 18:15:18.031568+07
CON002	Riverdale Constituency	COUNTY001	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: counties; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.counties (county_id, county_name, created_at) FROM stdin;
COUNTY001	Sample County	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: elections; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.elections (election_id, election_name, election_date, status, created_at) FROM stdin;
KE-PRES-2027	ETVS Presidential Election 2027	2027-08-10	ACTIVE	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: polling_stations; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.polling_stations (polling_station_id, election_id, registration_centre_id, polling_station_code, registered_voters, created_at) FROM stdin;
PS001	KE-PRES-2027	RC001	PS-001	1000	2026-09-11 18:15:18.031568+07
PS002	KE-PRES-2027	RC002	PS-002	800	2026-09-11 18:15:18.031568+07
PS003	KE-PRES-2027	RC003	PS-003	950	2026-09-11 18:15:18.031568+07
PS004	KE-PRES-2027	RC004	PS-004	1200	2026-09-11 18:15:18.031568+07
PS005	KE-PRES-2027	RC005	PS-005	600	2026-09-11 18:15:18.031568+07
PS006	KE-PRES-2027	RC006	PS-006	700	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: published_aggregate_totals; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.published_aggregate_totals (published_aggregate_id, election_id, source_document_id, aggregation_level, geography_id, candidate_id, metric, reported_value, created_at) FROM stdin;
33	KE-PRES-2027	5	WARD	W001	\N	TURNOUT	1700	2026-09-11 18:15:18.031568+07
34	KE-PRES-2027	5	WARD	W001	CAND001	CANDIDATE_VOTES	850	2026-09-11 18:15:18.031568+07
35	KE-PRES-2027	5	CONSTITUENCY	CON001	\N	TURNOUT	2200	2026-09-11 18:15:18.031568+07
36	KE-PRES-2027	5	CONSTITUENCY	CON001	CAND001	CANDIDATE_VOTES	1107	2026-09-11 18:15:18.031568+07
37	KE-PRES-2027	5	COUNTY	COUNTY001	\N	TURNOUT	4200	2026-09-11 18:15:18.031568+07
38	KE-PRES-2027	5	COUNTY	COUNTY001	CAND001	CANDIDATE_VOTES	2145	2026-09-11 18:15:18.031568+07
39	KE-PRES-2027	5	NATIONAL	NATIONAL	\N	TURNOUT	4200	2026-09-11 18:15:18.031568+07
40	KE-PRES-2027	5	NATIONAL	NATIONAL	CAND001	CANDIDATE_VOTES	2145	2026-09-11 18:15:18.031568+07
41	KE-PRES-2027	5	WARD	W001	CAND002	CANDIDATE_VOTES	520	2026-09-11 18:15:18.031568+07
42	KE-PRES-2027	5	CONSTITUENCY	CON001	CAND002	CANDIDATE_VOTES	670	2026-09-11 18:15:18.031568+07
43	KE-PRES-2027	5	COUNTY	COUNTY001	CAND002	CANDIDATE_VOTES	1260	2026-09-11 18:15:18.031568+07
44	KE-PRES-2027	5	NATIONAL	NATIONAL	CAND002	CANDIDATE_VOTES	1260	2026-09-11 18:15:18.031568+07
45	KE-PRES-2027	5	WARD	W001	CAND003	CANDIDATE_VOTES	270	2026-09-11 18:15:18.031568+07
46	KE-PRES-2027	5	CONSTITUENCY	CON001	CAND003	CANDIDATE_VOTES	350	2026-09-11 18:15:18.031568+07
47	KE-PRES-2027	5	COUNTY	COUNTY001	CAND003	CANDIDATE_VOTES	670	2026-09-11 18:15:18.031568+07
48	KE-PRES-2027	5	NATIONAL	NATIONAL	CAND003	CANDIDATE_VOTES	670	2026-09-11 18:15:18.031568+07
49	KE-PRES-2027	5	WARD	W002	\N	TURNOUT	500	2026-09-11 18:15:18.031568+07
50	KE-PRES-2027	5	WARD	W002	CAND001	CANDIDATE_VOTES	250	2026-09-11 18:15:18.031568+07
51	KE-PRES-2027	5	WARD	W002	CAND002	CANDIDATE_VOTES	150	2026-09-11 18:15:18.031568+07
52	KE-PRES-2027	5	WARD	W002	CAND003	CANDIDATE_VOTES	80	2026-09-11 18:15:18.031568+07
53	KE-PRES-2027	5	WARD	W003	\N	TURNOUT	1550	2026-09-11 18:15:18.031568+07
54	KE-PRES-2027	5	WARD	W003	CAND001	CANDIDATE_VOTES	830	2026-09-11 18:15:18.031568+07
55	KE-PRES-2027	5	CONSTITUENCY	CON002	\N	TURNOUT	2000	2026-09-11 18:15:18.031568+07
56	KE-PRES-2027	5	CONSTITUENCY	CON002	CAND001	CANDIDATE_VOTES	1045	2026-09-11 18:15:18.031568+07
57	KE-PRES-2027	5	WARD	W003	CAND002	CANDIDATE_VOTES	450	2026-09-11 18:15:18.031568+07
58	KE-PRES-2027	5	CONSTITUENCY	CON002	CAND002	CANDIDATE_VOTES	590	2026-09-11 18:15:18.031568+07
59	KE-PRES-2027	5	WARD	W003	CAND003	CANDIDATE_VOTES	250	2026-09-11 18:15:18.031568+07
60	KE-PRES-2027	5	CONSTITUENCY	CON002	CAND003	CANDIDATE_VOTES	320	2026-09-11 18:15:18.031568+07
61	KE-PRES-2027	5	WARD	W004	\N	TURNOUT	450	2026-09-11 18:15:18.031568+07
62	KE-PRES-2027	5	WARD	W004	CAND001	CANDIDATE_VOTES	215	2026-09-11 18:15:18.031568+07
63	KE-PRES-2027	5	WARD	W004	CAND002	CANDIDATE_VOTES	140	2026-09-11 18:15:18.031568+07
64	KE-PRES-2027	5	WARD	W004	CAND003	CANDIDATE_VOTES	70	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: registration_centres; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.registration_centres (registration_centre_id, registration_centre_name, ward_id, created_at) FROM stdin;
RC001	Greenfield Primary School	W001	2026-09-11 18:15:18.031568+07
RC002	Greenfield Community Hall	W002	2026-09-11 18:15:18.031568+07
RC003	Greenfield Secondary School	W001	2026-09-11 18:15:18.031568+07
RC004	Riverdale Primary School	W003	2026-09-11 18:15:18.031568+07
RC005	Riverdale Community Hall	W004	2026-09-11 18:15:18.031568+07
RC006	Riverdale Secondary School	W003	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: result_submissions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.result_submissions (result_submission_id, election_id, polling_station_id, candidate_id, result_version, votes, submitted_at, source_reference, created_at, source_document_id, submission_hash) FROM stdin;
115	KE-PRES-2027	PS001	CAND001	1	350	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS001-V1	2026-09-11 18:15:18.031568+07	4	7d6da5884c7fc4e98ee79f5d225931af670ef4d186b7cfd777335814ad44dc99
116	KE-PRES-2027	PS001	CAND002	1	220	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS001-V1	2026-09-11 18:15:18.031568+07	4	56d97ef022bb87590dcbb6b4b694411e3c2b8a0f3bad73fc1a7331e9af418b3e
117	KE-PRES-2027	PS001	CAND003	1	110	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS001-V1	2026-09-11 18:15:18.031568+07	4	25ca719ca19d9b456ef311e4e60bc599ecf15805478f3112b043b5b772ee31c2
118	KE-PRES-2027	PS002	CAND001	1	250	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS002-V1	2026-09-11 18:15:18.031568+07	4	1f0be1cf1c36e5d290f957cb4af503b484535babc38d249a194ba5239bebe1a4
119	KE-PRES-2027	PS002	CAND002	1	150	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS002-V1	2026-09-11 18:15:18.031568+07	4	36c5b328f553abaf9b141064d9927e51b74b007dc9987139d5f815d049b31365
120	KE-PRES-2027	PS002	CAND003	1	80	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS002-V1	2026-09-11 18:15:18.031568+07	4	921fd2db981c43d0470ad45ca05af68bb3d3eb9b9a51a6be7fc53e473176f52f
121	KE-PRES-2027	PS003	CAND001	1	500	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS003-V1	2026-09-11 18:15:18.031568+07	4	87bb3a513f3332722788ff8cdb5349324aa020366988ed62331569101675ea08
122	KE-PRES-2027	PS003	CAND002	1	300	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS003-V1	2026-09-11 18:15:18.031568+07	4	0d776fc4abf5735b5571262f84459a76333b3c0fc035c288c5e2f0473da3d064
123	KE-PRES-2027	PS003	CAND003	1	160	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS003-V1	2026-09-11 18:15:18.031568+07	4	d5413fcc6fc75979fd9794ebe1e2f72e127acd53c750139cbcf023944f74455d
124	KE-PRES-2027	PS004	CAND001	1	430	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS004-V1	2026-09-11 18:15:18.031568+07	4	51ba6607f19f5f93d8eb982ecf1beb94b495ea34826cf67b41712cc228c52cbf
125	KE-PRES-2027	PS004	CAND002	1	270	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS004-V1	2026-09-11 18:15:18.031568+07	4	f55b16df3cf21a7b776b10546a4559d1837209c071687481be75c1c65c7d1ca1
126	KE-PRES-2027	PS004	CAND003	1	150	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS004-V1	2026-09-11 18:15:18.031568+07	4	4006e3859a43bb472f24f584a3d9ef18828954a4a762e533a711e071bd127947
127	KE-PRES-2027	PS005	CAND001	1	210	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS005-V1	2026-09-11 18:15:18.031568+07	4	ce292db173cecc4857266570afdee418ea6b5151e7c1e9a869d5c7ce7d9f96b2
128	KE-PRES-2027	PS005	CAND001	2	215	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS005-V2	2026-09-11 18:15:18.031568+07	4	72f971e1a725ba18af880fc117d181a1edf32fd8dda7360f9780b9eca5749cd9
129	KE-PRES-2027	PS005	CAND002	1	140	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS005-V1	2026-09-11 18:15:18.031568+07	4	32a3a84b9c8ea79063571ac65b7f5256a1f1ee279d437d515630abf3fac6800b
130	KE-PRES-2027	PS005	CAND003	1	70	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS005-V1	2026-09-11 18:15:18.031568+07	4	8de9d32feb02f9f9f7c1ac22ba7ead6e57ac0c25ba2b036eade12b24ea0ca157
131	KE-PRES-2027	PS006	CAND001	1	400	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS006-V1	2026-09-11 18:15:18.031568+07	4	94cb23ee5d1b2fe9385a377e54f0c422d0fde55ca2df56869d749221f6c57ac0
132	KE-PRES-2027	PS006	CAND002	1	180	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS006-V1	2026-09-11 18:15:18.031568+07	4	9c35c4e98333c2ed2d5970582abc18befe3f437610bfa4bd7371e15c2939158e
133	KE-PRES-2027	PS006	CAND003	1	100	2026-09-11 18:15:18.031568+07	SEED-RESULT-PS006-V1	2026-09-11 18:15:18.031568+07	4	2ead1c3a555e150944f6c04c61357e73e165ffb37bd1bd45b3007890f2e8543d
\.


--
-- Data for Name: source_comparisons; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.source_comparisons (source_comparison_id, audit_run_id, election_id, published_document_id, derived_source_document_id, aggregation_level, geography_id, candidate_id, metric, published_value, derived_value, difference, status, compared_at) FROM stdin;
\.


--
-- Data for Name: source_documents; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.source_documents (document_id, source_id, document_name, document_type, document_uri, content_hash, retrieved_at, created_at) FROM stdin;
4	SRC-ETVS-SAMPLE	ETVS sample election observations	SEEDED_DATASET	seed.py	1eb21712bc91610305b13d6f597443970fcbefaf38482bdfc7bfae8c9254ed8c	2026-09-11 18:15:18.031568+07	2026-09-11 18:15:18.031568+07
5	SRC-PUBLISHED-AGGREGATES	Published aggregate results comparison	SEEDED_DATASET	seed.py	fa0bd228bc4d78485d1103591aa8a99b5ffe3eb39da49b6cad0dd7627ce42123	2026-09-11 18:15:18.031568+07	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: sources; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.sources (source_id, source_name, source_type, organization_name, description, source_url, created_at) FROM stdin;
SRC-ETVS-SAMPLE	ETVS controlled sample source	OTHER	ETVS project	Controlled provenance source for comparison.	\N	2026-09-11 18:15:18.031568+07
SRC-PUBLISHED-AGGREGATES	Published aggregate comparison source	OTHER	ETVS project	Controlled provenance source for comparison.	\N	2026-09-11 18:15:18.031568+07
\.


--
-- Data for Name: turnout_observations; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.turnout_observations (turnout_observation_id, election_id, polling_station_id, observation_version, voters_turnout, observed_at, source_reference, created_at, source_document_id) FROM stdin;
37	KE-PRES-2027	PS001	1	700	2026-09-11 18:15:18.031568+07	53262fee2c60160a773a9242c676c746c4c630b254562693ea433c351a82f516	2026-09-11 18:15:18.031568+07	4
38	KE-PRES-2027	PS002	1	500	2026-09-11 18:15:18.031568+07	4ff9803bfb82ae580f67bdfd803c07b49e1f0afc42cb5c49f53499ff13b40ab0	2026-09-11 18:15:18.031568+07	4
39	KE-PRES-2027	PS003	1	1000	2026-09-11 18:15:18.031568+07	9e43aa536c9492496cf537998dc5e49ebd7b0cd323eb753ed67ad174e1aec840	2026-09-11 18:15:18.031568+07	4
40	KE-PRES-2027	PS004	1	900	2026-09-11 18:15:18.031568+07	9f31b0615b072d9550811ffe7c581b69673e2849e04518325f0cd8f95317538f	2026-09-11 18:15:18.031568+07	4
41	KE-PRES-2027	PS005	1	450	2026-09-11 18:15:18.031568+07	0d9bb2e5f496a68f09ddd2a4c9e82506ce1ad00741b4e3c9211c79339fe18337	2026-09-11 18:15:18.031568+07	4
42	KE-PRES-2027	PS006	1	650	2026-09-11 18:15:18.031568+07	3a4c6ce8360c5efec0b8620f08fd9d94563695a568c50fd1ced3ffaf37820722	2026-09-11 18:15:18.031568+07	4
\.


--
-- Data for Name: wards; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.wards (ward_id, ward_name, constituency_id, created_at) FROM stdin;
W001	Greenfield Central	CON001	2026-09-11 18:15:18.031568+07
W002	Greenfield East	CON001	2026-09-11 18:15:18.031568+07
W003	Riverdale Central	CON002	2026-09-11 18:15:18.031568+07
W004	Riverdale East	CON002	2026-09-11 18:15:18.031568+07
\.


--
-- Name: audit_failed_results_audit_failed_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.audit_failed_results_audit_failed_id_seq', 1, false);


--
-- Name: audit_findings_audit_finding_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.audit_findings_audit_finding_id_seq', 178, true);


--
-- Name: audit_passed_results_audit_passed_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.audit_passed_results_audit_passed_id_seq', 1, false);


--
-- Name: audit_runs_audit_run_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.audit_runs_audit_run_id_seq', 4, true);


--
-- Name: ballot_accounting_observation_ballot_accounting_observation_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.ballot_accounting_observation_ballot_accounting_observation_seq', 60, true);


--
-- Name: published_aggregate_totals_published_aggregate_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.published_aggregate_totals_published_aggregate_id_seq', 64, true);


--
-- Name: result_submissions_result_submission_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.result_submissions_result_submission_id_seq', 190, true);


--
-- Name: source_comparisons_source_comparison_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.source_comparisons_source_comparison_id_seq', 1, false);


--
-- Name: source_documents_document_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.source_documents_document_id_seq', 11, true);


--
-- Name: turnout_observations_turnout_observation_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.turnout_observations_turnout_observation_id_seq', 60, true);


--
-- Name: audit_failed_results audit_failed_results_audit_finding_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_failed_results
    ADD CONSTRAINT audit_failed_results_audit_finding_id_key UNIQUE (audit_finding_id);


--
-- Name: audit_failed_results audit_failed_results_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_failed_results
    ADD CONSTRAINT audit_failed_results_pkey PRIMARY KEY (audit_failed_id);


--
-- Name: audit_findings audit_findings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT audit_findings_pkey PRIMARY KEY (audit_finding_id);


--
-- Name: audit_passed_results audit_passed_results_audit_finding_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_passed_results
    ADD CONSTRAINT audit_passed_results_audit_finding_id_key UNIQUE (audit_finding_id);


--
-- Name: audit_passed_results audit_passed_results_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_passed_results
    ADD CONSTRAINT audit_passed_results_pkey PRIMARY KEY (audit_passed_id);


--
-- Name: audit_runs audit_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_runs
    ADD CONSTRAINT audit_runs_pkey PRIMARY KEY (audit_run_id);


--
-- Name: ballot_accounting_observations ballot_accounting_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ballot_accounting_observations
    ADD CONSTRAINT ballot_accounting_observations_pkey PRIMARY KEY (ballot_accounting_observation_id);


--
-- Name: candidates candidates_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT candidates_pkey PRIMARY KEY (candidate_id);


--
-- Name: constituencies constituencies_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.constituencies
    ADD CONSTRAINT constituencies_pkey PRIMARY KEY (constituency_id);


--
-- Name: counties counties_county_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.counties
    ADD CONSTRAINT counties_county_name_key UNIQUE (county_name);


--
-- Name: counties counties_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.counties
    ADD CONSTRAINT counties_pkey PRIMARY KEY (county_id);


--
-- Name: elections elections_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.elections
    ADD CONSTRAINT elections_pkey PRIMARY KEY (election_id);


--
-- Name: polling_stations polling_stations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.polling_stations
    ADD CONSTRAINT polling_stations_pkey PRIMARY KEY (polling_station_id);


--
-- Name: published_aggregate_totals published_aggregate_totals_election_id_source_document_id_a_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.published_aggregate_totals
    ADD CONSTRAINT published_aggregate_totals_election_id_source_document_id_a_key UNIQUE NULLS NOT DISTINCT (election_id, source_document_id, aggregation_level, geography_id, candidate_id, metric);


--
-- Name: published_aggregate_totals published_aggregate_totals_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.published_aggregate_totals
    ADD CONSTRAINT published_aggregate_totals_pkey PRIMARY KEY (published_aggregate_id);


--
-- Name: registration_centres registration_centres_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registration_centres
    ADD CONSTRAINT registration_centres_pkey PRIMARY KEY (registration_centre_id);


--
-- Name: result_submissions result_submissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.result_submissions
    ADD CONSTRAINT result_submissions_pkey PRIMARY KEY (result_submission_id);


--
-- Name: source_comparisons source_comparisons_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.source_comparisons
    ADD CONSTRAINT source_comparisons_pkey PRIMARY KEY (source_comparison_id);


--
-- Name: source_documents source_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_pkey PRIMARY KEY (document_id);


--
-- Name: sources sources_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (source_id);


--
-- Name: turnout_observations turnout_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.turnout_observations
    ADD CONSTRAINT turnout_observations_pkey PRIMARY KEY (turnout_observation_id);


--
-- Name: ballot_accounting_observations unique_ballot_observation_version; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ballot_accounting_observations
    ADD CONSTRAINT unique_ballot_observation_version UNIQUE (election_id, polling_station_id, observation_version);


--
-- Name: candidates unique_candidate_election_pair; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT unique_candidate_election_pair UNIQUE (candidate_id, election_id);


--
-- Name: candidates unique_candidate_per_election; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT unique_candidate_per_election UNIQUE (election_id, candidate_name, office);


--
-- Name: constituencies unique_constituency_name_per_county; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.constituencies
    ADD CONSTRAINT unique_constituency_name_per_county UNIQUE (county_id, constituency_name);


--
-- Name: polling_stations unique_polling_station_code_per_election; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.polling_stations
    ADD CONSTRAINT unique_polling_station_code_per_election UNIQUE (election_id, polling_station_code);


--
-- Name: polling_stations unique_polling_station_election_pair; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.polling_stations
    ADD CONSTRAINT unique_polling_station_election_pair UNIQUE (polling_station_id, election_id);


--
-- Name: registration_centres unique_registration_centre_name_per_ward; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registration_centres
    ADD CONSTRAINT unique_registration_centre_name_per_ward UNIQUE (ward_id, registration_centre_name);


--
-- Name: result_submissions unique_result_version; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.result_submissions
    ADD CONSTRAINT unique_result_version UNIQUE (election_id, polling_station_id, candidate_id, result_version);


--
-- Name: source_documents unique_source_document; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT unique_source_document UNIQUE (source_id, document_name, content_hash);


--
-- Name: turnout_observations unique_turnout_observation_version; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.turnout_observations
    ADD CONSTRAINT unique_turnout_observation_version UNIQUE (election_id, polling_station_id, observation_version);


--
-- Name: wards unique_ward_name_per_constituency; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.wards
    ADD CONSTRAINT unique_ward_name_per_constituency UNIQUE (constituency_id, ward_name);


--
-- Name: wards wards_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.wards
    ADD CONSTRAINT wards_pkey PRIMARY KEY (ward_id);


--
-- Name: idx_audit_findings_election; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_findings_election ON public.audit_findings USING btree (election_id);


--
-- Name: idx_audit_findings_run; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_findings_run ON public.audit_findings USING btree (audit_run_id);


--
-- Name: idx_audit_findings_station; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_findings_station ON public.audit_findings USING btree (election_id, polling_station_id);


--
-- Name: idx_audit_runs_election; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_runs_election ON public.audit_runs USING btree (election_id);


--
-- Name: idx_ballot_election_station; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ballot_election_station ON public.ballot_accounting_observations USING btree (election_id, polling_station_id);


--
-- Name: idx_ballot_source_document; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ballot_source_document ON public.ballot_accounting_observations USING btree (source_document_id);


--
-- Name: idx_constituencies_county; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_constituencies_county ON public.constituencies USING btree (county_id);


--
-- Name: idx_polling_stations_election; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_polling_stations_election ON public.polling_stations USING btree (election_id);


--
-- Name: idx_polling_stations_election_centre; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_polling_stations_election_centre ON public.polling_stations USING btree (election_id, registration_centre_id);


--
-- Name: idx_polling_stations_registration_centre; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_polling_stations_registration_centre ON public.polling_stations USING btree (registration_centre_id);


--
-- Name: idx_registration_centres_ward; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_registration_centres_ward ON public.registration_centres USING btree (ward_id);


--
-- Name: idx_results_candidate; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_results_candidate ON public.result_submissions USING btree (candidate_id);


--
-- Name: idx_results_election_station; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_results_election_station ON public.result_submissions USING btree (election_id, polling_station_id);


--
-- Name: idx_results_source_document; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_results_source_document ON public.result_submissions USING btree (source_document_id);


--
-- Name: idx_results_submission_hash; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_results_submission_hash ON public.result_submissions USING btree (submission_hash);


--
-- Name: idx_source_documents_source; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_source_documents_source ON public.source_documents USING btree (source_id);


--
-- Name: idx_turnout_election_station; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_turnout_election_station ON public.turnout_observations USING btree (election_id, polling_station_id);


--
-- Name: idx_turnout_source_document; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_turnout_source_document ON public.turnout_observations USING btree (source_document_id);


--
-- Name: idx_wards_constituency; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_wards_constituency ON public.wards USING btree (constituency_id);


--
-- Name: audit_failed_results audit_failed_results_audit_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_failed_results
    ADD CONSTRAINT audit_failed_results_audit_finding_id_fkey FOREIGN KEY (audit_finding_id) REFERENCES public.audit_findings(audit_finding_id);


--
-- Name: audit_failed_results audit_failed_results_audit_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_failed_results
    ADD CONSTRAINT audit_failed_results_audit_run_id_fkey FOREIGN KEY (audit_run_id) REFERENCES public.audit_runs(audit_run_id);


--
-- Name: audit_failed_results audit_failed_results_election_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_failed_results
    ADD CONSTRAINT audit_failed_results_election_id_fkey FOREIGN KEY (election_id) REFERENCES public.elections(election_id);


--
-- Name: audit_passed_results audit_passed_results_audit_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_passed_results
    ADD CONSTRAINT audit_passed_results_audit_finding_id_fkey FOREIGN KEY (audit_finding_id) REFERENCES public.audit_findings(audit_finding_id);


--
-- Name: audit_passed_results audit_passed_results_audit_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_passed_results
    ADD CONSTRAINT audit_passed_results_audit_run_id_fkey FOREIGN KEY (audit_run_id) REFERENCES public.audit_runs(audit_run_id);


--
-- Name: audit_passed_results audit_passed_results_election_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_passed_results
    ADD CONSTRAINT audit_passed_results_election_id_fkey FOREIGN KEY (election_id) REFERENCES public.elections(election_id);


--
-- Name: audit_runs fk_audit_run_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_runs
    ADD CONSTRAINT fk_audit_run_election FOREIGN KEY (election_id) REFERENCES public.elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ballot_accounting_observations fk_ballot_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ballot_accounting_observations
    ADD CONSTRAINT fk_ballot_election FOREIGN KEY (election_id) REFERENCES public.elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ballot_accounting_observations fk_ballot_source_document; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ballot_accounting_observations
    ADD CONSTRAINT fk_ballot_source_document FOREIGN KEY (source_document_id) REFERENCES public.source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: ballot_accounting_observations fk_ballot_station_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ballot_accounting_observations
    ADD CONSTRAINT fk_ballot_station_election FOREIGN KEY (polling_station_id, election_id) REFERENCES public.polling_stations(polling_station_id, election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: candidates fk_candidate_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT fk_candidate_election FOREIGN KEY (election_id) REFERENCES public.elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: constituencies fk_constituency_county; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.constituencies
    ADD CONSTRAINT fk_constituency_county FOREIGN KEY (county_id) REFERENCES public.counties(county_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: audit_findings fk_finding_audit_run; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT fk_finding_audit_run FOREIGN KEY (audit_run_id) REFERENCES public.audit_runs(audit_run_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: audit_findings fk_finding_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT fk_finding_election FOREIGN KEY (election_id) REFERENCES public.elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: audit_findings fk_finding_station_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT fk_finding_station_election FOREIGN KEY (polling_station_id, election_id) REFERENCES public.polling_stations(polling_station_id, election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: polling_stations fk_polling_station_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.polling_stations
    ADD CONSTRAINT fk_polling_station_election FOREIGN KEY (election_id) REFERENCES public.elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: polling_stations fk_polling_station_registration_centre; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.polling_stations
    ADD CONSTRAINT fk_polling_station_registration_centre FOREIGN KEY (registration_centre_id) REFERENCES public.registration_centres(registration_centre_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: registration_centres fk_registration_centre_ward; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registration_centres
    ADD CONSTRAINT fk_registration_centre_ward FOREIGN KEY (ward_id) REFERENCES public.wards(ward_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: result_submissions fk_result_candidate_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.result_submissions
    ADD CONSTRAINT fk_result_candidate_election FOREIGN KEY (candidate_id, election_id) REFERENCES public.candidates(candidate_id, election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: result_submissions fk_result_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.result_submissions
    ADD CONSTRAINT fk_result_election FOREIGN KEY (election_id) REFERENCES public.elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: result_submissions fk_result_source_document; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.result_submissions
    ADD CONSTRAINT fk_result_source_document FOREIGN KEY (source_document_id) REFERENCES public.source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: result_submissions fk_result_station_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.result_submissions
    ADD CONSTRAINT fk_result_station_election FOREIGN KEY (polling_station_id, election_id) REFERENCES public.polling_stations(polling_station_id, election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: turnout_observations fk_turnout_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.turnout_observations
    ADD CONSTRAINT fk_turnout_election FOREIGN KEY (election_id) REFERENCES public.elections(election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: turnout_observations fk_turnout_source_document; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.turnout_observations
    ADD CONSTRAINT fk_turnout_source_document FOREIGN KEY (source_document_id) REFERENCES public.source_documents(document_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: turnout_observations fk_turnout_station_election; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.turnout_observations
    ADD CONSTRAINT fk_turnout_station_election FOREIGN KEY (polling_station_id, election_id) REFERENCES public.polling_stations(polling_station_id, election_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: wards fk_ward_constituency; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.wards
    ADD CONSTRAINT fk_ward_constituency FOREIGN KEY (constituency_id) REFERENCES public.constituencies(constituency_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: published_aggregate_totals published_aggregate_totals_election_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.published_aggregate_totals
    ADD CONSTRAINT published_aggregate_totals_election_id_fkey FOREIGN KEY (election_id) REFERENCES public.elections(election_id);


--
-- Name: published_aggregate_totals published_aggregate_totals_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.published_aggregate_totals
    ADD CONSTRAINT published_aggregate_totals_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.source_documents(document_id);


--
-- Name: source_comparisons source_comparisons_audit_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.source_comparisons
    ADD CONSTRAINT source_comparisons_audit_run_id_fkey FOREIGN KEY (audit_run_id) REFERENCES public.audit_runs(audit_run_id);


--
-- Name: source_comparisons source_comparisons_derived_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.source_comparisons
    ADD CONSTRAINT source_comparisons_derived_source_document_id_fkey FOREIGN KEY (derived_source_document_id) REFERENCES public.source_documents(document_id);


--
-- Name: source_comparisons source_comparisons_election_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.source_comparisons
    ADD CONSTRAINT source_comparisons_election_id_fkey FOREIGN KEY (election_id) REFERENCES public.elections(election_id);


--
-- Name: source_comparisons source_comparisons_published_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.source_comparisons
    ADD CONSTRAINT source_comparisons_published_document_id_fkey FOREIGN KEY (published_document_id) REFERENCES public.source_documents(document_id);


--
-- Name: source_documents source_documents_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(source_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: postgres
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;


--
-- PostgreSQL database dump complete
--

\unrestrict dPjJKxbdYuNvHoEVTEmj5FC1osUkpLdrQjm10KDLQgE8ENqa64ywyjMSpL2m036

