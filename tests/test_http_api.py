"""Executable acceptance criteria for the HTTP surface (features/http_api.feature).

Same stub seams as the CLI acceptance tests — the fake engine goes into
``interchange.ENGINES["api"]`` and ``interchange.retrieve_detail`` returns a canned
passage — so these runs are offline, free and deterministic. The app is driven
in-process through ``TestClient`` (no server, no socket).

Two unit checks ride along at the bottom: the offline ``stub`` engine answers
grounded, and ``enterprise.CALLER`` lands in the audit row as ``caller``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

import app as http_app
import enterprise
import interchange
from tests.conftest import fake_retrieval, last_audit_row

scenarios("http_api.feature")


@pytest.fixture
def client() -> TestClient:
    return TestClient(http_app.app)


# --- Background ------------------------------------------------------------
@given("a fresh audit log")
def fresh_audit_log(context, isolated_audit_log, monkeypatch):
    # the surface reads the engine from the environment; pin it to the stubbed one
    monkeypatch.delenv("INTERCHANGE_ENGINE", raising=False)
    # the corpus scenario names "rail"; allow it alongside the defaults so the
    # policy allow-list (ADR-0015) does not refuse this offline REST test
    monkeypatch.setenv("INTERCHANGE_CORPORA", "edi,hotel,rail")
    context["audit_path"] = isolated_audit_log


@given(parsers.parse('the knowledge base returns a passage from "{source}"'))
def kb_returns_passage(context, monkeypatch, source):
    def fake_retrieve(question, **kwargs):
        # record which collection the pipeline was pointed at for this call
        context["collection"] = interchange.active_collection()
        return fake_retrieval(
            {"source": source, "text": "An 824 reports application errors.", "chunk": 0},
            corpus=interchange.active_collection(),
        )

    monkeypatch.setattr(interchange, "retrieve_detail", fake_retrieve)
    context["source"] = source


@given(parsers.parse('the model answers "{text}"'))
def model_answers(context, monkeypatch, text):
    def fake(user_content):
        context["engine_called"] = True
        return {"text": text, "in": 100, "out": 20, "cost": None,
                "telemetry": "measured", "model": interchange.MODEL}

    monkeypatch.setitem(interchange.ENGINES, "api", fake)
    context["engine_called"] = False


# --- When ------------------------------------------------------------------
@when(parsers.parse('I GET "{path}"'))
def i_get(context, client, path):
    context["response"] = client.get(path)


@when(parsers.parse('I GET "{path}" with question "{question}"'))
def i_get_ask(context, client, path, question):
    context["response"] = client.get(path, params={"q": question})


@when(parsers.parse('I GET "{path}" with question "{question}" and corpus "{corpus}"'))
def i_get_ask_corpus(context, client, path, question, corpus):
    context["response"] = client.get(path, params={"q": question, "corpus": corpus})


# --- Then ------------------------------------------------------------------
@then(parsers.parse("the response status is {status:d}"))
def response_status(context, status):
    assert context["response"].status_code == status, context["response"].text


@then("the health response reports the active collection")
def health_reports_collection(context):
    body = context["response"].json()
    assert body["status"] == "ok"
    assert body["collection"] == interchange.active_collection()
    assert body["engine"] == "api"


@then("the response is grounded")
def response_grounded(context):
    assert context["response"].json()["grounded"] is True


@then(parsers.parse('the response cites "{source}"'))
def response_cites(context, source):
    body = context["response"].json()
    assert f"[{source}]" in body["text"]
    assert source in body["sources"]


@then("an audit row was written with a web caller")
def audit_row_web_caller(context):
    row = last_audit_row()
    assert row["grounded"] is True
    # the web surface records a correlation label (ADR-0015), not None like the CLI
    assert row["caller"] and row["caller"].startswith("web/")


@then("the response reports a blocked reason")
def response_blocked(context):
    body = context["response"].json()
    assert body["blocked"]
    assert body["text"].startswith("🛑")
    assert context["engine_called"] is False


@then("the audit row records that the request was blocked")
def audit_row_blocked(context):
    assert last_audit_row()["blocked"]


@then(parsers.parse('the pipeline read the collection "{name}"'))
def pipeline_read_collection(context, name):
    assert context["collection"] == name


@then(parsers.parse('the response reports corpus "{corpus}"'))
def response_corpus(context, corpus):
    assert context["response"].json()["corpus"] == corpus


# --- units -----------------------------------------------------------------
def test_stub_engine_answers_grounded(monkeypatch):
    """The offline `stub` engine cites the retrieved source, so it passes the
    grounding guardrail without a network or subprocess call."""
    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval(
            {"source": "x12-overview.md",
             "text": "An 824 reports application errors.", "chunk": 0}),
    )
    detail = interchange.answer_detail("what is an 824?", engine="stub")
    assert detail["grounded"] is True
    assert "[x12-overview.md]" in detail["text"]
    assert detail["model"] == "stub"
    assert detail["telemetry"] == "estimated"
    assert detail["cost_usd"] == 0.0
    assert detail["blocked"] is None


def test_caller_is_recorded_in_the_audit_row():
    """A calling surface sets enterprise.CALLER; the audit row names it."""
    token = enterprise.CALLER.set("x")
    try:
        enterprise.audit(question="q", model="stub", sources=[], in_tokens=1,
                         out_tokens=1, latency_ms=1, grounded=True)
    finally:
        enterprise.CALLER.reset(token)
    assert last_audit_row()["caller"] == "x"
    # and it is back to None once the caller scope ends
    enterprise.audit(question="q", model="stub", sources=[], in_tokens=1,
                     out_tokens=1, latency_ms=1, grounded=True)
    assert last_audit_row()["caller"] is None


def test_post_ask_mirrors_get_and_missing_question_is_422(monkeypatch):
    """POST takes the same {q, corpus} contract; a request with no question is a
    422 from validation — it never reaches the pipeline."""
    monkeypatch.delenv("INTERCHANGE_ENGINE", raising=False)
    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval(
            {"source": "x12-overview.md",
             "text": "An 824 reports application errors.", "chunk": 0}),
    )
    monkeypatch.setitem(interchange.ENGINES, "api", interchange.ENGINES["stub"])
    client = TestClient(http_app.app)

    posted = client.post("/ask", json={"q": "what is an 824?"})
    assert posted.status_code == 200
    assert posted.json()["grounded"] is True
    assert posted.json()["corpus"] == interchange.COLLECTION

    assert client.get("/ask").status_code == 422
    assert client.post("/ask", json={}).status_code == 422
