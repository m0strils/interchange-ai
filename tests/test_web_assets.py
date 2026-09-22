"""Offline guards for the vendored front-end bundle and the ``web/`` manifest.

Slice 0 of the browser workbench (ADR-0015) vendors Preact + htm + signals as
committed ES modules so the ``/ui`` page needs no build step and no runtime CDN
(CSP ``script-src 'self'``). These tests are the gate's stand-in for that
promise: integrity is pinned, no bare import specifier or external URL survives
in the shipped bytes, and no build residue (``node_modules``, ``package.json``,
``*.map`` …) slips into ``web/``. The page's JavaScript itself is exercised in a
browser, not here (ADR-0015 records that gap).
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess

import pytest

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
VENDOR = WEB / "vendor"

VENDOR_MODULES = [
    "preact.module.js",
    "hooks.module.js",
    "signals-core.module.js",
    "signals.module.js",
    "htm.module.js",
]

# The exact set of files ``web/`` is allowed to contain at this slice. Any extra
# file (build residue, an editor's .DS_Store, a stray *.map) fails the manifest
# test on purpose; later slices update this list when they add real files.
EXPECTED_MANIFEST = {
    "index.html",
    "app.css",
    "app.js",
    "state.js",
    "api.js",
    "fixture.js",
    "components/App.js",
    "components/Ask.js",
    "components/Options.js",
    "components/RunTabs.js",
    "components/Timing.js",
    "components/Ledger.js",
    "components/Slopegraph.js",
    "components/Compare.js",
    "components/Answer.js",
    "components/Passage.js",
    "components/Legend.js",
    "components/Footer.js",
    "vendor/preact.module.js",
    "vendor/hooks.module.js",
    "vendor/signals-core.module.js",
    "vendor/signals.module.js",
    "vendor/htm.module.js",
    "vendor/SHA256SUMS",
    "vendor/VERSIONS.md",
    "vendor/LICENSES.md",
}

# Forbidden bare import specifiers (no import map is shipped, so these would 404
# at runtime): every spelling the task calls out.
FORBIDDEN_SPECIFIERS = [
    'from"preact',
    'from "preact',
    'from"@preact',
    'from "@preact',
    'import"preact',
    "from'preact",
    "from '@preact",
]

# The only http:// substrings allowed in vendored bytes are the W3C XML
# namespace CONSTANTS that Preact passes to document.createElementNS for
# SVG/MathML. They are DOM-API arguments, never fetched, and cannot be removed
# without breaking SVG rendering. Every real CDN/import URL is https:// and is
# forbidden outright.
ALLOWED_HTTP_PREFIX = "http://www.w3.org/"


def _parse_sha256sums() -> dict[str, str]:
    text = (VENDOR / "SHA256SUMS").read_text()
    sums: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, name = line.split(maxsplit=1)
        sums[name.strip()] = digest
    return sums


def test_vendor_files_match_sha256sums():
    """(a) Every vendored *.js matches its pinned hash, and SHA256SUMS covers exactly them."""
    sums = _parse_sha256sums()
    on_disk = sorted(p.name for p in VENDOR.glob("*.js"))
    assert on_disk == sorted(VENDOR_MODULES), f"unexpected vendor *.js set: {on_disk}"
    assert sorted(sums) == sorted(VENDOR_MODULES), (
        f"SHA256SUMS lists {sorted(sums)}, expected {sorted(VENDOR_MODULES)}"
    )
    for name in VENDOR_MODULES:
        digest = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
        assert digest == sums[name], f"{name}: hash {digest} != pinned {sums[name]}"


@pytest.mark.parametrize("name", VENDOR_MODULES)
def test_no_bare_specifier_or_external_url(name):
    """(b) No bare preact/@preact specifier and no external URL survives in the bytes."""
    text = (VENDOR / name).read_text()

    for spec in FORBIDDEN_SPECIFIERS:
        assert spec not in text, f"{name} still contains a bare specifier: {spec!r}"

    assert "https://" not in text, f"{name} contains an https:// URL"

    # http:// only where it is a W3C namespace constant.
    idx = 0
    while True:
        idx = text.find("http://", idx)
        if idx == -1:
            break
        assert text.startswith(ALLOWED_HTTP_PREFIX, idx), (
            f"{name} contains a non-namespace http:// URL at offset {idx}"
        )
        idx += len("http://")


def test_web_dir_matches_manifest():
    """(c) web/ contains exactly the expected files — no build residue, no junk."""
    actual = {
        str(p.relative_to(WEB)).replace("\\", "/")
        for p in WEB.rglob("*")
        if p.is_file()
    }
    extra = actual - EXPECTED_MANIFEST
    missing = EXPECTED_MANIFEST - actual
    assert not extra, f"unexpected files under web/: {sorted(extra)}"
    assert not missing, f"missing expected files under web/: {sorted(missing)}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
@pytest.mark.parametrize("name", VENDOR_MODULES)
def test_vendored_module_imports_in_node(name):
    """(d) Each vendored module resolves and loads as ESM (specifier rewrite is sound)."""
    path = (VENDOR / name).resolve()
    proc = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            f"import({path.as_uri()!r}).then(()=>console.log('ok'))",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"{name} failed to import: {proc.stderr.strip()}"
    assert proc.stdout.strip() == "ok", f"{name}: unexpected output {proc.stdout!r}"
