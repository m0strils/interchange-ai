Feature: Hybrid retrieval surfaces exact EDI codes
  As an operator of Interchange
  I want an exact EDI transaction-set code to retrieve its own defining document
  So that the lexical (BM25) half of hybrid retrieval catches the precise matches
     that dense embeddings blur — "214" and "417" are near-identical vectors, but
     lexically they are unmistakable.

  # The BM25 win: a 3-digit code that appears in exactly ONE doc must rank a chunk
  # from that doc first. Dense similarity treats these short numeric tokens as
  # interchangeable; BM25 does not. This scenario asserts the BM25 component alone
  # (the mechanism of the win), so it runs offline and free — no embeddings.
  Scenario Outline: An exact code unique to one doc ranks that doc's chunk first
    Given the real corpus chunked with its source filenames
    When I BM25-search for the exact code "<code>"
    Then the top-ranked chunk comes from "<source>"

    Examples:
      | code | source            |
      | 997  | x12-overview.md   |
      | 214  | x12-overview.md   |
      | 161  | rail-edi-notes.md |
      | 417  | rail-edi-notes.md |
