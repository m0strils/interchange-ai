// Evidence table: one row per retrieved passage, ranked. A real <table> with a
// <caption> and <th scope> headers. Two verbs live here — Use (native checkbox)
// and Read (the "View passage" button). The Rank path column carries the
// slopegraph; the Scores column carries raw values as text (tabular-nums, never
// muted). A null signal shows "—" with the reason on focus/hover. The rerank
// value renders on a 0..1 track when the backend returns a probability (Jev).
// Restacks to label/value pairs under 600px (see app.css).

import {
  html, selected, toggleSelected, clearSelected, readPassage, activePassageId,
  answerFromSelected,
} from "../state.js";
import { Slopegraph, SlopeHead, rankPaths } from "./Slopegraph.js";

const fx = (v, d) => (v == null ? null : v.toFixed(d));

// Why a signal is absent for a passage — shown on the "—" via focus/hover.
const ABSENT = {
  l2: "no dense score: outside the top pool of dense candidates",
  bm25: "no bm25 rank: the passage shares no query terms",
  rrf: "no fused score: this mode does not fuse rankings",
  rerank: "outside the rerank window",
  pinned: "pinned by you — retrieval scores are not computed",
};

/** A raw score value, or "—" carrying its reason. */
function Val({ num, absentKey, pinned }) {
  if (num != null) return html`<span class="num">${num}</span>`;
  const note = pinned ? ABSENT.pinned : ABSENT[absentKey];
  // Not focusable (a "—" is not actionable): the reason lives in aria-label for AT,
  // and the CSS tooltip still shows on pointer hover (A2).
  return html`<span class="num absent" role="note"
    data-note=${note} aria-label=${`no value — ${note}`}>—</span>`;
}

/** The 0..1 probability track for a Jev rerank score, with a 0.5 tick. */
function ProbTrack({ p }) {
  if (p == null) return html`<${Val} num=${null} absentKey="rerank" />`;
  return html`<span class="prob" title=${`Jev probability ${p.toFixed(2)} on a 0 to 1 scale`}>
    <span class="prob-track" aria-hidden="true">
      <span class="prob-tick"></span>
      <span class="prob-fill" style=${`width:${Math.round(p * 100)}%`}></span>
    </span>
    <span class="num">${p.toFixed(2)}</span>
  </span>`;
}

function ScoreStack({ hit, rerankKind }) {
  const isProb = rerankKind === "probability";
  const rows = [
    { lab: "l2", key: "l2", num: fx(hit.dense_distance, 3) },
    { lab: "bm25", key: "bm25", num: fx(hit.bm25_score, 2) },
    { lab: "rrf", key: "rrf", num: fx(hit.rrf_score, 4) },
  ];
  return html`<div class="scores">
    ${rows.map(
      (r) => html`<div class="s">
        <span class="lab">${r.lab}</span>
        <${Val} num=${r.num} absentKey=${r.key} pinned=${hit.pinned} />
      </div>`
    )}
    <div class="s">
      <span class="lab">${isProb ? "jev" : "rerank"}</span>
      ${isProb
        ? html`<${ProbTrack} p=${hit.rerank_score} />`
        : html`<${Val} num=${fx(hit.rerank_score, 2)} absentKey="rerank" pinned=${hit.pinned} />`}
    </div>
  </div>`;
}

export function Ledger({ run, sample = false }) {
  const hits = run.hits || [];
  const rerankKind = run.scoring && run.scoring.rerank_score ? run.scoring.rerank_score.kind : "logit";

  if (hits.length === 0) {
    return html`<section aria-labelledby="ev-h">
      <h2 class="h-sm" id="ev-h">Evidence</h2>
      <p class="ev-empty">No evidence — the question was stopped before any passage was retrieved.</p>
    </section>`;
  }

  const { paths, maxRank } = rankPaths(hits);
  const cited = new Set(run.cited || []);

  return html`<section aria-labelledby=${sample ? "ev-h-sample" : "ev-h"}>
    ${!sample &&
    html`<h2 class="h-sm" id="ev-h">Evidence<span class="count">${hits.length} passages, ranked</span></h2>`}
    <div class="evidence-scroll" tabindex="0" role="region" aria-label="Retrieved evidence, scrollable">
      <table class="evidence">
        <caption id=${sample ? "ev-h-sample" : undefined}>
          Retrieved evidence, ranked. Rank path reads dense → bm25 → fused → rerank;
          — marks a signal a passage does not have.
        </caption>
        <thead>
          <tr>
            ${!sample && html`<th scope="col" class="use">Use</th>`}
            <th scope="col" class="rank">#</th>
            <th scope="col">Passage</th>
            <th scope="col">Rank path<${SlopeHead} /></th>
            <th scope="col">Scores</th>
          </tr>
        </thead>
        <tbody>
          ${hits.map((hit) => {
            const isSel = selected.value.has(hit.id);
            const isCited = cited.has(hit.source);
            const isOpen = activePassageId.value === hit.id;
            // Row click is a Read convenience: open the passage unless the click
            // landed on the Use checkbox/label or the View passage button (U5).
            const rowClick = sample
              ? undefined
              : (e) => {
                  if (e.target.closest("input,label,button,a")) return;
                  readPassage(hit.id);
                };
            return html`<tr id=${sample ? undefined : `ev-row-${hit.id}`}
                class=${isSel ? "is-selected" : ""} onClick=${rowClick}>
              ${!sample &&
              html`<td class="use" data-label="Use">
                <label>
                  <input type="checkbox" checked=${isSel}
                    aria-label=${`Use ${hit.id} in a grounded re-ask`}
                    onChange=${() => toggleSelected(hit.id)} />
                </label>
              </td>`}
              <td class="rank" data-label="Rank">${hit.final_rank}</td>
              <td class="passage-cell" data-label="Passage">
                <div class="id">${hit.source}:${hit.chunk}</div>
                <div class="sec">${hit.section}</div>
                <button class="read" type="button" aria-pressed=${isOpen}
                  onClick=${() => readPassage(hit.id)}>View passage</button>
                ${hit.pinned && html`<span class="pin-tag">pinned</span>`}
                ${isCited && html`<span class="cited">cited in the answer</span>`}
              </td>
              <td data-label="Rank path">
                <${Slopegraph} path=${paths.get(hit.id)} maxRank=${maxRank} label=${hit.id} />
              </td>
              <td data-label="Scores"><${ScoreStack} hit=${hit} rerankKind=${rerankKind} /></td>
            </tr>`;
          })}
        </tbody>
      </table>
    </div>

    ${!sample &&
    html`<div class="select-bar">
      <span class="summary">${selected.value.size} selected</span>
      ${selected.value.size > 0 &&
      html`<button class="clear" type="button" onClick=${clearSelected}>clear</button>`}
      <button class="btn" type="button" disabled=${selected.value.size === 0}
        onClick=${answerFromSelected}
        title=${selected.value.size === 0 ? "Tick Use on the passages you trust first" : ""}>
        Answer from selected${selected.value.size ? ` (${selected.value.size})` : ""}
      </button>
    </div>`}
  </section>`;
}
