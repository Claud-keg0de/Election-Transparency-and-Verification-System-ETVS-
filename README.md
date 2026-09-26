# Election Transparency and Verification System (ETVS)

ETVS is an independent, open-source system for auditing and verifying published election data. It is designed for research, transparency, reproducibility, and controlled evidence validation; it is not an IEBC critical-infrastructure system.

## Repository navigation

| Area | Purpose |
|---|---|
| [app/](app/) | Runtime audit/application code |
| [database/schema/](database/schema/) | Canonical schema and schema-v2 migration |
| [database/migrations/](database/migrations/) | Ordered historical database migrations |
| [database/permissions/](database/permissions/) | PostgreSQL role and privilege definitions |
| [database/seed/](database/seed/) | Controlled sample/reference data seeding |
| [tools/](tools/) | Read-only verification and diagnostic utilities |
| [docs/](docs/) | Design and implementation documentation |
| [backups/](backups/) | Explicitly labelled historical copies and database backups |
| [.github/workflows/](.github/workflows/) | Continuous integration |

## Current database direction

ETVS is being evolved toward an election-specific contest model. election_positions determines which contests apply to an election rather than assuming every election has six contests.

Turnout remains a station-level observation. Contest-specific ballot accounting includes position_id, so multiple applicable contests can be represented independently without duplicating turnout.

Sensitive elector/evidence records are isolated under etvs_private. The evidence model deliberately does not connect an elector to a candidate or vote choice.

## Normal development flow

1. Review the schema and migration documentation.
2. Use PostgreSQL 18 for current development/CI.
3. Apply the base schema, then the applicable migrations.
4. Apply permission definitions as an administrator.
5. Seed only controlled/synthetic development data.
6. Run the verification tools.
7. Run the audit engine and verify its hash chain.
8. Inspect the resulting database in DBeaver.

See docs/schema-v2.md for the current schema-v2 design and deployment sequence.

## Important

Do not place real voter, marked-ballot, or other sensitive electoral evidence in development fixtures. Binary evidence should use controlled encrypted storage and database metadata should retain integrity/provenance information.

backups/ is archival. Active development should use the clearly named files under app/, database/, and tools/.