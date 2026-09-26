# ETVS Repository Structure

The repository is organized by responsibility. The root contains only project-level configuration and navigation.

## Active code

- app/ — runtime audit/application code.
- database/schema/ — database definitions.
- database/migrations/ — ordered migrations.
- database/permissions/ — PostgreSQL roles and grants.
- database/seed/ — controlled seed/import logic.
- tools/ — verification and diagnostics.

## Documentation

- docs/ — design decisions, schema documentation, and implementation notes.
- README.md — project entry point and navigation.

## Backups

backups/2026-09-26-pre-reorganization/ contains copies of the root-level files moved during this reorganization. These copies are archival and are not part of the active execution path.

Database dump files are kept separately under the backup area and must never be treated as application fixtures.

## Compatibility rule

There should be one clearly identified active copy of each operational file.

- database/schema/schema.sql is the active base schema.
- database/schema/schema_v2.sql is the v2 extension/migration while schema-v2 is being reviewed.
- database/permissions/permissions_v2.sql is the active v2 permission definition.
- database/seed/seed.py is the active seed program.
- app/audit_engine.py is the active audit engine.
- tools/verify_project.py is the active project consistency verifier.
- tools/verify_schema_v2.py is the active schema-v2 verifier.

The archival copies under backups/ must not be imported by CI, application code, or deployment scripts.

## Promotion rule

After schema-v2 has been validated against PostgreSQL 18 and the migration path is accepted, the repository should converge on a single canonical schema/deployment path rather than retaining competing current schema files.