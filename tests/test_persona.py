"""Executable acceptance criteria for ADR-0016 slice 3: the persona follows the
corpus (per request) and the tool allow-list follows the profile.

Offline discipline (ADR-0006): no Chroma, no embeddings, no network, no subprocess.
The generation boundary is a fake engine in ``interchange.ENGINES`` that records the
system prompt in scope when it runs, and ``interchange.retrieve_detail`` is patched to
``conftest.fake_retrieval`` so the pipeline reaches generation without touching Chroma.
The overlay is pinned off by the autouse fixture in ``conftest.py``, so these read only
the committed ``profiles.yaml`` (``hotel`` carries a Demo-Hotel persona + a single
``search_docs`` tool; ``rail`` carries none, so it keeps the module default).

Placement (Slice-2 lesson): these scenarios live in their own
``features/persona.feature`` bound here with explicit ``scenario(...)`` calls, never
appended to a feature another module bulk-binds with ``scenarios()``.
"""
from __future__ import annotations

from pytest_bdd import given, parsers, scenario, then, when

import agent_sub
import interchange
from a2a_agent.profiles import load_profile
from tests.conftest import fake_retrieval


# --- scenario bindings (explicit; never bulk `scenarios()`) ----------------
@scenario("persona.feature", "The system prompt follows the corpus, not the process")
def test_system_prompt_follows_corpus():
    pass


@scenario("persona.feature", "A persona is reset after the request")
def test_persona_reset_after_request():
    pass


@scenario("persona.feature",
          "The subscription agent's allow-list contains only the profile's tools")
def test_allow_list_follows_profile():
    pass


@scenario("persona.feature", "The agent system prompt carries the profile persona")
def test_agent_system_prompt_carries_persona():
    pass


# --- Given -----------------------------------------------------------------
@given("a fake engine that records the active system prompt")
def fake_engine_records_prompt(context, monkeypatch):
    def fake(user_content):
        context["recorded_prompt"] = interchange.system_prompt()
        return {"text": "an answer [src.md]", "in": 1, "out": 1, "cost": 0.0,
                "telemetry": "estimated", "model": "stub"}

    monkeypatch.setitem(interchange.ENGINES, "api", fake)


@given(parsers.parse('the active demo profile is "{name}" with its vault dir set'))
def active_profile_with_vault(monkeypatch, tmp_path, name):
    # vault's committed docs_dir is ${INTERCHANGE_VAULT_DIR}; set it so load_profile
    # expands cleanly (no SystemExit) and returns vault's single-tool allow-list.
    monkeypatch.setenv("INTERCHANGE_VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("DEMO_PROFILE", name)


@given(parsers.parse('the active demo profile is "{name}"'))
def active_profile(monkeypatch, name):
    monkeypatch.setenv("DEMO_PROFILE", name)


# --- When ------------------------------------------------------------------
@when(parsers.parse('I answer a question on the "{corpus}" corpus'))
def answer_on_corpus(context, monkeypatch, corpus):
    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval(
            {"source": "src.md", "text": "some passage.", "chunk": 0}, corpus=corpus),
    )
    interchange.answer_detail("what is it?", engine="api", collection=corpus)


# --- Then ------------------------------------------------------------------
@then(parsers.parse('the recorded system prompt mentions "{needle}"'))
def recorded_prompt_mentions(context, needle):
    assert needle in context["recorded_prompt"]


@then("the system prompt outside any request is the module default")
def system_prompt_reset(context):
    assert interchange.system_prompt() == interchange.SYSTEM_PROMPT


@then(parsers.parse('the subscription allow-list is "{expected}"'))
def subscription_allow_list_is(expected):
    assert agent_sub.allowed_tools() == expected


@then(parsers.parse('the agent system prompt for "{name}" mentions "{needle}"'))
def agent_system_prompt_mentions(name, needle):
    assert needle in agent_sub.agent_system_prompt(load_profile(name))
