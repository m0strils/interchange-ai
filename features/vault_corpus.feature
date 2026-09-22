Feature: Vault corpus ingestion — nested Markdown folders as a read-only corpus
  As an operator of Interchange
  I want a whole folder tree of notes to be ingestible as a corpus
  So that a real Markdown vault — nested folders, duplicate filenames, editor
     housekeeping directories — can be indexed without hand-curating a flat
     directory, and without ever indexing a secret.

  # Offline discipline (ADR-0006 gate, ADR-0007 contract): these scenarios exercise
  # ONLY the pure discovery/ignore/source functions over throwaway tmp trees and the
  # real docs/ folder. Chroma, embeddings and the network are never touched — the
  # fused retrieve() and build_index() stay out of the gate, as in hybrid_retrieval.
  Scenario: Notes in nested folders are discovered with a folder-relative source
    Given a vault with "Projects/Rail/interchange.md" and "Inbox/quick.md"
    When I discover the vault's indexable files
    Then the discovered sources are "Inbox/quick.md, Projects/Rail/interchange.md"

  Scenario: Obsidian housekeeping folders are never indexed
    Given a vault with "Notes/real.md", "Notes/.obsidian/plugins/cfg.md", ".trash/deleted.md" and "_attachments/scan.md"
    When I discover the vault's indexable files
    Then the discovered sources are "Notes/real.md"

  Scenario: A path listed in .interchangeignore is skipped
    Given a vault with "Keep/keep.md" and "Meta/skip.md"
    And the vault's ignore file lists "Meta/"
    When I discover the vault's indexable files
    Then the discovered sources are "Keep/keep.md"

  Scenario: Two notes sharing a filename get distinct sources
    Given a vault with "Projects/Index.md" and "Personal/Index.md"
    When I discover the vault's indexable files
    Then the discovered sources are "Personal/Index.md, Projects/Index.md"
    And every discovered source is unique

  Scenario: The seed corpus discovers exactly the same three files as before
    Given the real seed docs directory
    When I discover the vault's indexable files
    Then the discovered sources are "a2a-RESULT.md, rail-edi-notes.md, x12-overview.md"

  Scenario: A note containing a credential pattern is flagged by the guard
    Given a note whose body is "GEMINI_API_KEY=AIzaSyD1a2b3c4d5e6f7g8h9i0jklmn"
    Then the credential guard flags the note

  Scenario: A note that only talks about tokens is not flagged
    Given a note whose body is "We kept the token budget under 4000 tokens."
    Then the credential guard does not flag the note

  Scenario: A placeholder credential in a code sample does not trip the guard
    Given a note whose body is "apiKey: process.env.OPENAI_API_KEY"
    Then the credential guard does not flag the note

  # --- wikilink graph (ADR-0014 slice 4): parse + resolve + link expansion ---
  Scenario: An aliased wikilink resolves to the note's relative path
    Given a vault with "Projects/Rail/Index.md" and "Projects/Rail/Spec.md"
    When I resolve the wikilink "[[Spec|the spec]]" from "Projects/Rail/Index.md"
    Then the wikilink resolves to "Projects/Rail/Spec.md"

  Scenario: A bare-title wikilink resolves to the shortest matching path
    Given a vault with "z/Index.md", "01-PROJECTS/deep/Index.md" and "a/b/Index.md"
    When I resolve the wikilink "[[Index]]" from "somewhere/note.md"
    Then the wikilink resolves to "z/Index.md"

  Scenario: An unresolvable wikilink is dropped, not guessed
    Given a vault with "Notes/Real.md"
    When I resolve the wikilink "[[Ghost Note]]" from "Notes/Real.md"
    Then the wikilink does not resolve

  Scenario: Link expansion adds the one-hop neighbours of the top fused notes as candidates
    Given a fused ranking of notes "A, B" whose links are "A->N1, B->N2"
    When I expand the ranking along its links
    Then the link candidates are "N1, N2"

  Scenario: With no links present, hybrid+links ranks identically to hybrid
    Given a dense ranking "a, b, c" and a bm25 ranking "b, c, d"
    When I fuse them with no link ranking
    Then hybrid+links ranks identically to hybrid
