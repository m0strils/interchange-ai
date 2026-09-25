# Lesson 09 — Many corpora, one engine; and the retrieval unit is not the context unit

Lessons 01 to 08 built one governed pipeline over one corpus. This lesson is about
what happens when the same engine has to serve *several* corpora — a public seed
corpus, a demo vertical, a personal notes vault, a folder of saved research dumps —
and about the retrieval failure that only shows up once the corpus is a real
knowledge base of small notes instead of a handful of reference documents.

Five decisions carry it: [ADR-0014](../docs/adr/0014-vault-corpus-and-measured-ablations.md)
(a real vault as a corpus, and measured ablations), [ADR-0016](../docs/adr/0016-corpus-profiles-as-portable-data.md)
(corpus profiles as portable data), [ADR-0017](../docs/adr/0017-passage-level-retrieval-and-lead-chunks.md)
(a passage-level metric, and a fix that was measured and rejected), and
[ADR-0018](../docs/adr/0018-context-assembly-with-a-budget.md) (context assembly with
a budget). ADR-0015, the workbench, is Lesson 08. Read the ADRs for the options
menus; this lesson is the *why*, the numbers, and the three mistakes that taught
the most.

## What we add

- **Profiles as data.** A corpus is a YAML block: path, collection, ignore rules,
  golden set, persona, retrieval mode, tool allow-list. A private overlay file adds
  or extends profiles outside the tree, so personal corpora never enter a public
  repo. One process serves any of them; the persona and tools follow the corpus per
  request.
- **A metric that sees passages, not just files.** `passage@k` and a `lead share`
  diagnostic, on top of the file-level `hit@k` from Lesson 04.
- **Context assembly.** After ranking, the context handed to the model is assembled
  by *note* under a character budget, with the chunks still doing the ranking.
- **Two eval habits** that made the rest honest: pre-register the numbers before
  building, and build the metric before the fix.

## Part 1: the vertical is data, not code

ADR-0013 (Lesson 07) made the claim that a vertical is a profile block, not a fork.
ADR-0014 tested it on the hardest corpus available: a real Obsidian vault of 207
notes with nested folders, duplicate basenames, YAML frontmatter, ~1,100 wikilinks,
and one note that held live keys. Four things had to exist before the claim held:

1. **Recursive discovery with an ignore file** (`discover_files`, `.interchangeignore`,
   a gitignore-lite subset). Source paths became folder-qualified, which is what
   disambiguates `Index.md` three times over.
2. **A credential guard at ingest** (`looks_like_secret`): a file that looks like it
   carries a key is skipped whole and counted, never embedded. A vector store is a
   place retrieval can surface text *into a prompt*; the guard is the second copy of
   the rule that keeps keys out of the corpus in the first place.
3. **Wikilink resolution** with Obsidian's shortest-path rule, stored as chunk
   metadata. It cost little and it enabled a measurement (below).
4. **Frontmatter kept in the indexed text**, deliberately: `tags`, `type`, `project`
   tokens are exactly what BM25 needs for a notes corpus. This decision is right, and
   Part 3 is about its cost.

Then ADR-0016 finished the job the workaround had started. The vault profile had
been committed with a `${INTERCHANGE_VAULT_DIR}` placeholder and an ignore list that
named a personal file; the index directory was hardcoded under the repo; the persona
was a rail/EDI system prompt for every corpus; and the X12 segment-lookup tool was
exposed to a notes agent that could only misuse it. The fix was small and all of it
is data:

```yaml
# ~/.interchange/profiles.yaml — a private overlay, never committed
brain:
  collection: brain
  docs_dir: ~/Documents/Brain
  golden: ~/.interchange/golden-brain.jsonl
  retrieval: {mode: hybrid, context: notes, budget_chars: 20000, note_max_chars: 16000,
              chunks_only: ["30-Career/People/", "30-Career/Interviews/"]}
  tools: [search_docs]
  persona: >
    You are the owner's second brain over a personal Obsidian vault. Answer only
    from the provided notes, cite the note path in [brackets], and say plainly when
    the notes do not cover the question.
```

`INTERCHANGE_PROFILES` names the overlay; `INTERCHANGE_CHROMA_DIR` relocates the
store so one machine has one store with N collections; `--profile NAME` applies a
profile in-process before any work, which retired the "export before `.env`" edge.
Persona is resolved **per request by collection**, so one server answers `hotel`
in a hotel voice and `edi` in the rail voice. The tool list is a least-privilege
allow-list honoured by both the subscription agent and the MCP server: a notes
profile never sees `lookup_segment`.

The measured part: rebuilds of 0.3 s, 3 s and 30 s for the three corpora settled
the freshness question (nightly full rebuild under launchd; incremental reindex is
trigger-gated on a rebuild over five minutes), and the vault's own golden set gave
ADR-0007's deferred reranker its trigger: `hybrid` 11/18 at rank 1, `hybrid+rerank`
15/18, a local cross-encoder at $0. The same run also *rejected* a feature: naive
one-hop wikilink expansion fell to 6/18. Building it was cheap; measuring it was the
point.

## Part 2: the metric that could not see the problem

The first real questions against the personal vault exposed a failure `hit@k`
cannot express. Asked for "the five most important Claude Code practices" the
engine ranked the right three notes first — and answered with pointers, no
practices. Every top-4 chunk was a frontmatter or title chunk.

Root cause, once you look at `chunk()`: a note with frontmatter yields two tiny
chunks before any body — the preamble (~190 chars) and the H1 with its intro
(~285 chars) — both dense with the exact topic tokens, both short enough that
BM25's length normalisation and the dense embedder prefer them to 600-char body
sections. That is the cost of keeping frontmatter in the index. And `hit@k`
scores a hit when the expected *file* is in the top-k, so on this corpus it read
18/19 while the answers were empty.

ADR-0017 built the missing metric first: golden rows gain an optional
`expected_section`; `passage@k` counts a hit only when a top-k chunk has the
expected source *and* a matching section label; `lead share` reports the fraction
of top-k chunks that are preamble or first-H1 chunks. The baseline: `passage@4`
3/6, lead share 0.26 — a quarter of every top-4 was a title.

Then it built the obvious fix and measured it: merge the lead chunks into the
first body chunk at ingest. Lead share fell on every corpus, exactly as designed.
And three of four acceptance gates failed: rail 14/14 → 13/14, vault `hybrid+rerank`
15/18 → 12/18 with the `hybrid` control unchanged, brain `passage@4` flat at 3/6.
Longer merged chunks gave the cross-encoder less focused passages. The merge was
reverted in one commit; the metric and the structural lead detection stayed.

The lesson is not "don't merge chunks". It is that the fix had been pointed at the
wrong layer, and only a pre-registered gate with a control could say so before it
shipped.

## Part 3: the retrieval unit is not the context unit

Reframed, the problem was never ranking. Source-level retrieval was 22 to 25 of 25
in every mode. What failed was what got handed to the model: four chunks of about
600 characters, chosen by chunk-level scoring, for a question whose answer spans ten
sections of one 4,918-character note. Perfect passage ranking would still have failed
it. And the notes are small — median 6.2k characters, most under 12k — so a whole note
fits comfortably in a context that already costs about ten thousand tokens per call.

ADR-0018 keeps chunks as the unit that is ranked and reranked, and adds a pure step
after ranking that assembles the context by note under a budget:

1. **Seed.** Every hit's own chunk is included first, so the assembled context is a
   superset of what the engine saw before. A test pins it.
2. **Fair share.** Each hit gets an equal share of the remaining budget; in rank order
   it takes its whole note if the note is under a size cap and fits its share, else
   ±1 neighbouring chunks.
3. **Redistribute.** The unspent remainder completes notes that now fit whole, else
   widens neighbours to ±2, never beyond.

One `[source]` block per note in chunk order, the budget measured on the emitted
string, expansion-added chunks passed through the credential guard, and a note is
never truncated mid-chunk. Two more rules came out of the design review rather than
the first draft, and both are the kind of thing that is expensive to retrofit:

- **Pinned re-asks never assemble.** Lesson 08's pins prove one chunk was returned;
  they are not a read-the-note capability. `pinned` forces `chunks`.
- **Sources follow the included set.** The grounding check, citations and the audit
  row use the sources that actually contributed text; a note that ranked but was
  dropped by the budget is never a legitimate citation target.

The first version of the expansion rule was greedy — each hit spent what it liked in
rank order — and the pre-registered gate caught it: `context@4` 4/7, mean context
16,702 characters against a 14,000 ceiling, and every knob variant left the mean
pinned at the budget because a big note at rank 1 starved the small target note at
rank 3. The largest note in the corpus turned out to be the plan for this very
change, which quoted the eval questions and outranked the notes they were about.
That is what a self-referential corpus does; the corpus was frozen and the rule was
revised, not the numbers.

Measured, on the frozen 25-row set, brain profile on plain `hybrid` (which the
control already preferred on this corpus; the vault keeps `hybrid+rerank`, its own
measured best):

| | before | after |
|---|---:|---:|
| context@4 (section rows) | 2/7 | 7/7 |
| note@4 (eligible rows) | n/a | 21/24 |
| mean assembled chars | 2,879 | 12,961 |
| per-row ranking changes | | 0 |
| rail hit@1 / vault hit@1 | 14/14 / 15/18 | 14/14 / 15/18 |
| graded answer-correctness (3 pre-registered rubric rows) | 40% | 93% |
| headless input tokens, mean of three live questions | 9,851 | 14,615 |

The 40% deserves a sentence. The answer-quality judge from Lesson 05 had reproduced
the RAG path by hand — raw top-k chunks, no persona, no assembly — and so graded a
context no surface built any more. The gate found it; the judge now calls the
governed `answer_detail` with the audit row switched off. Three lessons in, the eval
harness is still where the bugs are found first.

## The mapping

**OWASP LLM Top 10**
- *LLM01 Prompt injection.* Whole notes and neighbours enter the context in bulk, so
  the injection surface grows with the budget. The `research` corpus of saved
  internet dumps therefore stays on `chunks`; moving it needs a retrieved-text
  injection scan, which has its own trigger in the ADR backlog. The DATA framing and
  the grounding check are not a substitute.
- *LLM02 Insecure output handling / LLM06 Sensitive information disclosure.* The
  credential guard runs at ingest on whole files and again on every expansion-added
  chunk; the audit row stores sources and counts, never the context; `chunks_only`
  prefixes keep People and Interviews notes retrievable but never sent whole.
- *LLM08 Excessive agency.* Tools are a per-profile allow-list; the MCP server
  registers `lookup_segment` only when the profile grants it.
- *Access control.* The HTTP `context` knob is locked by default and clamped by
  policy; a public deploy clamps every profile to `chunks`. Pins never expand.

**NIST AI RMF**
- *GOVERN.* Profiles are inspectable data with a committed public shape and a private
  overlay; the corpus allow-list decides what a process may serve.
- *MEASURE.* Pre-registered expectations, a frozen golden set with a recorded hash, a
  control pinned by a test, and two rejections recorded with their numbers.
- *MANAGE.* Every decision carries its trigger for the next one.

## Run it yourself

```bash
# committed profiles work from a fresh clone
python interchange.py --profile rail --reindex
python interchange.py --profile rail --engine stub --ask "what is an 824?"

# a personal corpus is an overlay profile, never a fork
cat > ~/.interchange/profiles.yaml <<'EOF'
notes:
  collection: notes
  docs_dir: ~/path/to/your/vault
  retrieval: {mode: hybrid, context: notes}
  tools: [search_docs]
EOF
export INTERCHANGE_PROFILES=~/.interchange/profiles.yaml INTERCHANGE_CHROMA_DIR=~/.interchange/chroma
python interchange.py --profile notes --reindex
python interchange.py --profile notes --engine claude-code --explain --ask "..."

# the metrics, on the rail set (section rows need expected_section in the golden file)
make eval PROFILE=rail K=4
make eval PROFILE=rail K=4 CONTEXT=notes MODE=all
```

## What this does not prove

- The brain numbers were measured on a private corpus and cannot be reproduced from
  this clone; the rail and vault numbers can (the vault set needs your own vault).
- Twenty-five rows and seven section rows is a small set; the pre-registration, the
  control and the rejections are the evidence, not the fractions alone.
- `notes` assembly roughly triples the shadow cost of a call on the context term. It is
  $0 marginal on a subscription and it is recorded on every audit row; on a metered
  engine the daily budget now counts it.
- Incremental reindex, cross-corpus fan-out, a retrieved-text injection scan and the
  HTTP surface reading the profile's retrieval mode are all deferred with triggers,
  not built.
