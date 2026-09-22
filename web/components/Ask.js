// The question hero (large serif field) plus retrieval options and variant chips.
// During a run the Ask button becomes Stop; a 429 shows a live "try again"
// countdown at the control where it was caused. Ask/Stop and the variant chips
// drive the live stream through state.js — no network code lives here.

import {
  html, query, mode, k, rerank, busy, error, optionsError,
  ask, stop, reissueVariant,
} from "../state.js";
import { Options } from "./Options.js";
import { useState, useEffect } from "../vendor/hooks.module.js";

/** Live "try again in Ns" countdown for a 429 (busy / rate-limited / budget). */
function BusyNotice({ from, message }) {
  const [n, setN] = useState(from);
  useEffect(() => {
    if (n <= 0) return;
    const t = setTimeout(() => setN((v) => v - 1), 1000);
    return () => clearTimeout(t);
  }, [n]);
  return html`<p class="ask-error" role="status">
    ${message || "Busy — another run is in progress."} ${n > 0
      ? html`Try again in <b>${n}s</b>.`
      : html`Try again now.`}
  </p>`;
}

export function Ask() {
  const running = busy.value;
  const err = error.value;
  const is429 = err && (err.status === 429 || err.code === "busy" || err.countdown != null);
  const inlineErr = err && !is429 && !err.midStream;
  const [stopped, setStopped] = useState(false);
  const disabled = optionsError.value;

  const submit = () => {
    setStopped(false);
    ask();
  };
  const onKey = (e) => {
    if (e.key === "Enter" && !running && !disabled) submit();
  };
  const doStop = () => {
    stop();
    setStopped(true);
  };
  const variant = (opts) => {
    setStopped(false);
    reissueVariant(opts);
  };

  return html`<section class="ask" aria-labelledby="ask-h">
    <label class="q" id="ask-h" for="qbox">What do you want to know?</label>
    <div class="field-row">
      <input id="qbox" class="qbox" type="text" value=${query.value}
        placeholder="what is an 824?" disabled=${disabled}
        onKeyDown=${onKey}
        onInput=${(e) => (query.value = e.target.value)} />
      ${running
        ? html`<button class="btn btn-stop" type="button" onClick=${doStop}>Stop</button>`
        : html`<button class="btn btn-primary" type="button" disabled=${disabled}
            onClick=${submit}>Ask</button>`}
    </div>

    ${is429 && html`<${BusyNotice} from=${err.countdown || err.retry_after || 5} message=${err.message} />`}
    ${inlineErr &&
    html`<p class="ask-error" role="alert">${err.message}</p>`}
    ${running &&
    html`<p class="ask-hint">Running — the Ask button becomes Stop until the answer lands.</p>`}
    ${stopped && !running &&
    html`<p class="ask-hint">Stopped. The model call may still finish on the server.</p>`}

    <${Options} />

    <div class="variant-chips" aria-label="Re-run with one option changed">
      <button class="chip" type="button" disabled=${running || disabled}
        onClick=${() => variant({ mode: "bm25", rerank: "none" })}>run as bm25</button>
      <button class="chip" type="button" disabled=${running || disabled}
        onClick=${() => variant({ k: 8 })}>run with k = 8</button>
      ${rerank.value === "none"
        ? html`<button class="chip" type="button" disabled=${running || disabled}
            onClick=${() => variant({ mode: "hybrid", rerank: "cross-encoder" })}>add local rerank</button>`
        : html`<button class="chip" type="button" disabled=${running || disabled}
            onClick=${() => variant({ rerank: "none" })}>drop rerank</button>`}
    </div>
  </section>`;
}
