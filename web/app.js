// Entry point: apply the persisted theme (if any), then mount the workbench.
// No inline script in index.html keeps the CSP `script-src 'self'` clean.

import { render } from "./vendor/preact.module.js";
import { html } from "./state.js";
import { App } from "./components/App.js";

// Honour a theme the user chose on the portfolio one-pager or here before.
try {
  const saved = localStorage.getItem("interchange-theme");
  if (saved === "light" || saved === "dark") {
    document.documentElement.setAttribute("data-theme", saved);
  }
} catch (_) {
  /* storage blocked — fall back to prefers-color-scheme */
}

const root = document.getElementById("app");
render(html`<${App} />`, root);
