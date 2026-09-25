// Timing ledger: an ordered list of pipeline stages with real elapsed ms and a
// hairline bar whose width IS the ms (a length encoding of a magnitude — legal,
// unlike bars for unbounded scores). Exactly one stage may show "running" with a
// live counter; a stage that never ran shows "not run"; a failed stage offers
// Retry. One aria-live region announces only the newest line. This replaces the
// pipeline-dot strip (an anti-tell).

import { html, retry } from "../state.js";
import { useState, useEffect } from "../vendor/hooks.module.js";

const LABEL = {
  guard: "guard", retrieve: "retrieve", rerank: "rerank",
  generate: "generate", ground: "ground", done: "done",
};

/** Live elapsed counter for the one running stage, ticking from the run's real
 *  start timestamp (0.0 s at the top of the run — never a hardcoded seed). Data,
 *  not decoration, so it runs under reduced motion too. */
function RunningCounter({ startedAt }) {
  const base = startedAt || Date.now();
  const [s, setS] = useState(Math.max(0, (Date.now() - base) / 1000));
  useEffect(() => {
    const t = setInterval(() => setS(Math.max(0, (Date.now() - base) / 1000)), 200);
    return () => clearInterval(t);
  }, [base]);
  return html`<span class="val running">${s.toFixed(1)} s</span>`;
}

/** The single line an aria-live region should announce for the current state. */
function newestLine(rows) {
  const running = rows.find((s) => s.running);
  if (running) return `${LABEL[running.stage] || running.stage} running`;
  const failed = rows.find((s) => s.failed);
  if (failed) return `${LABEL[failed.stage] || failed.stage} failed`;
  const blocked = rows.find((s) => s.blocked);
  if (blocked) return "question blocked";
  return "Answer ready";
}

export function Timing({ run }) {
  const stages = run.stages || [];
  // "done" carries the audit/request ids, not a duration — keep it out of the bars.
  const rows = stages.filter((s) => s.stage !== "done");
  const maxMs = Math.max(1, ...rows.map((s) => (typeof s.ms === "number" ? s.ms : 0)));

  return html`<section aria-labelledby="timing-h">
    <h2 class="h-sm" id="timing-h">Timing</h2>
    <div class="sr-live" role="status" aria-live="polite">${newestLine(rows)}</div>
    <ol class="ledger">
      ${rows.map((s) => {
        const isNum = typeof s.ms === "number";
        const ms = isNum ? s.ms : 0;
        const pct = s.running ? 100 : Math.max(2, Math.round((ms / maxMs) * 100));
        const showBar = isNum && !s.blocked;
        return html`<li class=${s.failed ? "is-failed" : ""}>
          <span class="stage">${LABEL[s.stage] || s.stage}</span>
          ${s.running
            ? html`<${RunningCounter} startedAt=${run.startedAt} />`
            : s.failed
              ? html`<span class="val failed">failed</span>`
              : s.notRun
                ? html`<span class="val none">not run</span>`
                : s.blocked
                  ? html`<span class="val blocked">blocked</span>`
                  : html`<span class="val">${ms} ms</span>`}
          <span class="track" aria-hidden="true">
            ${showBar && html`<span class="bar" style=${`width:${pct}%`}></span>`}
          </span>
          ${s.running && s.stage === "generate" &&
          html`<span class="hint">usually 5 to 60 seconds</span>`}
          ${s.failed &&
          html`<span class="hint fail-row">
            The model call failed — the evidence below is kept.
            <button class="link-btn" type="button" onClick=${retry}>Retry</button>
          </span>`}
          ${s.blocked &&
          html`<span class="hint">${s.detail}</span>`}
        </li>`;
      })}
    </ol>
  </section>`;
}
