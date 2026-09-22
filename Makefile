# Interchange — task entry points.
#
# Everything here runs offline and at $0 unless it says otherwise.

PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
PROFILE ?= rail

.PHONY: help test a2a-demo a2a-keygen a2a-accept

help:
	@echo "make test                    - the offline test gate (pytest + pytest-bdd)"
	@echo "make a2a-demo [PROFILE=rail] - two-agent A2A demo, offline, \$$0 (rail|hotel)"
	@echo "make a2a-keygen              - print a fresh ES256 signing pair for the deploy"
	@echo "make a2a-accept              - run the A2A acceptance gate"

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
