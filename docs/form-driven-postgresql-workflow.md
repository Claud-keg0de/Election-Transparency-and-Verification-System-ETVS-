# ETVS form-driven PostgreSQL workflow

## Source entry

Normal human source entry is performed through `web/input_app.py`. `seed.py`
is retained only as a deterministic development/test fixture and is not the
normal source-entry mechanism.

The four permitted input areas are:

1. **Polling-station details** — election, reference ward, station ID/code,
   registration-centre name, registered voters and the ETVS turnout interval.
2. **Turnout / voters cast** — one station-wide observation at each configured
   interval.
3. **Contest results** — candidate votes for one contest.
4. **Ballot accounting** — rejected and spoilt ballots for that contest; ETVS
   derives valid votes from the candidate totals.

### Accounting identity

For every station and contest:

`valid votes = SUM(candidate votes)`

`turnout = valid votes + rejected ballots`

Spoilt ballots are stored separately and are **never treated as votes cast**.

Turnout is shared by the station's six contests; it is not entered six times.

## Turnout interval

Each polling station has `turnout_reporting_interval_minutes`. Migration 006
enforces the minimum elapsed time between successive turnout observations in
PostgreSQL as well as in the form workflow.

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

`python tools/check_db_connection.py`

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

The result-entry form and `audit_engine.py` use the same canonical BLAKE3-256 result fingerprint payload: `RESULT | election_id | polling_station_id | candidate_id | result_version | votes`. This is what audit rule R010 verifies.

The polling-station form reuses an existing registration centre when the same ward and registration-centre name are selected. This preserves the schema relationship where one registration centre can contain multiple polling stations.

For the complete reference-data validation, run `python verify_project.py KE-PRES-2027 --strict-reference-data` after loading the 47/290/1450 geography and the prison/diaspora reference migration.
