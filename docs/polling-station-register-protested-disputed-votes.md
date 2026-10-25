# Polling-station register: protested and disputed votes

ETVS uses a normalized polling-station register and generic source-document provenance; it does not provide a dedicated Form 34A upload, transcription or review workflow.

For each station and electoral position, record each candidate's **total votes**, including any disputed votes assigned to that candidate. Record **disputed votes assigned to a candidate** as a subset of that candidate's total. They are counted as that candidate's votes and therefore included in valid votes; do not add them a second time. At contest level, **unresolved protested votes** are recorded separately. Once disputed votes are assigned to a candidate, they belong in that candidate's total rather than the unresolved protested count.

The register reconciliation is:

`voters_turnout = valid_votes + rejected_votes + unresolved_protested_votes`

Spoilt ballots remain separate and are not counted as votes cast. For each candidate, assigned disputed votes must not exceed that candidate's total votes. Candidate totals include the assigned disputed votes. The unresolved protested-vote count includes only protested votes not yet assigned to a candidate. Generic `sources` and `source_documents` remain available for provenance without a Form 34A-specific workflow.

Migration `010_remove_form34a_add_protested_disputed_votes.sql` drops the legacy Form 34A-specific tables and adds the two register fields and constrains each candidate's disputed count to be no greater than that candidate's total votes. Back up any legacy Form 34A records before applying it if they must be retained.
