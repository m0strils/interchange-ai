Feature: Lead-chunk merge at ingest (ADR-0017, Slice 3 step 2)
  As the author of a governed knowledge runtime
  I want a note's frontmatter and title chunks folded into its first body section at
     ingest, when they are small enough
  So that the topic-token-dense lead chunks travel WITH the first real section instead
     of outranking it, and passage-level retrieval improves — measured, not assumed.

  # merge_lead_chunks is pure: it consumes mark_lead() output and returns new dicts.
  # build_index composes merge_lead_chunks(mark_lead(chunk(text))). Scenarios that
  # touch build_index stub Chroma with a recording client (offline, ADR-0006).

  Scenario: Frontmatter and the H1 intro merge into the first body section
    Given a frontmatter note with a short H1 intro and an H2 body
    When I merge the lead chunks
    Then the merge yields 1 chunk
    And chunk 1 has section "Body" level 2 lead false merged_lead true
    And chunk 1's text contains in order "type: note", "# A Heading", "the real body"

  Scenario: A lead run over the limit is left alone
    Given a frontmatter note whose H1 intro is 700 characters
    When I merge the lead chunks
    Then no chunk was merged
    And the chunk count is unchanged
    And the lead flags are preserved

  Scenario: A title-only note stays one chunk
    Given a title-only note
    When I merge the lead chunks
    Then the merge yields 1 chunk
    And no chunk was merged

  Scenario: A preamble-only document is untouched
    Given a preamble-only document with no headings
    When I merge the lead chunks
    Then the merge yields 1 chunk
    And no chunk was merged

  Scenario: The merged chunk is not counted by lead_share
    Given a frontmatter note with a short H1 intro and an H2 body
    When I merge the lead chunks
    And the merged chunk and a genuine preamble hit are the top 2 results
    Then the lead share at k 2 is "0.50"

  Scenario: Chunk ids stay contiguous after a merge
    Given a merging two-body corpus and a recording Chroma client
    When I build the index
    Then the chunk ids are "note.md:0,note.md:1"
    And the first recorded chunk has merged_lead true

  Scenario: The indexing summary reports merged lead chunks
    Given a merging two-body corpus and a recording Chroma client
    When I build the index
    Then the summary reports merged lead chunks
