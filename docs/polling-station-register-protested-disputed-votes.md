# Polling-station register: protested and disputed votes

ETVS uses a normalized polling-station register and generic source-document provenance; it does not provide a dedicated Form 34A upload, transcription or review workflow.

For each station and electoral position, record candidate **valid votes** and **disputed votes assigned to that candidate** separately. At contest level, record **protested votes** separately from valid and rejected votes. Protested votes are excluded from valid votes. Assigning disputed votes to a candidate records the attribution only; it does not automatically reclassify those votes as valid or add them to the valid-vote total.

The register reconciliation is:

`voters_turnout = valid_votes + rejected_votes + protested_votes`

Spoilt ballots remain separate and are not counted as votes cast. The sum of candidate-assigned disputed votes must not exceed the protested-vote count. Generic `sources` and `source_documents` remain available for provenance without a Form 34A-specific workflow.

Migration `010_remove_form34a_add_protested_disputed_votes.sql` drops the legacy Form 34A-specific tables and adds the two register fields. Back up any legacy Form 34A records before applying it if they must be retained.
