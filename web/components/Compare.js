// Compare view: two runs' ledgers placed side by side, keyed on chunk id, with a
// rank-delta column so the reader sees exactly which passage each run's ranking
// moved. Keys are chunk ids (never parsed — read straight off the hit). A chunk
// that only one run retrieved shows "—" on the other side. Movement marks are
// --graphite/--ink; --built stays reserved for grounded status and the selected
// rule, so a rank change is never dressed as "good".

import { html, runs, activeRunId, compareWith } from "../state.js";

function label(run) {
  const eff = run.options_effective || run.options || {};
  const rr = eff.rerank && eff.rerank !== "none" ? eff.rerank : "no rerank";
  return `${eff.mode}, ${rr}`;
}

function delta(a, b, aId, bId) {
  if (a == null && b == null) return { text: "—", cls: "d-none" };
  if (a == null) return { text: `new in run ${bId} (rank ${b})`, cls: "d-new" };
  if (b == null) return { text: `only in run ${aId} (rank ${a})`, cls: "d-drop" };
  const diff = a - b; // positive = moved up (better) in run B
  if (diff === 0) return { text: `${a} → ${b}, unchanged`, cls: "d-none" };
  const dir = diff > 0 ? `up ${diff}` : `down ${-diff}`;
  return { text: `${a} → ${b}, ${dir}`, cls: diff > 0 ? "d-up" : "d-down" };
}

export function Compare() {
  const list = runs.value;
  const A = list.find((r) => r.id === activeRunId.value) || list[0];
  const B = list.find((r) => r.id === compareWith.value) || list[1];
  if (!A || !B) return null;

  const aRank = new Map(A.hits.map((h) => [h.id, h]));
  const bRank = new Map(B.hits.map((h) => [h.id, h]));
  const ids = [];
  for (const h of A.hits) ids.push(h.id);
  for (const h of B.hits) if (!aRank.has(h.id)) ids.push(h.id);
  ids.sort((x, y) => {
    const ax = aRank.get(x)?.final_rank ?? 99;
    const ay = aRank.get(y)?.final_rank ?? 99;
    if (ax !== ay) return ax - ay;
    const bx = bRank.get(x)?.final_rank ?? 99;
    const by = bRank.get(y)?.final_rank ?? 99;
    return bx - by;
  });

  return html`<section class="compare" aria-labelledby="cmp-h">
    <h2 class="h-sm" id="cmp-h">Compare
      <span class="count">run ${A.id} and run ${B.id}, keyed on passage</span></h2>
    <div class="evidence-scroll" tabindex="0" role="region" aria-label="Run comparison, scrollable">
      <table class="evidence cmp">
        <caption>
          Both runs' rankings for the same question, joined on chunk id. The delta
          reads run ${A.id} → run ${B.id}; — marks a passage a run did not retrieve.
        </caption>
        <thead>
          <tr>
            <th scope="col">Passage</th>
            <th scope="col" class="rank">Run ${A.id}<span class="cmp-sub">${label(A)}</span></th>
            <th scope="col" class="rank">Run ${B.id}<span class="cmp-sub">${label(B)}</span></th>
            <th scope="col">Rank change</th>
          </tr>
        </thead>
        <tbody>
          ${ids.map((id) => {
            const a = aRank.get(id);
            const b = bRank.get(id);
            const hit = a || b;
            const ar = a ? a.final_rank : null;
            const br = b ? b.final_rank : null;
            const d = delta(ar, br, A.id, B.id);
            return html`<tr>
              <td class="passage-cell" data-label="Passage">
                <div class="id">${hit.source}:${hit.chunk}</div>
                <div class="sec">${hit.section}</div>
              </td>
              <td class="rank" data-label=${`Run ${A.id}`}>${ar == null ? html`<span class="num absent">—</span>` : ar}</td>
              <td class="rank" data-label=${`Run ${B.id}`}>${br == null ? html`<span class="num absent">—</span>` : br}</td>
              <td class="cmp-delta" data-label="Rank change"><span class=${d.cls}>${d.text}</span></td>
            </tr>`;
          })}
        </tbody>
      </table>
    </div>
    <p class="cmp-note">Pick a run tab above to leave compare and inspect one run's full evidence.</p>
  </section>`;
}
