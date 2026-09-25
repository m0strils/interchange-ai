// The memorable element: a per-row rank slopegraph. Each passage's ordinal
// position across four retrieval stages — dense -> bm25 -> fused -> rerank — is
// plotted and joined by hairlines, so the reader sees the passage BM25 loved and
// the reranker demoted. Marks are --graphite; a null (signal absent) breaks the
// line and shows "—". No bars: these ranks are ordinal, not magnitudes. The
// header letters double as buttons that open the matching score legend note.

import { html, openLegend, motionOk } from "../state.js";
import { useRef, useEffect } from "../vendor/hooks.module.js";

const STAGES = ["dense", "bm25", "fused", "rerank"];
const SHORT = { dense: "d", bm25: "b", fused: "f", rerank: "r" };
const LEGEND_KEY = {
  dense: "dense_distance", bm25: "bm25_score", fused: "rrf_score", rerank: "rerank_score",
};

/**
 * Pure: derive each hit's ordinal position per stage and the shared max rank.
 * dense/bm25 come straight from the rank fields (they range over the full pool);
 * fused is ranked from rrf_score across the retrieved hits; rerank is the final
 * (post-rerank) order.
 * @returns {{paths: Map<string, {dense:?number,bm25:?number,fused:?number,rerank:?number}>, maxRank:number}}
 */
export function rankPaths(hits) {
  const withRrf = hits
    .filter((h) => h.rrf_score != null)
    .slice()
    .sort((a, b) => b.rrf_score - a.rrf_score);
  const fusedRank = new Map();
  withRrf.forEach((h, i) => fusedRank.set(h.id, i + 1));

  const paths = new Map();
  let maxRank = 1;
  for (const h of hits) {
    const p = {
      dense: h.dense_rank ?? null,
      bm25: h.bm25_rank ?? null,
      fused: fusedRank.has(h.id) ? fusedRank.get(h.id) : null,
      rerank: h.rerank_score == null ? null : h.final_rank ?? null,
    };
    paths.set(h.id, p);
    for (const s of STAGES) if (p[s] != null) maxRank = Math.max(maxRank, p[s]);
  }
  return { paths, maxRank };
}

const W = 118, H = 34, PADX = 8, PADY = 6;
const xs = STAGES.map((_, i) => PADX + (i * (W - 2 * PADX)) / (STAGES.length - 1));
const yOf = (rank, maxRank) =>
  maxRank <= 1 ? H / 2 : PADY + ((rank - 1) / (maxRank - 1)) * (H - 2 * PADY);

/** Open the score legend focused on one signal (the header letters call this). */
function openSignalLegend(stage) {
  openLegend.value = LEGEND_KEY[stage];
  try {
    const el = document.getElementById("score-legend");
    if (el) {
      el.open = true;
      el.scrollIntoView({ block: "nearest", behavior: motionOk() ? "smooth" : "auto" });
    }
  } catch (_) {
    /* no-op */
  }
}

/** Column labels shown once, in the table header — each a button to its legend note. */
export function SlopeHead() {
  return html`<div class="slope-head">
    ${STAGES.map(
      (s) => html`<button class="slope-h-btn" type="button"
        title=${`What ${s} means`} aria-label=${`Explain the ${s} score`}
        onClick=${() => openSignalLegend(s)}>${SHORT[s]}</button>`
    )}
  </div>`;
}

export function Slopegraph({ path, maxRank, label }) {
  const ref = useRef(null);
  const pts = STAGES.map((s, i) =>
    path[s] == null ? null : { x: xs[i], y: yOf(path[s], maxRank) }
  );

  const segments = [];
  for (let i = 0; i < pts.length - 1; i++) {
    if (pts[i] && pts[i + 1]) segments.push([pts[i], pts[i + 1]]);
  }

  // Draw the lines once on mount; under reduced motion, paint the final state.
  useEffect(() => {
    if (ref.current && motionOk()) {
      // Re-trigger the CSS draw animation after mount.
      ref.current.classList.remove("draw");
      void ref.current.getBoundingClientRect();
      ref.current.classList.add("draw");
    }
  }, []);

  const summary = STAGES.map((s) => `${s} ${path[s] == null ? "none" : path[s]}`).join(", ");

  return html`<div class="slope" ref=${ref}>
    <svg viewBox="0 0 ${W} ${H}" width=${W} height=${H} role="img"
         aria-label=${`Rank path${label ? ` for ${label}` : ""}: ${summary}`}>
      ${segments.map(
        ([a, b]) => html`<line class="seg" x1=${a.x} y1=${a.y} x2=${b.x} y2=${b.y} stroke-width="1" />`
      )}
      ${pts.map((p, i) =>
        p
          ? html`<circle cx=${p.x} cy=${p.y} r="2.2" />`
          : html`<text class="gap-label" x=${xs[i]} y=${H / 2 + 3} text-anchor="middle">—</text>`
      )}
    </svg>
  </div>`;
}
