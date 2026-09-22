// The single seam to the backend contract (ADR-0015). Every read of a server
// field name lives HERE, so a later rename of a wire field (a reviewer may move
// one) touches this file only — the components and state never spell a contract
// field. No EventSource anywhere: fetch + ReadableStream + AbortController, so
// one idle tab never auto-reconnects a fresh generation (review row 3). The UI
// never calls the non-stream /ask.

const SESSION_KEY = "interchange-session";
const APIKEY_KEY = "interchange-apikey";

/** A stable per-tab session uuid kept in sessionStorage (correlation, not identity). */
export function sessionId() {
  try {
    let s = sessionStorage.getItem(SESSION_KEY);
    if (!s) {
      s =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `s-${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
      sessionStorage.setItem(SESSION_KEY, s);
    }
    return s;
  } catch (_) {
    return "anon";
  }
}

/** The API key the operator pasted (only sent when /options.auth_required). */
export function getApiKey() {
  try {
    return sessionStorage.getItem(APIKEY_KEY) || "";
  } catch (_) {
    return "";
  }
}

export function setApiKey(v) {
  try {
    if (v) sessionStorage.setItem(APIKEY_KEY, v);
    else sessionStorage.removeItem(APIKEY_KEY);
  } catch (_) {
    /* storage blocked */
  }
}

// --- field extractors: the ONLY place that spells wire field names -----------

/** Normalise the /options document into the shape the controls render off. */
export function readOptions(doc) {
  const d = doc || {};
  const corpora = d.corpora || {};
  const mode = d.mode || {};
  const rerank = d.rerank || {};
  const k = d.k || {};
  const metered = d.metered || {};
  const index = d.index || {};
  // Every knob shares one envelope: choices carry {allowed, default, locked, reason};
  // the k range carries {min, max, default, locked, reason}; rerank adds `unavailable`.
  // `reason` is null unless the knob is locked (e.g. "k is locked by policy").
  return {
    corpora: {
      allowed: corpora.allowed || [],
      default: corpora.default || "",
      locked: !!corpora.locked,
      reason: corpora.reason || null,
    },
    mode: {
      allowed: mode.allowed || [],
      default: mode.default || "hybrid",
      locked: !!mode.locked,
      reason: mode.reason || null,
    },
    rerank: {
      allowed: rerank.allowed || ["none"],
      default: rerank.default || "none",
      locked: !!rerank.locked,
      reason: rerank.reason || null,
      unavailable: rerank.unavailable || {},
    },
    k: {
      min: k.min != null ? k.min : 1,
      max: k.max != null ? k.max : 20,
      default: k.default != null ? k.default : 4,
      locked: !!k.locked,
      reason: k.reason || null,
    },
    metered: {
      allowed: !!metered.allowed,
      budget_usd: metered.budget_usd,
      spent_today_usd: metered.spent_today_usd,
      price_per_judgment_usd: metered.price_per_judgment_usd,
      window: metered.window,
    },
    index: {
      collection: index.collection,
      chunks: index.chunks,
      space: index.space,
    },
    engine: d.engine,
    auth_required: !!d.auth_required,
    ui: d.ui !== false,
    examples: d.examples || [],
  };
}

/** A stage frame from the stream, with hits/scoring lifted off the retrieve frame. */
export function readStage(frame) {
  const f = frame || {};
  return {
    stage: f.stage,
    ms: f.ms,
    telemetry: f.telemetry,
    detail: f.detail,
    data: f.data || {},
    hits: f.hits || null,
    scoring: f.scoring || null,
  };
}

/** The effective retrieval mode a retrieve frame reports (drives options_effective). */
export function readModeEffective(retrieveFrame) {
  return (retrieveFrame && retrieveFrame.data && retrieveFrame.data.mode_effective) || null;
}

/** The retrieve frame's index descriptor {collection, chunks, space}. */
export function readIndex(retrieveFrame) {
  return (retrieveFrame && retrieveFrame.data && retrieveFrame.data.index) || null;
}

/** The metered spend a rerank frame priced, in USD (0 for a $0 local reranker). */
export function readRerankSpend(stages) {
  const r = (stages || []).find((s) => s.stage === "rerank");
  return r && r.data ? r.data.estimated_usd || 0 : 0;
}

/** The final AskResponse (the `done` frame) mapped to the run's fields. */
export function readDone(body) {
  const b = body || {};
  return {
    answer_text: b.answer_text || "",
    text: b.text || "",
    grounded: b.grounded,
    blocked: b.blocked || null,
    sources: b.sources || [],
    engine: b.engine,
    model: b.model,
    cost_usd: b.cost_usd || 0,
    telemetry: b.telemetry,
    mode: b.mode,
    mode_effective: b.mode_effective,
    k: b.k,
    pinned: !!b.pinned,
    corpus: b.corpus,
    request_id: b.request_id,
    audit_id: b.audit_id,
    stages: b.stages || [],
    scoring: b.scoring || {},
  };
}

/** The {id, token} pin capability for a selected hit (token is the hit's `pin`). */
export function pinRef(hit) {
  return { id: hit.id, token: hit.pin };
}

/** A mid-stream error frame → the typed error object the UI places by cause. */
export function readErrorFrame(data) {
  const d = data || {};
  return {
    status: null,
    code: d.code || "internal",
    message: d.message || "The pipeline failed.",
    correlation_id: d.correlation_id || null,
    retry_after: null,
    detail: null,
    midStream: true,
  };
}

const HTTP_FALLBACK = {
  0: "The server is not reachable.",
  400: "The request was refused.",
  403: "This request is not permitted by policy.",
  422: "One of the options is not valid.",
  429: "The server is busy.",
  500: "An internal error occurred.",
  503: "The service is unavailable.",
};

/** A non-2xx HTTP response → the typed error object {status, code, message, ...}. */
async function errorFrom(res) {
  const status = res.status;
  const retryHeader = res.headers.get("retry-after");
  let payload = null;
  try {
    payload = await res.json();
  } catch (_) {
    /* not JSON */
  }
  const p = payload || {};
  // ErrorResponse {code,message,correlation_id}; a guardrail 400 nests {detail:{blocked}};
  // pydantic 422 nests {detail:[...]}. Read every spelling here, once.
  const nested = p.detail && !Array.isArray(p.detail) ? p.detail : {};
  const code = p.code || nested.code || `http_${status}`;
  const message = p.message || nested.message || HTTP_FALLBACK[status] || "Request failed.";
  const correlation_id = p.correlation_id || nested.correlation_id || null;
  const retry_after =
    p.retry_after != null
      ? p.retry_after
      : retryHeader
        ? Number(retryHeader)
        : null;
  return {
    status,
    code,
    message,
    correlation_id,
    retry_after,
    detail: p.detail != null ? p.detail : p,
  };
}

// --- transport ---------------------------------------------------------------

/** GET /options. Throws the typed error object on any failure (caller renders it). */
export async function getOptions() {
  let res;
  try {
    res = await fetch("/options", { headers: { accept: "application/json" } });
  } catch (_) {
    throw {
      status: 0,
      code: "unreachable",
      message: HTTP_FALLBACK[0],
      correlation_id: null,
      retry_after: null,
      detail: null,
    };
  }
  if (!res.ok) throw await errorFrom(res);
  return readOptions(await res.json());
}

/** Split one SSE frame (already delimited on a blank line) and dispatch it. */
function dispatchFrame(raw, { onStage, onDone, onError }) {
  let event = "message";
  const dataLines = [];
  for (const line of raw.split("\n")) {
    if (!line || line.startsWith(":")) continue; // blank or `: keepalive` comment
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (!dataLines.length) return;
  let data;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch (_) {
    return; // a partial/garbled frame — skip, never throw into the reader loop
  }
  if (event === "stage") onStage && onStage(readStage(data));
  else if (event === "done") onDone && onDone(readDone(data));
  else if (event === "error") onError && onError(readErrorFrame(data));
}

/**
 * POST /ask/stream and dispatch the Server-Sent Events.
 *   body  — the AskRequest object ({q, corpus?, mode?, k?, rerank?, pin?}).
 *   opts  — { signal, onStage, onDone, onError, apiKey }.
 * Completion is keyed on the `done` event (the server also emits a `stage`
 * frame whose stage=="done"; that one is just another ledger row). An
 * AbortError (Stop, or a disconnect) resolves cleanly with no onError.
 */
export async function stream(body, { signal, onStage, onDone, onError, apiKey } = {}) {
  const headers = { "content-type": "application/json", "x-session": sessionId() };
  const key = apiKey != null ? apiKey : getApiKey();
  if (key) headers["x-api-key"] = key;

  let res;
  try {
    res = await fetch("/ask/stream", {
      method: "POST",
      headers,
      body: typeof body === "string" ? body : JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e && e.name === "AbortError") return; // clean stop before the stream opened
    onError &&
      onError({
        status: 0,
        code: "unreachable",
        message: HTTP_FALLBACK[0],
        correlation_id: null,
        retry_after: null,
        detail: null,
      });
    return;
  }

  if (!res.ok) {
    onError && onError(await errorFrom(res));
    return;
  }
  if (!res.body || !res.body.getReader) {
    // No streaming body (a proxy buffered it, say) — parse the whole text at once.
    const text = await res.text();
    for (const chunk of text.split("\n\n")) if (chunk.trim()) dispatchFrame(chunk, { onStage, onDone, onError });
    return;
  }

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      // Frames are blank-line delimited; tolerate frames split across chunks.
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        dispatchFrame(frame, { onStage, onDone, onError });
      }
    }
    buf += dec.decode();
    if (buf.trim()) dispatchFrame(buf, { onStage, onDone, onError });
  } catch (e) {
    if (e && e.name === "AbortError") return; // Stop mid-stream: keep what arrived
    onError &&
      onError({
        status: 0,
        code: "stream_broken",
        message: "The connection was interrupted.",
        correlation_id: null,
        retry_after: null,
        detail: null,
        midStream: true,
      });
  }
}
