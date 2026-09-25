// "What this page stores" — the privacy disclosure the design plan requires
// (review row 20), as a footer popover. It states exactly what the workbench
// keeps and where, backed by the CSP the server sends. Honest by construction:
// it names storage the fixture does not even use yet.

import { html, fixtureMode } from "../state.js";
import { useState, useRef } from "../vendor/hooks.module.js";

export function Footer() {
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);

  // Esc closes the popover and returns focus to the trigger (A5, like the passage sheet).
  const onKey = (e) => {
    if (e.key === "Escape" && open) {
      setOpen(false);
      if (btnRef.current) btnRef.current.focus();
    }
  };

  return html`<footer class="foot">
    <div class="wrap">
      <div class="store-pop" onKeyDown=${onKey}>
        <button class="link-btn store-btn" type="button" ref=${btnRef} aria-expanded=${open}
          aria-controls="store-panel" onClick=${() => setOpen((v) => !v)}>
          What this page stores
        </button>
        <div id="store-panel" class="store-panel" role="region"
          aria-label="What this page stores" hidden=${!open}>
          <p>
            Your question and options are sent to this server only; nothing leaves
            the origin; the URL carries the question only when you copy a link;
            localStorage keeps <b>corpus</b> and <b>mode</b>;
            ${"sessionStorage keeps a "}<b>session id</b> (and the API key when
            required); no cookies, no analytics.
          </p>
          ${fixtureMode &&
          html`<p class="fixture-line">This fixture sends nothing over the network at all.</p>`}
        </div>
      </div>
      <span class="foot-sig">Interchange, a governed knowledge runtime</span>
    </div>
  </footer>`;
}
