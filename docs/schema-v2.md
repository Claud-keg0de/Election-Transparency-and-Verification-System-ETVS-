# ETVS Schema V2

## Purpose

Schema V2 extends the existing ETVS database for elector-scoped evidence, six-contest ballot handling, counterfoil evidence, device-aware security validation, and explicit PostgreSQL permission boundaries.

### Contest model

A general election may contain six ordinary contest positions: President, Governor, Senator, Women Representative, Member of Parliament, and Member of County Assembly.

ETVS does not hard-code six artifacts into an elector row. The election_positions table defines which contests actually apply to an election. This supports by-elections and other elections with fewer contests.

### Turnout model

Turnout remains one station-wide voter count. It is not duplicated per contest.

Contest-specific ballot accounting uses (election_id, polling_station_id, position_id, observation_version). This fixes the previous uniqueness conflict that prevented multiple contest records at one polling station/version.

### Elector/evidence separation

Sensitive elector records live under etvs_private.

The preferred identifier is an application-generated/tokenized reference. Where retention of the original elector number is specifically authorized, the encrypted representation is stored as ciphertext and an SHA-256 hash is retained for exact matching.

There is deliberately no candidate_id, vote_choice, result_submission_id, or equivalent choice relationship on the elector evidence path.

Conceptually: Elector -> Contest -> Evidence -> Security Validation, and not Elector -> Candidate/Vote Choice.

### Ballot and counterfoil evidence

elector_ballot_artifacts stores metadata for ballot evidence. Binary images/PDFs should be held in encrypted external storage; PostgreSQL records the immutable storage key, SHA-256 hash, media type, size, version and provenance.

counterfoil_artifacts is separate because a counterfoil is evidence about ballot serial/security handling, not a representation of the voter's candidate choice.

### Device-aware validation

Capabilities include hashing, MIME detection, image quality, OCR, barcode/QR, serial recognition, metadata inspection, visual security inspection and digital-signature verification.

Each validation check records capability, availability, execution status and result. NOT_AVAILABLE is distinct from FAIL.

### Permissions

| Role | Purpose | Core data | Audit output | Sensitive evidence |
|---|---|---|---|---|
| etvs_owner | maintenance/DDL | full ownership | full ownership | full ownership |
| etvs_seed | controlled import/seed | SELECT/INSERT/UPDATE/DELETE | none | none |
| etvs_app | application/audit workflow | SELECT | INSERT only | append + restricted SELECT |
| etvs_reader | reporting/dashboard | SELECT | SELECT | none |

Passwords are intentionally not stored in Git. Configure LOGIN credentials separately.

## Files

- database/schema/schema.sql — active base schema
- database/schema/schema_v2.sql — schema-v2 migration/extension under review
- database/permissions/permissions_v2.sql — role creation, grants/revokes and default privileges
- tools/verify_schema_v2.py — read-only schema contract verification
- database/seed/seed.py — aligned with election-specific contest configuration and contest-specific ballot accounting

## Deployment order

1. Apply the active base schema.
2. Apply the ordered migrations required by the database state.
3. Apply database/schema/schema_v2.sql while v2 is under review.
4. Apply database/permissions/permissions_v2.sql as PostgreSQL administrator.
5. Run tools/verify_schema_v2.py.
6. Run the normal seed/check workflow.
7. Review DBeaver's public and etvs_private schemas and confirm role-specific visibility.

Do not upload real voter or ballot evidence into development/test data without appropriate authorization. Use synthetic evidence while validating the implementation.