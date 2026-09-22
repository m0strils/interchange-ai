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
