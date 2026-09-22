// Top-level layout. Left column: timing ledger, evidence, score legend. Right
// column: the stacked answer(s) and the passage reader. Cold start shows the
// example questions and one static example row; Compare replaces the work grid
// with two ledgers side by side. One design system, inherited from
// site/index.html; the memorable element is the slopegraph, everything else quiet.
//
// LIVE by default (state.js). The "Fixture data" banner and the fixture switcher
// appear only with `?state=`; the header and controls otherwise render off
// `/options`.

import {
  html, runs, activeRun, activeRunId, coldStart, compareWith, corpus,
  selected, sessionSpend, jev, stateName, examples, query,
  fixtureMode, options, optionsError, apiKey, answerFromSelected,
} from "../state.js";
import { setApiKey } from "../api.js";
import { Ask } from "./Ask.js";
import { RunTabs } from "./RunTabs.js";
import { Timing } from "./Timing.js";
import { Ledger } from "./Ledger.js";
import { Legend } from "./Legend.js";
import { Answer } from "./Answer.js";
import { Passage } from "./Passage.js";
import { Compare } from "./Compare.js";
import { Footer } from "./Footer.js";
import { STATES, hits as fxHits, scoring as fxScoring } from "../fixture.js";

// One passage, shown at cold start so the slopegraph reads before any run.
const SAMPLE = fxHits[0];
const SAMPLE_SCORING = fxScoring;

function toggleTheme() {
  const root = document.documentElement;
  let cur = root.getAttribute("data-theme");
  if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  const next = cur === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", next);
  try {
    localStorage.setItem("interchange-theme", next);
  } catch (_) {
    /* storage blocked — the toggle still works for this view */
  }
}

function Header() {
  const spend = sessionSpend.value;
  const o = options.value;
  const corpora = o && o.corpora.allowed.length ? o.corpora.allowed : ["edi", "hotel"];
  const engine = o ? o.engine : fixtureMode ? "stub" : "…";
  const idx = o ? o.index : null;
  const authReq = o ? o.auth_required : false;
  const corpusLocked = o ? o.corpora.locked : false;
  const corpusReason = (o && o.corpora.reason) || "corpus is locked by policy";

  return html`<header class="bar">
    <div class="wrap">
      <span class="brand">Interchange workbench</span>
      ${idx && idx.collection &&
      html`<span class="field stat idx" title="Active index">index
        <b>${idx.collection}</b> ${idx.chunks != null ? `${idx.chunks} chunks` : ""}</span>`}
      <span class="spacer"></span>
      <label class="field">corpus
        <select value=${corpus.value} disabled=${corpusLocked}
          aria-describedby=${corpusLocked ? "corpus-locked" : undefined}
          onChange=${(e) => (corpus.value = e.target.value)}>
          ${corpora.map((c) => html`<option value=${c}>${c}</option>`)}
        </select>
        ${corpusLocked &&
        html`<span class="inline-note" id="corpus-locked" role="note">${corpusReason}</span>`}
      </label>
      <span class="field stat">engine <b>${engine}</b></span>
      ${authReq &&
      html`<label class="field key">key
        <input type="password" autocomplete="off" spellcheck="false" value=${apiKey.value}
          aria-label="API key (required on this host)"
          onInput=${(e) => { apiKey.value = e.target.value; setApiKey(e.target.value); }} />
      </label>`}
      ${spend > 0 &&
      html`<span class="field stat spend" title="Metered spend this session (Jev)">
        spent <b>$${spend.toFixed(4)}</b></span>`}
      <button class="toggle" type="button" onClick=${toggleTheme}
        aria-label="Switch between light and dark theme">theme</button>
    </div>
  </header>`;
}

/** The honest "this is a fixture" banner, with a switcher so every state is one click away. */
function FixtureBanner() {
  return html`<div class="fixture-note">
    <div class="wrap">
      <span class="fx-lead">Fixture data — <b>${stateName}</b>, not a live run.</span>
      <nav class="fx-switch" aria-label="Fixture states">
        ${STATES.map(
          (s) => html`<a href=${`?state=${s}`} aria-current=${s === stateName ? "true" : "false"}>${s}</a>`
        )}
      </nav>
    </div>
  </div>`;
}

/** Cold start: an invitation to act, the example questions, and one legible sample row. */
function ColdStart() {
  const ex = examples.value;
  return html`<section class="cold" aria-labelledby="cold-h">
    <p class="cold-lead" id="cold-h">Ask a question to see the evidence the answer is built on.</p>
    ${ex.length > 0 &&
    html`<div class="cold-ex" aria-label="Example questions">
      ${ex.map(
        (q) => html`<button class="chip" type="button" onClick=${() => (query.value = q)}>${q}</button>`
      )}
    </div>`}
    <p class="cold-note">
      Every answer arrives with its ranked evidence. This is one example row — the
      rank path reads dense → bm25 → fused → rerank, so you can see which passage
      each stage preferred before you trust the answer.
    </p>
    <${Ledger} run=${{ hits: [SAMPLE], scoring: SAMPLE_SCORING, cited: [] }} sample=${true} />
  </section>`;
}

export function App() {
  const run = activeRun.value;
  const comparing = compareWith.value != null && runs.value.length >= 2;
  const nSel = selected.value.size;

  return html`<div>
    <${Header} />
    ${fixtureMode && html`<${FixtureBanner} />`}
    ${optionsError.value &&
    html`<div class="server-down" role="alert">
      <div class="wrap">The server is not reachable. The controls are disabled until it responds.</div>
    </div>`}

    <main class="wrap" id="top">
      <${Ask} />
      ${coldStart.value
        ? html`<${ColdStart} />`
        : html`
          <${RunTabs} />
          ${comparing
            ? html`<${Compare} />`
            : html`<div class="work">
                <div class="left">
                  <${Timing} run=${run} />
                  <${Ledger} run=${run} />
                  <${Legend} scoring=${run.scoring} />
                </div>
                <div class="right">
                  <div class="answers" id="answers-anchor">
                    ${runs.value.map(
                      (r) => html`<${Answer} run=${r} expanded=${r.id === activeRunId.value} />`
                    )}
                  </div>
                  <${Passage} run=${run} />
                </div>
              </div>`}
        `}
    </main>

    <${Footer} />

    ${!coldStart.value && !comparing && nSel > 0 &&
    html`<div class="stickybar" role="region" aria-label="Grounded re-ask">
      <span class="s-count">${nSel} selected</span>
      <button class="btn btn-primary" type="button" onClick=${answerFromSelected}>Answer from selected (${nSel})</button>
      <a class="s-jump" href="#answers-anchor">jump to answer</a>
    </div>`}
  </div>`;
}
