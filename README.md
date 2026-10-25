# Election Transparency and Verification System (ETVS)

**ETVS — Verified Turnout** is a database-first, open-source project for independently auditing published election information in Kenya. It is designed to make checks reproducible and explainable: retain the source evidence, validate the reported figures, record discrepancies and show the results at polling-station and higher geographic levels.

ETVS is an independent audit and research tool. It is **not an IEBC system**, does not modify the IEBC's published records, and does not determine electoral fraud from a mathematical discrepancy alone.

## Project goals

- **Transparency:** make the source document and the values derived from it traceable.
- **Compliance and policy checks:** apply explicit, versioned rules and retain the outcome of each check.
- **Reconciliation:** compare figures across source documents and geographic aggregation levels without silently choosing one conflicting value.
- **Auditability:** preserve source observations separately from audit outputs and use BLAKE3-256 fingerprints and a hash chain for supported records.
- **Public understanding:** expose clear, evidence-linked findings and coverage metrics, with a planned GIS layer for geographic exploration.

## Current architecture

The current implementation uses PostgreSQL as the authoritative data store. The canonical schema is `schema.sql`; numbered SQL files in `migrations/` evolve the database contract.

```text
web/input_app.py
      |
      v
PostgreSQL source and observation tables
      |
      v
audit_engine.py ----> audit_runs / audit_findings
      |                         |
      v                         v
verification tools        public reporting (planned)
```

The local form-driven source-entry workflow includes the following input forms:

1. Polling-station details, including the election, geography, station code, registered-voter reference and ETVS reporting interval.
2. Independent, versioned turnout observations for each polling-station/electoral-position pair (President, Governor, Senator, Woman Representative, MP and MCA).
3. Candidate results for a selected electoral position/contest.
4. Contest-specific candidate results for the selected position.
5. Contest-specific ballot accounting, including valid, rejected and spoilt ballot counts.

The structured results/accounting contract for each selected station and electoral position is:

- `valid_votes = SUM(candidate votes)` for the contest.
- `voters_turnout = valid_votes + rejected_votes`.
- Spoilt ballots are stored separately and do not count as votes cast.
- Turnout is entered independently for each station/position stream; ETVS never copies the President's figure into another contest.

This is the **current application contract**, not a claim that every official election form contains all of these fields. Form 34A has its own printed counts and disputed-vote decision section, captured by the dedicated Form 34A evidence form and stored separately from normalized contest inputs.

## Form 34A source capture versus nationwide import

The local application supports Form 34A PDF/image upload and manual transcription/review at `/form34a`. Nationwide retrieval, OCR/automatic extraction, and ingestion of the corresponding official forms for the other five positions are separate future workflows.

The current schema already provides reusable building blocks:

- `sources` and `source_documents` for provenance and document fingerprints;
- `source_submissions` and `submission_validation_results` for generic published-source payloads and validation;
- `registered_voter_observations`, `turnout_observations`, `ballot_accounting_observations` and `result_submissions` for structured observations;
- `published_aggregate_totals` and `source_comparisons` for published totals and cross-source comparisons;
- `audit_runs` and `audit_findings` for reproducible audit output, including hash-chained findings.

Form 34A extraction/review tables, manual source upload/transcription, and individual disputed-vote decision capture are implemented in the current schema/UI. Nationwide automated PDF extraction, automatic mapping into normalized contest observations, and a PostGIS-backed map remain future work; see [the Form 34A evidence and reconciliation guide](docs/form34a-evidence-and-reconciliation.md).

## Architecture and data integrity principles

1. **Preserve the source.** Keep the original document bytes, source URL/URI, retrieval time and BLAKE3-256 hash. A hash detects byte-level changes; it does not by itself prove that a source was authentic when first obtained.
2. **Keep evidence separate from conclusions.** Extraction must not overwrite official source records. Audit runs consume observations and write findings.
3. **Version corrections.** If a document copy, transcription or source value changes, retain the earlier evidence and identify the new version or reconciliation decision.
4. **Do not turn missing data into zero.** A blank, illegible, unreviewed or unavailable field is not the same thing as a confirmed zero.
5. **Explain every finding.** Record the applicable rule, observed and comparison values, source references and a human-readable explanation.
6. **Do not equate a failed check with fraud.** Report a rule violation or unresolved discrepancy; interpreting its legal or electoral significance requires the evidence and applicable process.
7. **Keep reference geography honest.** The six ETVS regions are an operational grouping, not a constitutional tier. The hierarchy is County → Constituency → Ward → Registration Centre → Polling Station, with the operational region used as classification metadata.

## Kenya reference geography

The reference-data workflow targets 47 counties, 290 constituencies and 1,450 County Assembly Wards. See [Kenya geography and input contract](docs/kenya-geography-and-input-contract.md) for provenance and loader details. Confirm the source, retrieval date and data quality before publishing a real-election coverage claim. Do not hard-code a national polling-station count; obtain the station inventory for the specific election.

## Technical baseline

- **Database:** PostgreSQL 18 (canonical schema and migration workflow)
- **Application:** Python, including the form-driven application under `web/`
- **Audit engine:** `audit_engine.py`
- **Integrity fingerprints:** BLAKE3-256 for supported document/result/input fingerprints and audit hash-chain entries
- **Database verification:** `verify_project.py`
- **Reference loading and development support:** `seed.py` and tools under `tools/`

The seed script is a deterministic development/test fixture, not the normal source-entry interface. See [PostgreSQL 18 finalization](docs/postgresql18-finalization.md) before rebuilding a development database and [the form-driven PostgreSQL workflow](docs/form-driven-postgresql-workflow.md) for the normal input path.

## Suggested local workflow

1. Review `schema.sql` and applicable migrations before changing the data contract.
2. Configure `ETVS_DB_HOST`, `ETVS_DB_PORT`, `ETVS_DB_NAME`, `ETVS_DB_USER` and `ETVS_DB_PASSWORD` for the intended PostgreSQL instance.
3. Run the repository's database connection checker and `verify_project.py` against the intended database.
4. Use `web/input_app.py` for normal source entry; use `seed.py` only for controlled development/test fixtures.
5. Run `audit_engine.py` and its hash-chain verification mode, then inspect findings and resolve data/source conflicts explicitly.

For exact commands and port details, follow the documentation for the target environment rather than assuming that every developer has the same local PostgreSQL port mapping.

## Documentation

- [Form 34A evidence model, ballot semantics and reconciliation](docs/form34a-evidence-and-reconciliation.md)
- [Form-driven PostgreSQL input workflow](docs/form-driven-postgresql-workflow.md)
- [Kenya geography and input contract](docs/kenya-geography-and-input-contract.md)
- [PostgreSQL 18 finalization](docs/postgresql18-finalization.md)
- [Cross-file consistency notes](CONSISTENCY_NOTES.txt)

## Scope and limitations

ETVS is intended for independent analysis of published data and documented observations. It should not access or interfere with IEBC production infrastructure, alter official election records, or present an automated anomaly as a definitive finding of fraud. A public dashboard should identify the source and retrieval context, distinguish missing evidence from failed checks, and show the specific rule behind every status.
