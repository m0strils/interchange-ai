# ADR-0010: Document ingestion formats — PDF via pypdf (BSD)

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** Jeff Lynch

## Context
`build_index()` only ingests `*.md` and `*.txt` from `docs/`. Real EDI/rail
reference material often arrives as PDF, so ingestion needs to grow to cover it.

Two realistic Python libraries fit: **pypdf** (pure-Python, BSD-3, offline, plain
text only) and **pymupdf4llm** (built on PyMuPDF/MuPDF, **AGPL v3**, outputs
Markdown *with headings* — a natural fit for the ADR-0007 heading-aware
`chunk()`). The extraction-quality tradeoff is real: pymupdf4llm would hand
`chunk()` real section boundaries; pypdf hands it a flat wall of text that all
lands in the `"preamble"` section.

The forcing constraint: this repo is **MIT** and slated to go public (per
`CLAUDE.md`'s honest-claim / public-repo posture). AGPL v3 is a copyleft license
that would require anyone linking/distributing pymupdf4llm-based code to release
their own source under AGPL-compatible terms — incompatible with a permissively
licensed, resellable-adjacent portfolio project. License hygiene has to win over
extraction fidelity here.

## Options considered
1. **pypdf** — pure-Python PDF text extraction, BSD-3. Pros: license-compatible
   with MIT, zero native deps, offline/$0, simple `PdfReader` API. Cons: no
   Markdown structure — `page.extract_text()` returns flat text, so PDF content
   always chunks as `"preamble"`; no OCR (scanned/image PDFs extract to `""`).
2. **pymupdf4llm** (PyMuPDF) — converts PDF to Markdown with headings preserved,
   feeding `chunk()`'s structure-aware split exactly as designed. Pros: much
   better retrieval-relevant chunking for PDF sources. Cons: **AGPL v3** —
   incompatible with the repo's MIT license and public-repo intent.
3. **Both, behind a flag** — default to pypdf, offer pymupdf4llm as an opt-in
   extra for users who accept AGPL terms. Pros: keeps the high-fidelity path
   available. Cons: adds a runtime branch, a second dependency to maintain, and
   an AGPL boundary to explain/enforce correctly — premature for one seed corpus
   with zero PDFs in it today.

## Decision
**pypdf.** MIT-repo license cleanliness wins over extraction fidelity. PDF text
extracts flat and lands in `chunk()`'s `"preamble"` section — an accepted,
documented tradeoff, not an oversight.

## Consequences
- PDF-sourced chunks lose heading structure, so section-aware retrieval
  (ADR-0007) is weaker for PDF sources than for the Markdown seed docs — every
  PDF chunk in the corpus carries `section: "preamble"` unless the PDF text
  happens to contain literal Markdown-style `#` headings (unlikely).
- No OCR: a scanned/image-only PDF extracts to `""`. `build_index()` treats
  whitespace-only extraction as a signal to `WARN` and skip the file rather than
  silently index nothing — an honest-telemetry choice (ADR-0004's spirit applied
  to ingestion), and the skip count is reported in the indexing summary.
- Stays dependency-light and offline/$0 (pypdf is pure-Python, no native/AGPL
  code enters the dependency tree).
- Escape hatch, if PDF retrieval quality ever becomes the bottleneck: add
  pymupdf4llm as an **opt-in** extra behind an explicit flag, documented as an
  AGPL boundary the user opts into — Option 3 above, deferred until there's a
  real corpus and a measured need (mirrors ADR-0007's "measure before you build"
  posture).
- Cross-references ADR-0007 (retrieval/chunking strategy) — this ADR governs
  what text `chunk()` receives, not how `chunk()` splits it.
