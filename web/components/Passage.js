// The reading pane. "Read" (the View passage button) focuses a passage here. On
// desktop it sits inline in the right column; under 600px it rises as a
// dismissible bottom sheet with a backdrop. It is a focus target (tabindex="-1")
// so keyboard users land on it; Esc closes, and so does the backdrop.

import { html, activePassageId } from "../state.js";
import { useRef, useEffect } from "../vendor/hooks.module.js";

export function Passage({ run }) {
  const ref = useRef(null);
  const hit = (run.hits || []).find((h) => h.id === activePassageId.value) || null;

  useEffect(() => {
    if (hit && ref.current) ref.current.focus();
  }, [hit && hit.id]);

  const close = () => (activePassageId.value = null);
  const onKey = (e) => {
    if (e.key === "Escape") close();
  };

  return html`<div class=${`passage-wrap ${hit ? "open" : ""}`}>
    <div class="sheet-backdrop" aria-hidden="true" onClick=${close}></div>
    <section class="passage" ref=${ref} tabindex="-1"
        aria-label="Passage reader" onKeyDown=${onKey}>
      ${hit
        ? html`<div>
            <div class="ptop">
              <div>
                <div class="pid">${hit.source}:${hit.chunk}</div>
                <div class="psec">${hit.section}</div>
              </div>
              <button class="close" type="button" aria-label="Close passage"
                onClick=${close}>Close</button>
            </div>
            <p class="ptext">${hit.text}</p>
          </div>`
        : html`<p class="empty">Select View passage on any row to read the full chunk here.</p>`}
    </section>
  </div>`;
}
