// Honest score legend, straight from the run's `scoring` document. Collapsed by
// default (<details id="score-legend">) so it never competes with the evidence,
// but always one keystroke away — and the d/b/f/r header buttons open it focused
// on one signal (the row is highlighted). The point of the workbench is trusting
// the numbers, so the definitions are never more than a click from the marks.

import { html, openLegend } from "../state.js";

const ORDER = ["dense_distance", "bm25_score", "rrf_score", "rerank_score"];
const NAME = {
  dense_distance: "Dense distance",
  bm25_score: "BM25 score",
  rrf_score: "Fused (RRF) score",
  rerank_score: "Rerank score",
};

export function Legend({ scoring }) {
  const hot = openLegend.value;
  return html`<details class="legend-block" id="score-legend">
    <summary>What the scores mean</summary>
    <dl>
      ${ORDER.filter((key) => scoring[key]).map((key) => {
        const s = scoring[key];
        const kind = s.backend ? `${s.kind} (${s.backend})` : s.kind;
        return html`<div class=${key === hot ? "hot" : ""}>
          <dt>${NAME[key]}<span class="kind">${kind}</span></dt>
          <dd>${s.note}</dd>
        </div>`;
      })}
    </dl>
  </details>`;
}
