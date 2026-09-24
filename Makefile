# Interchange — task entry points.
#
# Everything here runs offline and at $0 unless it says otherwise.

PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
PROFILE ?= rail
MODE ?= hybrid
K ?= 4

.PHONY: help test a2a-demo a2a-keygen a2a-accept workbench-accept reindex eval

help:
	@echo "make test                    - the offline test gate (pytest + pytest-bdd)"
	@echo "make a2a-demo [PROFILE=rail] - two-agent A2A demo, offline, \$$0 (rail|hotel)"
	@echo "make a2a-keygen              - print a fresh ES256 signing pair for the deploy"
	@echo "make a2a-accept              - run the A2A acceptance gate"
	@echo "make workbench-accept [WB_ENGINE=stub]   - real-engine acceptance gate for /ui + /ask/stream; ~5 claude -p calls, \$$0 marginal (stub = \$$0 self-test)"
	@echo "make reindex PROFILE=vault   - build the index for PROFILE in-process (--profile); set INTERCHANGE_CHROMA_DIR to relocate the store; vault needs INTERCHANGE_VAULT_DIR only when no overlay sets its docs_dir"
	@echo "make eval PROFILE=vault      - retrieval eval for PROFILE (MODE=hybrid|dense|bm25|hybrid+links|hybrid+rerank|all K=4)"

test:
	$(PY) -m pytest -q

# Two-agent handoff over A2A: signed card, task lifecycle, cited answer, audit
# row. Mints an ephemeral key pair per run (a fresh clone has no private key),
# starts the knowledge agent, runs the requester, and always stops the server.
a2a-demo:
	@PROFILE=$(PROFILE) bash a2a_agent/demo.sh

# Mint the ES256 pair for a deployment. The private half goes into the server's
# A2A_SIGNING_KEY_PEM environment variable and NOWHERE else; the public half
# replaces a2a_agent/keys/interchange-2026-09.pub.pem, which clients pin.
a2a-keygen:
	@$(PY) -m a2a_agent.keys

a2a-accept:
	@bash scripts/a2a-accept.sh

# Real-engine acceptance gate for the browser workbench (ADR-0015): starts the
# server on the claude-code subscription engine, drives /ui + /ask + /ask/stream,
# and asserts the things the stub cannot show. ~5 `claude -p` calls, $0 marginal.
# WB_ENGINE=stub runs the mechanics at $0 (real-engine-only checks become SKIP).
workbench-accept:
	@bash scripts/workbench-accept.sh

reindex:  ## Build the index for PROFILE in-process (--profile); PROFILE=vault needs INTERCHANGE_VAULT_DIR only when no overlay sets its docs_dir
	@$(PY) interchange.py --profile $(PROFILE) --reindex
eval:     ## Retrieval eval for PROFILE: MODE=hybrid|dense|bm25|hybrid+links|hybrid+rerank|all K=4 (corpus + golden come from the profile)
	@$(PY) interchange.py --profile $(PROFILE) --eval --mode $(MODE) --k $(K)
