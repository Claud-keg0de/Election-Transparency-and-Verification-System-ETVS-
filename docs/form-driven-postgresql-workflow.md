# ETVS form-driven PostgreSQL workflow

## Source entry

Normal human source entry is performed through `web/input_app.py`. `seed.py`
is retained only as a deterministic development/test fixture and is not the
normal source-entry mechanism.

The local source-entry workflow has five input areas:

1. **Polling-station details** — election, reference ward, station ID/code,
   registration-centre name, registered voters and the ETVS turnout interval.
2. **Turnout / voters cast by position** — a separate, versioned observation for
   each polling station and each of the six positions (President, Governor,
   Senator, Woman Representative, MP and MCA). The reporting interval applies
   independently to each station/position stream.
3. **Form 34A evidence** — upload the original presidential polling-station PDF/image
   and manually transcribe its printed fields, candidate rows and disputed-vote
   decision details. This preserves source evidence separately from contest inputs.
4. **Contest results** — candidate votes for the selected station and position.
5. **Ballot accounting** — rejected and spoilt ballots for that contest; ETVS
   derives valid votes from the candidate totals.

### Current application accounting identity

For every station and contest in this current manual-input workflow:

```text
valid votes = SUM(candidate votes)
turnout = valid votes + rejected ballots
```

Spoilt ballots are stored separately and are **never treated as votes cast**.

Turnout is not shared across the six contests. Each station/position has its own versioned observation, and contest accounting must reference the latest turnout for that same position.

This is the current ETVS application/input contract. Do not assume that every
field is printed on every statutory election form.

## Form 34A evidence capture and remaining import work

The `/form34a` input form accepts an original PDF or image and a manual, reviewable
transcription of the presidential polling-station return. ETVS retains the original
file locally, records a BLAKE3-256 content hash and source-document provenance,
and stores the extraction in dedicated relational tables with explicit capture
states and reviewer history. It does not silently copy the transcription into
normalized contest results. Automated nationwide retrieval, OCR, automated field
extraction and ingestion of official documents for the other five positions remain
future work.

See [Form 34A evidence model and reconciliation design](form34a-evidence-and-reconciliation.md)
for the prescribed fields, vote-count semantics, source reconciliation and remaining work.

The source-specific distinctions matter:

- Form 34A separately reports candidate votes, total valid votes, registered
  voters, rejected ballots, rejection-objected-to ballots and disputed votes,
  and can list disputed ballot serial numbers and their assigned candidates.
- The rejection-objected-to count must not be added a second time to rejected
  ballots when calculating votes cast. A rejection that is objected to remains
  rejected for the polling-station declaration under the applicable regulation.
- Disputed ballots counted by the presiding officer are treated as valid for
  the station declaration. Their count is not an additional vote pool to add
  on top of candidate totals.
- The Form 34A polling-station counts block does not contain a distinct
  spoilt-ballot field. Do not claim a spoilt count was extracted from this form.
- A blank or illegible printed value is not a numeric zero. A published source
  observation must not silently overwrite a separate turnout observation
  obtained through the manual input workflow.

The importer should preserve the source and extract into source-specific
observations first. A reviewed mapping into existing normalized tables must be
implemented and tested before the importer is allowed to populate the same
tables as human-entered observations.

## Turnout interval

Each polling station has `turnout_reporting_interval_minutes`. Successive observations
are checked independently within each station/position stream in PostgreSQL and
in the input form workflow.

This interval is an **ETVS collection/audit policy**. It should not be described
as a universal IEBC reporting requirement unless an authoritative source
establishes one.

## Database connection

The application reads:

- `ETVS_DB_HOST`
- `ETVS_DB_PORT`
- `ETVS_DB_NAME`
- `ETVS_DB_USER`
- `ETVS_DB_PASSWORD`

Inside the Debian VM, PostgreSQL normally listens on 5432. From the Windows host
through the existing VirtualBox NAT forwarding, the DBeaver connection uses
`127.0.0.1:5433` for the guest PostgreSQL port 5432.

Run:

```bash
python tools/check_db_connection.py
```

A successful check reports **STATUS: CONNECTED** and the number of geography,
station, turnout, result and accounting records.

## DBeaver

After the PostgreSQL schema and migrations have been applied to the target ETVS
database, create/open a DBeaver PostgreSQL connection using the same host, port,
database and user values. Refresh the connection and expand:

**Schemas -> public -> Tables**

The authoritative data remains PostgreSQL data. DBeaver is a database client,
not a second data store.

The expected workflow is:

**GitHub branch -> migration/schema review -> PostgreSQL -> form input ->
PostgreSQL records -> DBeaver visibility -> audit engine**

No source-entry data should be inserted into `seed.py` merely to make it appear
in DBeaver.

## Cross-file consistency checks

The result-entry form and `audit_engine.py` use the same canonical BLAKE3-256
result fingerprint payload:

```text
RESULT | election_id | polling_station_id | candidate_id | result_version | votes
```

This is what audit rule R010 verifies.

The polling-station form reuses an existing registration centre when the same
ward and registration-centre name are selected. This preserves the schema
relationship where one registration centre can contain multiple polling
stations.

For the complete reference-data validation, run:

```bash
python verify_project.py KE-PRES-2027 --strict-reference-data
```

Run this after loading the 47/290/1450 geography and the prison/diaspora
reference migration.
