"""Pytest unit tests for document ingestion — PDF via pypdf (ADR-0010).

Mirrors test_retrieval.py discipline: import each symbol *inside* the test that
needs it, no embeddings, no Chroma index build. The boundary under test
(``_extract_pdf``) is patched for the routing test rather than shelled out to a
real PDF; a small real fixture (``tests/fixtures/sample.pdf``) is used for one
smoke test to prove pypdf extraction actually works, offline and $0.
"""
from __future__ import annotations

from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
X12 = DOCS / "x12-overview.md"


# --- _read_document: suffix routing (contract "_read_document") -----------
def test_read_document_routes_pdf_suffix_to_extract_pdf(monkeypatch):
    """A .pdf path is routed to _extract_pdf, not read as plain text."""
    import interchange

    monkeypatch.setattr(interchange, "_extract_pdf", lambda p: "canned 824 text")

    assert interchange._read_document("anything.pdf") == "canned 824 text"


def test_read_document_routes_non_pdf_to_plain_text_read(monkeypatch):
    """A real .md path is read as plain UTF-8 text (unchanged pre-ADR-0010 behavior)."""
    import interchange

    monkeypatch.setattr(interchange, "_extract_pdf", lambda p: "canned 824 text")

    assert X12.exists(), "expected the real seed doc docs/x12-overview.md to exist"
    result = interchange._read_document(str(X12))

    assert result == X12.read_text(encoding="utf-8")


# --- _extract_pdf: real extraction smoke test (contract "_extract_pdf") ---
def test_extract_pdf_real_fixture_yields_nonempty_text_with_997():
    """pypdf extracts real, non-empty text from the committed fixture PDF,
    containing '997' (the fixture was generated from an X12 snippet mentioning
    the 997 Functional Acknowledgment). Offline: no network, no API calls."""
    from interchange import _extract_pdf

    sample = FIXTURES / "sample.pdf"
    assert sample.exists(), f"expected committed fixture at {sample}"

    text = _extract_pdf(str(sample))

    assert text.strip(), "expected non-empty extracted text"
    assert "997" in text


# --- empty-PDF guard (contract: whitespace-only extraction) ---------------
def test_read_document_yields_empty_for_scanned_pdf(monkeypatch):
    """A scanned/image-only PDF (no OCR in pypdf) extracts to "" — _read_document
    passes that empty string through unchanged. build_index()'s WARN+skip branch
    acts on exactly this signal (whitespace-only text)."""
    import interchange

    monkeypatch.setattr(interchange, "_extract_pdf", lambda p: "")

    result = interchange._read_document("scanned.pdf")

    assert result == ""
    assert not result.strip()


# --- is_ignored: gitignore-lite matching (contract "is_ignored") ----------
def test_is_ignored_any_dot_segment():
    """Rule 1: ANY path segment starting with "." is ignored — at the root, at
    depth, and for the file itself. One rule covers a nested .obsidian/, .git/,
    .trash/ and stray .DS_Store without needing a pattern for each."""
    from interchange import is_ignored

    assert is_ignored(".obsidian/workspace.md", []) is True
    assert is_ignored("Projects/Rail/.obsidian/plugins/x.md", []) is True
    assert is_ignored("Projects/.DS_Store", []) is True
    assert is_ignored(".DS_Store", []) is True
    assert is_ignored("Projects/Rail/notes.md", []) is False


def test_is_ignored_directory_pattern_matches_nested_segment():
    """Rule 2 (bare directory name): a pattern like "_attachments/" matches that
    directory at ANY depth — but only as a directory segment, never as the file
    itself (a file literally named ``_attachments`` is not a directory)."""
    from interchange import is_ignored

    patterns = ["_attachments/"]
    assert is_ignored("_attachments/logo.md", patterns) is True
    assert is_ignored("Projects/Rail/_attachments/deep/scan.pdf", patterns) is True
    assert is_ignored("Projects/Rail/notes.md", patterns) is False
    # the LAST segment is the file, so the dir pattern must not match it
    assert is_ignored("Projects/_attachments", patterns) is False


def test_is_ignored_path_prefix_directory_pattern():
    """Rule 2 (path prefix): a directory pattern that still contains a "/" is
    anchored at the corpus root, so it matches that exact subtree only."""
    from interchange import is_ignored

    patterns = ["Projects/Archive/"]
    assert is_ignored("Projects/Archive/old.md", patterns) is True
    assert is_ignored("Projects/Archive/2019/q1.md", patterns) is True
    # same folder name under a DIFFERENT parent is not the anchored subtree
    assert is_ignored("Personal/Archive/old.md", patterns) is False
    assert is_ignored("Projects/Active/new.md", patterns) is False


def test_is_ignored_basename_glob_and_path_glob():
    """Rules 3 and 4: a pattern containing "/" is fnmatch'd against the WHOLE
    relative path; a pattern without one is fnmatch'd against the basename only.
    Matching is case-sensitive (fnmatchcase), so macOS and Linux agree."""
    from interchange import is_ignored

    # rule 4 — basename glob, at any depth
    assert is_ignored("draft.md", ["*.md"]) is True
    assert is_ignored("Projects/Rail/draft.md", ["draft.md"]) is True
    assert is_ignored("Projects/Rail/final.md", ["draft.md"]) is False
    assert is_ignored("Projects/Rail/DRAFT.md", ["draft.md"]) is False  # case-sensitive

    # rule 3 — path glob, anchored at the root. Note fnmatch's "*" spans "/",
    # so a path glob reaches into subfolders too (a documented quirk of the
    # gitignore-LITE subset — there is no separate "**").
    assert is_ignored("Projects/scratch.md", ["Projects/*.md"]) is True
    assert is_ignored("Projects/Rail/scratch.md", ["Projects/*.md"]) is True
    assert is_ignored("Personal/scratch.md", ["Projects/*.md"]) is False


# --- parse_ignore / load_ignore_patterns (contract "ignore file") ---------
def test_parse_ignore_drops_comments_and_blanks():
    """One pattern per line, stripped; blank lines and "#" comments dropped."""
    from interchange import parse_ignore

    text = "# why adr/ is excluded\nadr/\n\n   _attachments/   \n\n#trailing comment\n"

    assert parse_ignore(text) == ["adr/", "_attachments/"]
    assert parse_ignore("") == []
    assert parse_ignore("# only a comment\n") == []


def test_load_ignore_patterns_merges_defaults_file_and_env(tmp_path, monkeypatch):
    """The effective list is DEFAULT_IGNORE + the root's .interchangeignore +
    the comma-separated INTERCHANGE_IGNORE env var."""
    from interchange import DEFAULT_IGNORE, IGNORE_FILE, load_ignore_patterns

    (tmp_path / IGNORE_FILE).write_text("# comment\nadr/\n", encoding="utf-8")
    monkeypatch.setenv("INTERCHANGE_IGNORE", " Templates/ , *.tmp.md ,, ")

    patterns = load_ignore_patterns(tmp_path)

    assert set(DEFAULT_IGNORE) <= set(patterns)
    assert "adr/" in patterns
    assert "Templates/" in patterns and "*.tmp.md" in patterns
    assert "" not in patterns  # blank env entries dropped

    # no file, no env -> defaults only
    monkeypatch.delenv("INTERCHANGE_IGNORE", raising=False)
    assert load_ignore_patterns(tmp_path / "nope") == list(DEFAULT_IGNORE)


# --- discover_files (contract "discover_files") ---------------------------
def test_discover_files_is_recursive_sorted_and_suffix_filtered(tmp_path, monkeypatch):
    """Recursive walk, restricted to .md/.txt/.pdf, sorted by relative POSIX
    path, with dot-dirs at ANY depth and _attachments/ excluded by default."""
    from interchange import discover_files, rel_source

    monkeypatch.delenv("INTERCHANGE_IGNORE", raising=False)

    def write(rel: str, body: str = "x") -> None:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body.encode())

    write("root.md")
    write("notes.txt")
    write("scan.pdf")
    write("Projects/Rail/deep.md")
    write("Projects/Rail/ignored.db")          # wrong suffix
    write("Projects/build.py")                 # wrong suffix
    write("Projects/Rail/.obsidian/plugins/cfg.md")  # nested dot-dir
    write("_attachments/logo.md")              # default ignore
    write("Projects/.DS_Store")                # dot file

    found = [rel_source(tmp_path, p) for p in discover_files(tmp_path)]

    assert found == ["Projects/Rail/deep.md", "notes.txt", "root.md", "scan.pdf"]


def test_discover_files_seed_docs_pins_the_edi_corpus():
    """The real docs/ corpus discovers EXACTLY the three seed documents.

    This pins the committed ``docs/.interchangeignore`` — recursive discovery
    must not pull the 14+ ADRs under ``docs/adr/`` into the edi index, which
    would silently change the corpus the golden eval set is scored against."""
    from interchange import DOCS_DIR, discover_files, rel_source

    assert [rel_source(DOCS_DIR, p) for p in discover_files(DOCS_DIR)] == [
        "a2a-RESULT.md",
        "rail-edi-notes.md",
        "x12-overview.md",
    ]


# --- rel_source (contract "rel_source") -----------------------------------
def test_rel_source_flat_file_is_basename(tmp_path):
    """For a flat corpus the source is exactly the basename — so the existing
    golden set and every [source] citation keep working unchanged."""
    from interchange import rel_source

    assert rel_source(tmp_path, tmp_path / "x12-overview.md") == "x12-overview.md"


def test_rel_source_nested_is_posix_relative(tmp_path):
    """A nested note gets a folder-qualified, forward-slash source."""
    from interchange import rel_source

    nested = tmp_path / "Projects" / "Rail" / "Index.md"

    assert rel_source(tmp_path, nested) == "Projects/Rail/Index.md"
    assert "\\" not in rel_source(tmp_path, nested)


# --- looks_like_secret: credential guard ----------------------------------
def test_looks_like_secret_flags_api_key_lines_and_passes_prose():
    """An assigned credential (label + ":"/"=" + a long opaque value) is flagged;
    ordinary prose that merely mentions the words is not.

    Tightened for the vault (ADR-0014): the value must be a 20+ char opaque run
    with digits, so a real password carries digits — a digit-free passphrase is a
    deliberate false negative of the second-layer guard (see
    test_looks_like_secret_ignores_placeholders_and_code for why)."""
    from interchange import looks_like_secret

    assert looks_like_secret("GEMINI_API_KEY=AIzaSyD1a2b3c4d5e6f7g8h9i0jklmn") is True
    assert looks_like_secret("api key: sk-ant-0123456789abcdefghij") is True
    assert looks_like_secret("client_secret = 9f8e7d6c5b4a39281706abcd") is True
    assert looks_like_secret("password: hunter2-9fk3-battery-staple-42x") is True

    assert looks_like_secret("We kept the token budget under 4000 tokens.") is False
    assert looks_like_secret("The password policy requires rotation.") is False
    assert looks_like_secret("An 824 is an Application Advice.") is False
    # too short to be a credential value
    assert looks_like_secret("api_key=short") is False


def test_looks_like_secret_ignores_placeholders_and_code():
    """The 13 false positives a real note vault produced (ADR-0014): a credential
    keyword whose value is a placeholder or a code reference — an env-var lookup,
    a schema builder, a template token, a `<PLACEHOLDER>` — must NOT be flagged.
    These are exactly the shapes the tightened guard was written to let through."""
    from interchange import looks_like_secret

    placeholders = [
        'api_key: "your-api-key"',
        "API_KEY=KEY_xxxxxx",
        "apiKey: 'test_api_...'",
        "apiKey: process.env.X",
        "ApiKey: z.string()",
        "secret: process.env.Y",
        "API key: `OPENAI_API_KEY`",
        "Password = process.env.Z",
        "PASSWORD=your_password",
        "apiKey: import.meta.env.X",
        "Token:taskToken,In...",
    ]
    for line in placeholders:
        assert looks_like_secret(line) is False, f"false positive on {line!r}"


def test_looks_like_secret_flags_real_key_shapes():
    """Real, opaque credentials are still caught: a well-known provider key shape
    anywhere in the text (Google AIza…, OpenAI sk-…) regardless of any label, and a
    labelled 20+ char opaque value with digits."""
    from interchange import looks_like_secret

    assert looks_like_secret("AIza" + "A" * 35) is True            # Google key shape
    assert looks_like_secret("sk-" + "a1b2c3d4e5f6g7h8i9j0k1l2") is True  # sk- + 24 alnum
    # api_key: "<24 mixed alnum with digits>"
    assert looks_like_secret('api_key: "a1b2c3d4e5f6g7h8i9j0k1l2"') is True


# --- chunk(): heading level (contract "chunk", ADR-0017) ------------------
def test_chunk_preamble_is_level_zero():
    """Content before the first heading is section ``preamble`` at ``level`` 0."""
    from interchange import chunk

    pre = [c for c in chunk("Intro before any heading.\n\n# Title\nBody.")
           if c["section"] == "preamble"]
    assert pre and all(c["level"] == 0 for c in pre)


def test_chunk_h1_is_level_one_and_h3_is_level_three():
    """A ``#`` heading section carries ``level`` 1, a ``###`` one ``level`` 3 — the
    heading DEPTH — without changing the section labels."""
    from interchange import chunk

    chunks = chunk("# One\nUnder one.\n\n### Three\nUnder three.")
    by_section = {c["section"]: c for c in chunks}
    assert by_section["One"]["level"] == 1
    assert by_section["Three"]["level"] == 3


def test_chunk_long_section_windows_all_carry_the_level():
    """Every char window of an over-long section keeps the same section label AND
    the same ``level``."""
    from interchange import CHUNK_CHARS, chunk

    text = "## Big Section\n" + ("word " * (CHUNK_CHARS // 2))
    big = [c for c in chunk(text) if c["section"] == "Big Section"]
    assert len(big) >= 2, "oversized section should split into multiple chunks"
    assert all(c["level"] == 2 for c in big)


# --- mark_lead(): structural lead detection (contract "mark_lead") --------
def test_mark_lead_does_not_mutate_inputs_and_returns_new_dicts():
    """``mark_lead`` returns new dicts and never mutates the inputs."""
    from interchange import mark_lead

    inputs = [{"text": "x", "section": "preamble", "level": 0}]
    out = mark_lead(inputs)
    assert "lead" not in inputs[0], "inputs must not be mutated"
    assert out[0]["lead"] is True
    assert out[0] is not inputs[0]


def test_mark_lead_preamble_plus_first_h1_are_lead_body_is_not():
    """Preamble (level 0) plus the first H1 section (level 1) are lead; the following
    body section is not."""
    from interchange import mark_lead

    out = mark_lead([
        {"section": "preamble", "level": 0},
        {"section": "Title", "level": 1},
        {"section": "Body", "level": 2},
    ])
    assert [c["lead"] for c in out] == [True, True, False]


def test_mark_lead_first_heading_h2_leaves_only_preamble_as_lead():
    """A note whose first heading is level 2+ has only its preamble as lead."""
    from interchange import mark_lead

    out = mark_lead([
        {"section": "preamble", "level": 0},
        {"section": "Body", "level": 2},
    ])
    assert [c["lead"] for c in out] == [True, False]


def test_mark_lead_second_h1_is_never_lead():
    """A second level-1 heading later in the note is never lead."""
    from interchange import mark_lead

    out = mark_lead([
        {"section": "preamble", "level": 0},
        {"section": "First", "level": 1},
        {"section": "Second", "level": 1},
    ])
    assert [c["lead"] for c in out] == [True, True, False]


def test_mark_lead_first_h1_windows_all_lead_no_preamble():
    """With no preamble, every window of the first H1 section is lead; the next
    section breaks the run."""
    from interchange import mark_lead

    out = mark_lead([
        {"section": "Title", "level": 1},
        {"section": "Title", "level": 1},
        {"section": "Body", "level": 2},
    ])
    assert [c["lead"] for c in out] == [True, True, False]


def test_mark_lead_empty_list_returns_empty_list():
    from interchange import mark_lead

    assert mark_lead([]) == []
