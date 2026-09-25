// Run history tabs. A run is the unit of state; each Ask appends one and these
// tabs switch between them. Compare places two runs' ledgers side by side; it is
// enabled once a second run exists and toggles the compare view.

import { html, runs, activeRunId, compareWith } from "../state.js";

function summarise(run) {
  const eff = run.options_effective || run.options;
  const total = (run.stages || []).reduce(
    (a, s) => a + (typeof s.ms === "number" ? s.ms : 0),
    0
  );
  return { mode: eff.mode, k: eff.k, ms: total };
}

export function RunTabs() {
  const list = runs.value;
  const comparing = compareWith.value != null && list.length >= 2;
  const activeId = activeRunId.value;

  // Side A is always the active run; side B is any other run, defaulting to the
  // most recent one that is not A.
  const others = list.filter((r) => r.id !== activeId);
  const defaultB = others.length ? others[others.length - 1].id : null;

  // Clicking a run tab picks side A. While comparing it stays in compare and keeps
  // B distinct from the new A; otherwise it just switches the shown run.
  const pickRun = (id) => {
    if (comparing) {
      activeRunId.value = id;
      if (compareWith.value === id) {
        const rest = list.filter((r) => r.id !== id);
        compareWith.value = rest.length ? rest[rest.length - 1].id : null;
      }
    } else {
      activeRunId.value = id;
      compareWith.value = null;
    }
  };

  const toggleCompare = () => {
    if (list.length < 2) return;
    compareWith.value = comparing ? null : defaultB;
  };

  const compareLabel =
    list.length < 2 ? "Compare" : comparing ? "Leave compare" : `Compare runs ${activeId} and ${defaultB}`;

  return html`<nav class="runs" aria-label="Runs">
    <span class="lbl">Runs</span>
    ${list.map((run) => {
      const s = summarise(run);
      const current = activeRunId.value === run.id;
      return html`<button class="run-tab" type="button" aria-current=${current ? "true" : "false"}
          onClick=${() => pickRun(run.id)}>
        <span class="n">${run.id}</span>
        <span>${s.mode} k${s.k}</span>
        <span class="ms">${s.ms} ms</span>
      </button>`;
    })}
    <button class="run-tab compare-tab" type="button"
        disabled=${list.length < 2}
        aria-pressed=${comparing ? "true" : "false"}
        title=${list.length < 2 ? "Available once a second run exists" : "Show both ledgers side by side"}
        onClick=${toggleCompare}>${compareLabel}</button>
    ${comparing &&
    html`<label class="cmp-with">Compare with
      <select value=${compareWith.value}
        onChange=${(e) => (compareWith.value = e.target.value)}>
        ${list.filter((r) => r.id !== activeId).map(
          (r) => html`<option value=${r.id}>run ${r.id}</option>`
        )}
      </select>
    </label>`}
  </nav>`;
}
