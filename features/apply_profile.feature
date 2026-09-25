Feature: A corpus profile is applied in-process (ADR-0016 slice 2)
  As an operator running Interchange over more than one corpus
  I want --profile to select the collection, docs dir, golden set, retrieval
     default and tools before any work, and the index location to be an env var
  So that one process serves any corpus without the export-before-.env dance.

  # Offline discipline (ADR-0006): the pure config helper, the in-process
  # profile application, and a build_index over a two-note tmp corpus against a
  # recording stub Chroma client. No Chroma on disk, no embeddings, no network.
  #
  # These scenarios live here rather than in corpus_profiles.feature on purpose:
  # tests/test_corpus_profiles.py binds that feature with the bulk `scenarios()`
  # call, which would also bind anything appended there and fail for want of the
  # step definitions (pytest-bdd resolves steps per module).

  Scenario: The index directory is configurable and defaults to the repo's .chroma
    Then chroma_dir_from_env with no override ends with the repo's ".chroma"
    And chroma_dir_from_env honours an expanded INTERCHANGE_CHROMA_DIR
    And the module CHROMA_DIR equals chroma_dir_from_env of the environment

  Scenario: --profile selects corpus, collection and golden set for one process
    Given an overlay defining a "journal" profile with golden "~/g/j.jsonl"
    When I apply the "hotel" profile
    Then interchange DOCS_DIR ends with "hotel-demo"
    And interchange COLLECTION is "hotel"
    And active_collection is "hotel"
    And os.environ INTERCHANGE_COLLECTION is "hotel"
    And os.environ DEMO_PROFILE is "hotel"
    And PROFILE_TOOLS is "search_docs"
    And PROFILE_RETRIEVAL mode is "hybrid"
    When I apply the "journal" profile
    Then GOLDEN_PATH is the expanded journal golden
    When I apply the "rail" profile
    Then GOLDEN_PATH is the repo's "eval/golden.jsonl"

  Scenario: The indexing summary reports elapsed seconds and clears the snapshot cache
    Given a temporary corpus of two notes and a recording Chroma client
    And the snapshot cache holds a sentinel for the active collection
    When I build the index
    Then the summary reports two chunks and elapsed seconds
    And the snapshot cache no longer holds the active collection
