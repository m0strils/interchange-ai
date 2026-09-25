Feature: Corpus profiles as portable data — a personal overlay extends the committed set
  As an operator running Interchange over my own corpora
  I want a private profiles overlay outside the repo
  So that I can point a profile at my own notes, add whole new profiles, and
     tune retrieval / persona / tools without editing (or ever publishing) the
     committed profiles.yaml.

  # Offline discipline (ADR-0006): every scenario works over throwaway overlay
  # files under tmp_path with INTERCHANGE_PROFILES monkeypatched, or the committed
  # profiles read raw. No Chroma, no network — only the pure profile functions.

  Scenario: A personal overlay extends a committed profile without touching the tree
    Given an overlay that sets vault docs_dir to "/tmp/my-notes"
    And INTERCHANGE_VAULT_DIR is unset
    When I load the "vault" profile
    Then the profile's docs_dir is "/tmp/my-notes"
    And the profile's collection is "vault"
    And the committed profiles.yaml is byte-for-byte unchanged

  Scenario: An overlay may add a whole new profile
    Given an overlay that defines a "journal" profile with collection "journal" and docs_dir "/tmp/j"
    When I load the "journal" profile
    Then the profile's collection is "journal"
    And the profile's exported env has INTERCHANGE_COLLECTION "journal"

  Scenario: Lists replace rather than concatenate
    Given an overlay that sets vault ignore to "x/"
    And INTERCHANGE_VAULT_DIR is set to "/tmp/v"
    When I load the "vault" profile
    Then the profile's ignore list is exactly "x/"

  Scenario: With the overlay disabled and no vault dir, the vault profile still fails plainly
    Given the overlay is disabled
    And INTERCHANGE_VAULT_DIR is unset
    When I try to load the "vault" profile
    Then it exits plainly naming "INTERCHANGE_VAULT_DIR"

  Scenario: A missing overlay file is not an error
    Given INTERCHANGE_PROFILES points at a nonexistent path
    When I load the "rail" profile
    Then the profile's collection is "edi"

  Scenario: A profile is found by its collection
    Given the overlay is disabled
    Then the profile for collection "hotel" is named "hotel"
    And there is no profile for collection "nope"

  Scenario: Tool sets default to the rail tools unless a profile narrows them
    Given the overlay is disabled
    Then the "rail" profile's tools are "search_docs, lookup_segment"
    And the "vault" profile's tools are "search_docs"

  Scenario: Retrieval defaults to hybrid and validates the mode
    Given the overlay is disabled
    Then the "rail" profile's retrieval is mode "hybrid" rerank none
    And the "vault" profile's retrieval mode is "hybrid+rerank"

  Scenario: An overlay profile with a bogus retrieval mode is rejected
    Given an overlay that defines a "bad" profile with collection "bad", docs_dir "/tmp/b" and retrieval mode "bogus"
    When I read the retrieval of the "bad" profile
    Then a ValueError names "bogus"

  Scenario: A profile persona is exposed when present and absent for rail
    Given the overlay is disabled
    Then the "hotel" profile persona mentions "Demo Hotel"
    And the "rail" profile has no persona
