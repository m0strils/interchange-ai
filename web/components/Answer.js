// Answer pane. Answers stack and never replace: the active run's answer is
// expanded, earlier ones collapse to a summary. The grounded/ungrounded state is
// rendered from the `grounded` boolean into a <div role="status"> before the
// prose, wired with aria-describedby (review row 21). A blocked question shows a
// panel with the reason verbatim and "Edit question". "Copy run as JSON" and
// "Copy link to this run" write to the clipboard (downloads are inert in some
// sandboxes). request_id and audit_id are copyable.

import { html, citePassage } from "../state.js";
import { useState, useRef, useEffect } from "../vendor/hooks.module.js";

/** Split answer text into plain runs and [citation] marks. Each citation is a
 *  button: it focuses the matching evidence row and opens its passage (U4). */
function renderProse(text, run) {
  const parts = [];
  const re = /\[([^\]]+)\]/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const src = m[1];
    parts.push(html`<button class="cite" type="button"
      aria-label=${`Show the evidence cited as ${src}`}
      onClick=${() => citePassage(run.id, src)}>${src}</button>`);
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function report(run) {
  return {
    request_id: run.request_id, audit_id: run.audit_id, question: run.q,
    options_requested: run.options, options_effective: run.options_effective,
    index: run.index, hits: run.hits, scoring: run.scoring,
    answer_text: run.answer_text, grounded: run.grounded,
    engine: run.engine, model: run.model, cost_usd: run.cost_usd,
    telemetry: run.telemetry, stages: run.stages,
  };
}

function linkFor(run) {
  const o = run.options || {};
  const p = new URLSearchParams();
  p.set("q", run.q || "");
  if (o.mode) p.set("mode", o.mode);
  if (o.k != null) p.set("k", String(o.k));
  // Never mirror a metered choice into a shareable link.
  if (o.rerank && o.rerank !== "typesafe") p.set("rerank", o.rerank);
  return `${location.origin}${location.pathname}?${p.toString()}`;
}

function subtitle(run) {
  if (run.blocked) return "blocked";
  if (run.pinned_on) return `grounded on your ${run.pinned_on} selected passages`;
  const eff = run.options_effective || run.options || {};
  return `${eff.mode}, ${(run.hits || []).length} passages`;
}

/** A small copy-to-clipboard control that confirms in place. On a clipboard
 *  rejection (insecure context, permission denied) it says so and exposes the
 *  text in a selectable field so the reader can copy it by hand (U11b). */
function Copy({ text, children, className = "btn", label }) {
  const [state, setState] = useState("idle"); // idle | done | failed
  const faref = useRef(null);
  useEffect(() => {
    if (state === "failed" && faref.current) faref.current.select();
  }, [state]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("done");
      setTimeout(() => setState("idle"), 1500);
    } catch (_) {
      setState("failed");
    }
  };
  return html`<span class="copy-wrap">
    <button class=${className} type="button" aria-label=${label || undefined} onClick=${copy}>
      ${state === "done" ? "copied" : children}
    </button>
    ${state === "failed" &&
    html`<span class="copy-fail">
      <span class="copy-fail-msg" role="status">Couldn't copy, select the text instead:</span>
      <textarea class="copy-fallback" readonly ref=${faref} rows="2"
        onFocus=${(e) => e.target.select()}>${text}</textarea>
    </span>`}
  </span>`;
}

export function Answer({ run, expanded }) {
  const statusId = `grounded-${run.id}`;
  const proseId = `answer-${run.id}`;
  const running = (run.stages || []).some((s) => s.running);
  const failed = (run.stages || []).some((s) => s.failed);
  const hasAnswer = !!run.answer_text;

  const head = html`<div class="ahead">
    <h3 id=${`answer-h-${run.id}`}>Answer ${run.id}</h3>
    <span class="asub">${subtitle(run)}</span>
    ${!run.blocked && hasAnswer &&
    html`<div id=${statusId} role="status" class=${`status ${run.grounded ? "grounded" : "ungrounded"}`}>
      <span class="glyph" aria-hidden="true">${run.grounded ? "✓" : "!"}</span>
      <span class="st-lines">
        <b>${run.grounded ? "Grounded" : "Ungrounded"}</b>
        <span class="st-sub">${run.grounded
          ? "Every claim cites a passage"
          : "Not fully supported by the cited passages"}</span>
      </span>
    </div>`}
  </div>`;

  let body;
  if (run.blocked) {
    body = html`<div class="blocked-panel" role="status">
      <p class="bp-lead">This question was blocked before it reached the index.</p>
      <p class="bp-reason">${run.blocked}</p>
      <button class="btn btn-primary" type="button"
        onClick=${() => { const el = document.getElementById("qbox"); if (el) el.focus(); }}>
        Edit question</button>
    </div>`;
  } else if (!hasAnswer) {
    body = html`<p class=${`answer-wait ${failed ? "is-fail" : ""}`}>
      ${failed
        ? "The answer did not generate — the model call failed. Retry from the timing panel above; your evidence is kept."
        : "Generating the answer — the evidence is ready below. This usually takes 5 to 60 seconds."}
    </p>`;
  } else {
    body = html`<div>
      <div class="prose" id=${proseId} aria-describedby=${statusId}>
        ${renderProse(run.answer_text, run)}
      </div>
      <div class="meta">
        <span>engine <b>${run.engine}</b></span>
        <span>cost <b>$${(run.cost_usd || 0).toFixed(run.telemetry === "estimated" ? 4 : 2)}</b></span>
        <span>telemetry <b>${run.telemetry}</b></span>
      </div>
      <div class="ids">
        <span>request <${Copy} text=${run.request_id} className="copy-id"
          label=${`Copy request id ${run.request_id}`}>${run.request_id}<//></span>
        <span>audit <${Copy} text=${run.audit_id} className="copy-id"
          label=${`Copy audit id ${run.audit_id}`}>${run.audit_id}<//></span>
      </div>
      <div class="actions">
        <${Copy} text=${JSON.stringify(report(run), null, 2)}>Copy run as JSON<//>
        <${Copy} text=${linkFor(run)}>Copy link to this run<//>
      </div>
    </div>`;
  }

  return html`<article class="answer" aria-labelledby=${`answer-h-${run.id}`}>
    <details open=${expanded}>
      <summary>${head}</summary>
      ${body}
    </details>
  </article>`;
}
