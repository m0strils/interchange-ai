"""Agent-to-agent (A2A) surface for Interchange — ADR-0013.

Named ``a2a_agent`` and *not* ``a2a``: a top-level ``a2a/`` directory in the
repo root would shadow the installed ``a2a-sdk`` package for any process
started from the root, and every SDK import would break.

Modules:
  * ``keys``      — the pinned ES256 verification key, the signer's private key,
                    and the ``key_provider`` that refuses remote key fetches.
  * ``profiles``  — the demo profiles (corpus, sample question, display names).
  * ``server``    — the Agent Card, the executor, and ``mount_a2a(app, base_url)``.
  * ``requester`` — the client agent: verify the card, stream a task, print it.
"""
from __future__ import annotations

__all__ = ["keys", "profiles", "requester", "server"]
