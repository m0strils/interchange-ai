# Vendored front-end modules

These are the exact ES-module builds the workbench (`/ui`) loads from `./vendor/`.
They are committed to the repo so the page needs **no build step and no runtime CDN**
(CSP `script-src 'self'`). Node/pnpm are **not** used; vendoring is `curl` + `sed` +
`shasum` only. Integrity is pinned in `SHA256SUMS` and checked by
`tests/test_web_assets.py`.

Vendored on **2026-09-22**.

| Package | Version | License | Source (jsDelivr) |
|---|---|---|---|
| preact | 10.29.8 | MIT | `https://cdn.jsdelivr.net/npm/preact@10.29.8/dist/preact.module.js` |
| preact (hooks) | 10.29.8 | MIT | `https://cdn.jsdelivr.net/npm/preact@10.29.8/hooks/dist/hooks.module.js` |
| @preact/signals-core | 1.14.4 | MIT | `https://cdn.jsdelivr.net/npm/@preact/signals-core@1.14.4/dist/signals-core.module.js` |
| @preact/signals | 2.11.2 | MIT | `https://cdn.jsdelivr.net/npm/@preact/signals@2.11.2/dist/signals.module.js` |
| htm | 3.1.1 | Apache-2.0 | `https://cdn.jsdelivr.net/npm/htm@3.1.1/dist/htm.module.js` |

## Exact commands

Run from a scratch directory (never inside the repo), then copy only the five
`*.module.js` files into `web/vendor/`.

```sh
# 1. Fetch each package's own dist ES-module build at the pinned version
curl -sS -o preact.module.js        "https://cdn.jsdelivr.net/npm/preact@10.29.8/dist/preact.module.js"
curl -sS -o hooks.module.js         "https://cdn.jsdelivr.net/npm/preact@10.29.8/hooks/dist/hooks.module.js"
curl -sS -o signals-core.module.js  "https://cdn.jsdelivr.net/npm/@preact/signals-core@1.14.4/dist/signals-core.module.js"
curl -sS -o signals.module.js       "https://cdn.jsdelivr.net/npm/@preact/signals@2.11.2/dist/signals.module.js"
curl -sS -o htm.module.js           "https://cdn.jsdelivr.net/npm/htm@3.1.1/dist/htm.module.js"

# 2. Rewrite bare import specifiers to relative paths (BSD sed; use 'sed -i' on GNU)
sed -i '' 's|from"preact/hooks"|from"./hooks.module.js"|g' signals.module.js
sed -i '' 's|from"@preact/signals-core"|from"./signals-core.module.js"|g' signals.module.js
sed -i '' 's|from"preact"|from"./preact.module.js"|g' signals.module.js hooks.module.js

# 3. Strip the //# sourceMappingURL trailer (no .map files are vendored)
sed -i '' 's@//# sourceMappingURL=.*$@@' preact.module.js hooks.module.js signals-core.module.js signals.module.js htm.module.js

# 4. Drop the blank line left by step 3 (minified files carry none of their own)
sed -i '' '/^$/d' preact.module.js hooks.module.js signals-core.module.js signals.module.js htm.module.js

# 5. Copy the five files into web/vendor/, then hash them
shasum -a 256 preact.module.js hooks.module.js signals-core.module.js signals.module.js htm.module.js > SHA256SUMS

# 6. Verify
shasum -a 256 -c SHA256SUMS
```

## Edits applied to the upstream bytes

Only two mechanical, byte-level edits, both required for same-origin, no-build,
no-import-map loading under CSP:

1. **Bare specifiers rewritten to relative paths** so the browser resolves them
   from `./vendor/` with no import map: `"preact"` → `"./preact.module.js"`,
   `"preact/hooks"` → `"./hooks.module.js"`,
   `"@preact/signals-core"` → `"./signals-core.module.js"`.
   (`preact.module.js`, `signals-core.module.js`, `htm.module.js` have no imports;
   `hooks.module.js` imports `preact`; `signals.module.js` imports all three.)
2. **`//# sourceMappingURL=…` trailers stripped** because the `.map` files are not
   vendored.

No other bytes are changed. In particular `preact.module.js` still contains the
three W3C XML-namespace **constants** (`http://www.w3.org/2000/svg`,
`http://www.w3.org/1999/xhtml`, `http://www.w3.org/1998/Math/MathML`) that Preact
passes to `document.createElementNS`; these are DOM API arguments, never fetched,
and must stay for SVG/MathML rendering. `tests/test_web_assets.py` forbids every
`https://` and every `http://` except these w3.org namespace URIs.
