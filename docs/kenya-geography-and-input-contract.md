# Kenya geography and input contract

## Geography

ETVS keeps the constitutional/electoral hierarchy:

**Region classification metadata -> County -> Constituency -> Ward -> Registration Centre -> Election-specific Polling Station**

Kenya currently has **47 counties, 290 constituencies and 1,450 County Assembly Wards**. The six region labels in `etvs_regions` are an ETVS operational classification so the system can display six requested regions without incorrectly treating them as a constitutional tier.

The loader derives the 290 constituencies from the complete ward dataset. Ward records retain their published ward codes.

## Six ETVS regions

The six labels are:

1. Coastal Region
2. South Eastern Region
3. Mt Kenya Region
4. Northern Region
5. North Rift Valley Region
6. Western Region

Because regional classifications are used differently by different Kenyan institutions and publications, the ETVS region field is explicitly marked `ETVS_OPERATIONAL`. It must not be presented as a replacement for counties or as an official IEBC constitutional boundary level.

## Reference-data loader

`tools/load_kenya_geography.py` imports the complete CitizenGuide ward export:

`https://www.citizenguide.ke/api/data/exports/wards?format=json`

It creates/updates:

- 47 counties
- 290 constituencies
- 1,450 wards

The loader refuses to finish unless the final counts are exactly 47/290/1,450. It can also consume a downloaded JSON file with `--input`, which is useful for reproducible/offline seeding.

The dataset is described by CitizenGuide as a compilation of public information with IEBC public materials as the original publisher; it is not itself an official Government of Kenya statistical release. Keep the source URL and retrieval time in the ETVS provenance layer.

## Input scope for this phase

Only these are enabled as source-entry areas:

- polling-station details
- turnout/voters-cast observations
- candidate results
- ballot accounting

Everything else is reference data or derived output for now.

### Turnout

`turnout_observations.voters_turnout` is a **variable observed input**. ETVS must never calculate turnout merely as a percentage or substitute registered voters for votes cast.

The audit engine checks:

`0 <= voters_turnout <= registered_voters`

and then uses the same station turnout observation when checking contest-level ballot accounting. This prevents the six contests from being treated as six separate electorates.

## BLAKE3

All new ETVS cryptographic fingerprints use **BLAKE3-256**:

- source-document fingerprints
- result-submission fingerprints
- audit hash-chain entries

The hexadecimal representation remains 64 characters, so the database storage shape remains compatible while the algorithm changes from SHA-256 to BLAKE3.

BLAKE3 is a cryptographic hash function with a default 256-bit output. It is not a password-hashing/KDF algorithm; ETVS uses it for integrity/fingerprinting and tamper-evident chaining, not password storage.

Install the Python dependency with the project requirements before running the seed/audit tools.
