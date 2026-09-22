// Reactive state for the workbench, and the actions that drive it live.
//
// LIVE by default: `runs` is populated from real `/ask/stream` streams and the
// controls render off `/options`. The design fixture machine (fixture.js) is
// reachable only with `?state=` in the URL — then, and only then, the page shows
// the "Fixture data" banner and seeds its signals from the chosen fixture. This
// module is the single seam between the UI components (which never touch the
// network) and api.js (which owns every wire field name).

import { h } from "./vendor/preact.module.js";
import htm from "./vendor/htm.module.js";
import { signal, computed, effect } from "./vendor/signals.module.js";
import { selectFixture, examples as fixtureExamples } from "./fixture.js";
import * as api from "./api.js";

/** htm bound to Preact's hyperscript: `html` is the template tag every component uses. */
export const html = htm.bind(h);

// --- mode selection: fixture only when ?state= is present ----------------------
function readParams() {
  try {
    return new URLSearchParams(location.search);
  } catch (_) {
    return new URLSearchParams("");
  }
}
const params = readParams();
/** True only with `?state=` — the design fixture machine (never on the live page). */
export const fixtureMode = params.has("state");
const fx = fixtureMode ? selectFixture() : null;

// Copy-link restore: a shared link may carry mode/k/rerank alongside ?q= (see
// Answer.linkFor). These seed the controls as a prefill only — never auto-run —
// and are validated against /options once it loads (clamp k, drop a disallowed
// rerank, leave a locked knob at its server default). Fixture mode ignores them.
const seedMode = fixtureMode ? null : params.get("mode");
const seedRerank = fixtureMode ? null : params.get("rerank");
const seedKRaw = fixtureMode ? null : params.get("k");
const seedK =
  seedKRaw != null && seedKRaw !== "" && Number.isFinite(Number(seedKRaw))
    ? Number(seedKRaw)
    : null;

function lsGet(key, dflt) {
  try {
    const v = localStorage.getItem(key);
    return v == null ? dflt : v;
  } catch (_) {
    return dflt;
  }
}
function lsSet(key, v) {
  try {
    localStorage.setItem(key, v);
  } catch (_) {
    /* storage blocked */
  }
}

/** Which fixture is showing (for the fixture banner's honest label), or null live. */
export const stateName = fixtureMode ? fx.stateName : null;

/** The /options document that drives the controls (null until fetched / on error). */
export const options = signal(null);
/** True when /options could not be reached — the controls render disabled. */
export const optionsError = signal(false);

// --- Run history (the unit of state) -------------------------------------------
export const runs = signal(fixtureMode ? fx.runs : []);
export const activeRunId = signal(fixtureMode ? fx.activeRunId : null);

/** The run currently shown in the ledger/answer columns, or null at cold start. */
export const activeRun = computed(
  () => runs.value.find((r) => r.id === activeRunId.value) || runs.value[0] || null
);

/** True before any run exists — the cold-start screen. */
export const coldStart = computed(() => runs.value.length === 0);

// --- Query + options (the request the next Ask would send) ----------------------
export const query = signal(fixtureMode ? fx.query : params.get("q") || "");
export const corpus = signal(fixtureMode ? fx.corpus : lsGet("interchange-corpus", "edi"));
export const mode = signal(fixtureMode ? fx.mode : seedMode || lsGet("interchange-mode", "hybrid"));
export const k = signal(fixtureMode ? fx.k : seedK != null ? seedK : 4);
export const rerank = signal(fixtureMode ? fx.rerank : seedRerank || "none");

/** Jev radio look: "policy-off" | "available" | "confirm". */
export const jev = signal(fixtureMode ? fx.jev : "policy-off");

/** The API key the operator pasted (only used/shown when /options.auth_required). */
export const apiKey = signal(api.getApiKey());

// --- Selection + reading --------------------------------------------------------
// Selection is per run: `selected` mirrors the active run's chosen passages, while
// `selByRun` remembers every run's set. A new run starts empty; switching tabs
// restores that run's set (the effect below, keyed on activeRunId).
export const selected = signal(new Set(fixtureMode ? fx.selected : []));
const selByRun = new Map();
export const activePassageId = signal(fixtureMode ? fx.activePassageId : null);
export const openLegend = signal(null);

// --- Run lifecycle --------------------------------------------------------------
export const busy = signal(fixtureMode ? fx.busy : false);
export const error = signal(fixtureMode ? fx.error : null);
/** When set, the ledgers of activeRunId and this run are shown side by side. */
export const compareWith = signal(fixtureMode ? fx.compareWith : null);
export const session = signal(fixtureMode ? fx.session : api.sessionId());

/** Cold-start example questions: from /options live, from the fixture otherwise. */
export const examples = computed(() => {
  if (fixtureMode) return fixtureExamples;
  const o = options.value;
  return o && o.examples ? o.examples : [];
});

/** Metered spend this session, summed honestly from each run's rerank frame. */
export const sessionSpend = computed(() =>
  runs.value.reduce((a, r) => a + api.readRerankSpend(r.stages), 0)
);

/** Toggle a chunk id in the `selected` set, replacing the Set so signals fire. */
export function toggleSelected(id) {
  const next = new Set(selected.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selected.value = next;
  if (activeRunId.value != null) selByRun.set(activeRunId.value, next);
}

export function clearSelected() {
  const empty = new Set();
  selected.value = empty;
  if (activeRunId.value != null) selByRun.set(activeRunId.value, empty);
}

/** Open a passage in the reader. */
export function readPassage(id) {
  activePassageId.value = id;
}

/** A citation in an answer, clicked: show the run whose answer cited this source,
 *  scroll its top matching evidence row into view, and open that passage (Read). */
export function citePassage(runId, source) {
  const r = runs.value.find((x) => x.id === runId) || activeRun.value;
  if (!r) return;
  if (activeRunId.value !== r.id) {
    activeRunId.value = r.id;
    compareWith.value = null;
  }
  const matches = (r.hits || []).filter((h) => h.source === source);
  if (!matches.length) return;
  const top = matches.reduce((best, h) => (h.final_rank < best.final_rank ? h : best), matches[0]);
  readPassage(top.id);
  try {
    const el = document.getElementById(`ev-row-${top.id}`);
    if (el) el.scrollIntoView({ block: "nearest", behavior: motionOk() ? "smooth" : "auto" });
  } catch (_) {
    /* no row element (e.g. compare view) — the passage still opens */
  }
}

/** Reduced-motion, read live so JS-driven motion paints the final state instantly. */
export function motionOk() {
  try {
    return !matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (_) {
    return true;
  }
}

// ==============================================================================
// LIVE ACTIONS — the only code here that reaches the network (via api.js).
// ==============================================================================

// Persist the two disclosed preferences (corpus, mode) as the user changes them.
if (!fixtureMode) {
  effect(() => lsSet("interchange-corpus", corpus.value));
  effect(() => lsSet("interchange-mode", mode.value));
  // Selection follows the active run: restore its stored set on a tab switch, and
  // start empty for a run never selected in (a freshly created run clears it).
  effect(() => {
    const id = activeRunId.value;
    selected.value = id != null && selByRun.has(id) ? selByRun.get(id) : new Set();
  });
}

/** Fetch /options and seed the controls. Called once on the live page. */
export async function loadOptions() {
  try {
    const o = await api.getOptions();
    options.value = o;
    optionsError.value = false;
    jev.value = o.metered.allowed ? "available" : "policy-off";
    if (o.corpora.allowed.length && !o.corpora.allowed.includes(corpus.value)) {
      corpus.value = o.corpora.default || o.corpora.allowed[0];
    }
    // A locked knob is display-only at its effective (server default) value: pin the
    // control to that default so it never shows a stale choice, and buildBody() omits
    // it from the request (sending a locked knob is a 403 knob_locked, never a downgrade).
    if (o.corpora.locked && o.corpora.default) corpus.value = o.corpora.default;
    if (o.mode.locked && o.mode.default) mode.value = o.mode.default;
    if (o.k.locked && o.k.default != null) k.value = o.k.default;
    if (o.rerank.locked) rerank.value = o.rerank.default || "none";
    // Now that the bounds/allowed sets are known, reconcile any copy-link seeds:
    // a seed for a locked knob is ignored (the server default above stands); k is
    // clamped to the index bounds; a mode/rerank the backend does not allow is dropped.
    if (seedMode && !o.mode.locked && o.mode.allowed.includes(seedMode)) mode.value = seedMode;
    if (seedK != null && !o.k.locked) {
      k.value = Math.min(Math.max(o.k.min, Math.round(seedK)), o.k.max);
    }
    if (seedRerank && !o.rerank.locked && o.rerank.allowed.includes(seedRerank)) {
      rerank.value = seedRerank;
    }
  } catch (_) {
    options.value = null;
    optionsError.value = true;
  }
}
if (!fixtureMode) loadOptions();

let controller = null;

/** Sources cited in the answer text, read off the [source] marks it renders. */
function citedSources(text) {
  const out = new Set();
  const re = /\[([^\]]+)\]/g;
  let m;
  while ((m = re.exec(text || ""))) out.add(m[1]);
  return [...out];
}

/** The AskRequest body for the current controls; k clamped to the index bound. A
 *  knob the policy locks is omitted (never sent) so the server applies its default
 *  instead of answering 403 knob_locked. */
function buildBody() {
  const o = options.value;
  const locked = (name) => !!(o && o[name] && o[name].locked);
  const body = { q: (query.value || "").trim() };
  if (corpus.value && !locked("corpora")) body.corpus = corpus.value;
  if (mode.value && !locked("mode")) body.mode = mode.value;
  const kmax = (o && o.k && o.k.max) || 20;
  const kn = Number(k.value);
  if (Number.isFinite(kn) && !locked("k")) body.k = Math.min(Math.max(1, Math.round(kn)), kmax);
  if (rerank.value && rerank.value !== "none" && !locked("rerank")) body.rerank = rerank.value;
  return body;
}

/** The pipeline stages this run expects (so a running/not-run row can be shown). */
function expectedOrder({ pinned, rerankOn }) {
  if (pinned) return ["guard", "retrieve", "generate", "ground", "done"];
  return rerankOn
    ? ["guard", "retrieve", "rerank", "generate", "ground", "done"]
    : ["guard", "retrieve", "generate", "ground", "done"];
}

/** Received frames (minus the terminal `done`) plus a synthetic running row. */
function displayStages(r) {
  const recv = r._recv || [];
  const rows = recv.slice();
  if (r._streaming) {
    const seen = new Set(recv.map((s) => s.stage));
    const next = (r._order || []).find((s) => !seen.has(s));
    if (next && next !== "done") {
      rows.push({
        stage: next, ms: "running", running: true,
        telemetry: "measured", detail: "", data: {},
      });
    }
  }
  return rows;
}

/** Apply `mut` to the run with `id`, returning a fresh object so signals fire. */
function patchRun(id, mut) {
  runs.value = runs.value.map((r) => {
    if (r.id !== id) return r;
    mut(r);
    return { ...r };
  });
}

function onStage(id) {
  return (frame) =>
    patchRun(id, (r) => {
      r._recv.push(frame);
      if (frame.stage === "retrieve") {
        if (frame.hits) r.hits = frame.hits;
        if (frame.scoring) r.scoring = frame.scoring;
        // A pinned run keeps mode "pinned" and k = the pin count (set at startRun);
        // never let the server's mode_effective/k overwrite them (U8).
        const me = api.readModeEffective(frame);
        if (me && !r.pinned) r.options_effective = { ...r.options_effective, mode: me };
        const idx = api.readIndex(frame);
        if (idx) r.index = idx;
        if (frame.data && frame.data.pinned) r.pinned = true;
      }
      r.stages = displayStages(r);
    });
}

function onDone(id) {
  return (done) => {
    patchRun(id, (r) => {
      r._streaming = false;
      r.answer_text = done.answer_text;
      r.text = done.text;
      r.grounded = done.grounded;
      r.blocked = done.blocked;
      r.sources = done.sources;
      r.engine = done.engine;
      r.model = done.model;
      r.cost_usd = done.cost_usd;
      r.telemetry = done.telemetry;
      r.request_id = done.request_id;
      r.audit_id = done.audit_id;
      if (done.scoring && Object.keys(done.scoring).length) r.scoring = done.scoring;
      r.stages = done.stages && done.stages.length ? done.stages : r._recv.slice();
      r.cited = citedSources(done.answer_text);
      r.options_effective = r.pinned
        ? { ...r.options_effective, mode: "pinned", k: r.options.k }
        : {
            ...r.options_effective,
            mode: done.mode_effective || r.options_effective.mode,
            k: done.k != null ? done.k : r.options_effective.k,
          };
    });
    busy.value = false;
    controller = null;
  };
}

function onError(id) {
  return (err) => {
    busy.value = false;
    controller = null;
    if (err.midStream) {
      // Evidence is kept; the failing stage row offers Retry; the rest are not run.
      patchRun(id, (r) => {
        r._streaming = false;
        const seen = new Set((r._recv || []).map((s) => s.stage));
        const order = r._order || [];
        const rows = (r._recv || []).filter((s) => s.stage !== "done");
        const failedStage = order.find((s) => !seen.has(s) && s !== "done");
        if (failedStage) {
          rows.push({
            stage: failedStage, ms: null, failed: true,
            telemetry: "measured", detail: err.message, data: {},
          });
          for (const s of order.slice(order.indexOf(failedStage) + 1)) {
            if (s !== "done") {
              rows.push({ stage: s, ms: null, notRun: true, telemetry: "measured", detail: "", data: {} });
            }
          }
        }
        r.stages = rows;
        r.error = { code: err.code, message: err.message, stage: failedStage, retry: true };
      });
      error.value = { code: err.code, message: err.message, stage: err.code, retry: true, midStream: true };
      return;
    }
    // Pre-stream failure, placed by cause.
    if (err.status === 400 && err.detail && err.detail.blocked) {
      patchRun(id, (r) => {
        r._streaming = false;
        r.blocked = err.detail.blocked;
      });
      return;
    }
    // No evidence to keep — drop the empty run and surface the error at the control.
    runs.value = runs.value.filter((r) => r.id !== id || (r._recv && r._recv.length));
    if (err.status === 429) error.value = { ...err, code: err.code || "busy", countdown: err.retry_after || 5 };
    else error.value = err;
  };
}

function startRun({ q, pins, pinnedOn }) {
  const id = String(runs.value.length + 1);
  const requested = {
    corpus: corpus.value, mode: pins ? "pinned" : mode.value,
    k: pins ? pins.length : Number(k.value), rerank: pins ? "none" : rerank.value,
  };
  const rerankOn = !pins && rerank.value !== "none";
  return {
    id, q,
    options: requested,
    options_effective: { ...requested },
    index: (options.value && options.value.index) || null,
    hits: [], scoring: {}, stages: [],
    answer_text: "", text: "", grounded: null, blocked: null, cited: [],
    engine: (options.value && options.value.engine) || "",
    model: "", cost_usd: 0, telemetry: null,
    request_id: null, audit_id: null,
    pinned: !!pins, pinned_on: pinnedOn || undefined,
    startedAt: Date.now(),
    _streaming: true, _recv: [],
    _order: expectedOrder({ pinned: !!pins, rerankOn }),
  };
}

/** Ask the current question with the current controls (or a pinned re-ask). */
export function ask(extra) {
  if (busy.value) return;
  const q = (extra && extra.q) || (query.value || "").trim();
  if (!q) return;
  error.value = null;
  activePassageId.value = null;

  const pins = (extra && extra.pins) || null;
  const pinnedOn = (extra && extra.pinnedOn) || 0;
  const run = startRun({ q, pins, pinnedOn });
  runs.value = [...runs.value, run];
  activeRunId.value = run.id;
  compareWith.value = null;
  busy.value = true;

  controller = new AbortController();
  const body = pins ? { q, corpus: corpus.value, pin: pins } : buildBody();
  api.stream(body, {
    signal: controller.signal,
    apiKey: apiKey.value || undefined,
    onStage: onStage(run.id),
    onDone: onDone(run.id),
    onError: onError(run.id),
  });
}

/** Stop the in-flight run: abort the fetch, keep completed stages and evidence. */
export function stop() {
  if (controller) {
    try {
      controller.abort();
    } catch (_) {
      /* already gone */
    }
    controller = null;
  }
  busy.value = false;
  const id = activeRunId.value;
  patchRun(id, (r) => {
    if (r._streaming) {
      r._streaming = false;
      r.stages = (r._recv || []).filter((s) => s.stage !== "done");
      r.stopped = true;
    }
  });
}

/** Re-issue the current question with exactly one option changed (a variant chip). */
export function reissueVariant(opts) {
  if ("mode" in opts) mode.value = opts.mode;
  if ("k" in opts) k.value = opts.k;
  if ("rerank" in opts) rerank.value = opts.rerank;
  ask();
}

/** "Answer from selected": a pinned re-ask on the ticked hits, same question. */
export function answerFromSelected() {
  const cur = activeRun.value;
  if (!cur) return;
  const pins = [];
  for (const id of selected.value) {
    const hit = (cur.hits || []).find((h) => h.id === id);
    if (hit && hit.pin) pins.push(api.pinRef(hit));
  }
  if (!pins.length) return;
  ask({ q: cur.q, pins, pinnedOn: pins.length });
}

/** Retry the current question after a mid-stream failure. */
export function retry() {
  ask();
}
