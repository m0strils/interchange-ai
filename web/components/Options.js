// Retrieval options: mode, k, and the rerank radio group. LIVE, these render off
// GET /options — allowed modes, the k bounds, which rerank backends are available,
// and whether a knob is locked by policy — and hard-code nothing. The Jev radio
// has three looks (review row 2): available with its metered estimate, disabled
// with the server's policy reason, and a first-use inline confirm.

import { html, mode, k, rerank, jev, options, fixtureMode } from "../state.js";
import { useState } from "../vendor/hooks.module.js";

const FALLBACK_MODES = ["hybrid", "dense", "bm25", "hybrid+links"];

/** Render a server reason with a leading capital and a terminal period, tolerating
 *  a server that already punctuates it (U7). */
function sentence(s) {
  const t = (s || "").trim();
  if (!t) return t;
  const capped = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(capped) ? capped : `${capped}.`;
}

export function Options() {
  const o = options.value;
  const modes = o ? o.mode.allowed : FALLBACK_MODES;
  const kMin = o ? o.k.min : 1;
  const kMax = o ? o.k.max : 20;
  const modeLocked = o ? o.mode.locked : false;
  const rerankLocked = o ? o.rerank.locked : false;
  const kLocked = o ? o.k.locked : false;
  // `reason` is null unless the knob is locked; render it as help text, uniformly.
  const modeReason = (o && o.mode.reason) || "mode is locked by policy";
  const rerankReason = (o && o.rerank.reason) || "rerank is locked by policy";
  const kReason = (o && o.k.reason) || "k is locked by policy";
  const rerankAllowed = o ? o.rerank.allowed : ["none", "cross-encoder"];
  const hasLocal = rerankAllowed.includes("cross-encoder") || rerankAllowed.includes("flashrank");
  const localBackend = rerankAllowed.includes("cross-encoder") ? "cross-encoder" : "flashrank";

  // Jev (metered) availability and its honest estimate, both from /options.
  const meteredAllowed = o ? o.metered.allowed : jev.value !== "policy-off";
  const jevEnabled = meteredAllowed;
  const jevReasonServer = o ? o.rerank.unavailable && o.rerank.unavailable.typesafe : null;
  // Reason from the server, punctuated tolerantly; the remedy is phrased for a
  // non-operator; the env var lives only in a secondary line / title (U7).
  const jevReason = sentence(jevReasonServer || "Metered reranking is off by policy");
  const jevRemedy = "Ask an operator to enable metered reranking.";
  const jevEnvNote = "An operator sets INTERCHANGE_ALLOW_METERED=1 to enable it.";
  const window = o ? o.metered.window : 30;
  const price = o ? o.metered.price_per_judgment_usd : 0.0000556;
  const est = price && window ? (price * window).toFixed(4) : "0.002";
  const jevEstimate = `Jev probability, metered — about ${window} judgments ≈ $${est} per ask`;

  const kNum = Number(k.value);
  const kOver = Number.isFinite(kNum) && kNum > kMax;

  const [confirming, setConfirming] = useState(jev.value === "confirm");

  const pickJev = () => {
    if (!jevEnabled) return;
    if (rerank.value !== "typesafe") setConfirming(true);
    rerank.value = "typesafe";
  };

  return html`<div class="options">
    <label class="grp">mode
      <select value=${mode.value} disabled=${modeLocked}
        onChange=${(e) => (mode.value = e.target.value)}>
        ${modes.map((m) => html`<option value=${m}>${m}</option>`)}
      </select>
    </label>
    ${modeLocked &&
    html`<span class="inline-note" role="note">${modeReason}</span>`}

    <label class="grp">k
      <input type="number" min=${kMin} max=${kMax} value=${k.value} disabled=${kLocked}
        aria-describedby=${kLocked ? "k-locked" : kOver ? "k-clamp" : undefined}
        onInput=${(e) => (k.value = e.target.value)}
        onBlur=${(e) => { const v = Number(e.target.value); if (v > kMax) k.value = kMax; else if (v < kMin) k.value = kMin; }} />
    </label>
    ${kLocked
      ? html`<span class="inline-note" id="k-locked" role="note">${kReason}</span>`
      : kOver &&
        html`<span class="inline-err" id="k-clamp" role="status">k is capped at ${kMax} for this index</span>`}

    <fieldset class="rerank-set" disabled=${rerankLocked}>
      <legend>rerank</legend>
      <label class="radio">
        <input type="radio" name="rerank" checked=${rerank.value === "none"}
          onChange=${() => (rerank.value = "none")} />
        <span>none</span>
      </label>
      ${hasLocal &&
      html`<label class="radio">
        <input type="radio" name="rerank" checked=${rerank.value === localBackend}
          onChange=${() => (rerank.value = localBackend)} />
        <span>local, $0</span>
      </label>`}
      <label class=${`radio jev ${jevEnabled ? "" : "disabled"}`}
        title=${jevEnabled ? jevEstimate : `${jevReason} ${jevRemedy}`}>
        <input type="radio" name="rerank" disabled=${!jevEnabled}
          checked=${rerank.value === "typesafe"} onChange=${pickJev} />
        <span>${jevEnabled ? "Jev probability, metered" : "Jev probability"}</span>
      </label>
    </fieldset>
    ${rerankLocked &&
    html`<span class="inline-note" role="note">${rerankReason}</span>`}

    ${jevEnabled
      ? html`<p class="jev-note" id="jev-est">${jevEstimate}</p>`
      : html`<p class="jev-note off" id="jev-est" title=${jevEnvNote}>
          ${jevReason} ${jevRemedy}
          <span class="jev-env">${jevEnvNote}</span>
        </p>`}

    ${jevEnabled && confirming && rerank.value === "typesafe" &&
    html`<div class="jev-confirm" role="group" aria-label="Confirm metered rerank">
      <p>Jev is metered. This ask spends about <b>$${est}</b> from the daily budget.</p>
      <div class="jc-actions">
        <button class="btn btn-primary" type="button" onClick=${() => setConfirming(false)}>Use Jev</button>
        <button class="btn" type="button"
          onClick=${() => { rerank.value = "none"; setConfirming(false); }}>Not now</button>
        <button class="link-btn" type="button"
          onClick=${() => { jev.value = "available"; setConfirming(false); }}>Don't ask again this session</button>
      </div>
    </div>`}
  </div>`;
}
