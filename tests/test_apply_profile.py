"""Executable acceptance criteria for ADR-0016 slice 2: the configurable index
directory, ``apply_profile`` (in-process profile application), ``--profile`` in
``main()``, and the timed, cache-safe ``build_index``.

Offline discipline (ADR-0006): no Chroma on disk, no embeddings, no network. The
Chroma-touching seam (``build_index``) runs against a recording stub
``chromadb.PersistentClient`` — the pattern in ``tests/test_scored_retrieval.py``.
Every module global ``apply_profile`` rebinds, and every env var it sets, is
snapshotted by the ``guard_profile_state`` fixture and restored on teardown, so
applying a profile in one test never leaks into another.

Note on placement: these scenarios live in ``features/apply_profile.feature`` and
are bound here with explicit ``scenario(...)`` calls, rather than appended to
``features/corpus_profiles.feature``. ``tests/test_corpus_profiles.py`` binds that
feature with the bulk ``scenarios()`` call, which would also bind anything appended
there and fail for want of the step definitions (pytest-bdd resolves steps per
module — verified). A separate feature keeps that file byte-for-byte unchanged and
green. See the change report for the rationale.
"""
from __future__ import annotations

import os
import pathlib
import re

import chromadb
import pytest
from pytest_bdd import given, parsers, scenario, then, when

import interchange


# --- fixtures --------------------------------------------------------------
@pytest.fixture
def guard_profile_state(monkeypatch):
    """Snapshot the module globals ``apply_profile`` rebinds and the env vars it
    sets, so monkeypatch teardown restores them no matter what the code under test
    did to them (``apply_profile`` writes ``os.environ`` and rebinds globals)."""
    for attr in ("DOCS_DIR", "COLLECTION", "GOLDEN_PATH",
                 "PROFILE_RETRIEVAL", "PROFILE_TOOLS"):
        monkeypatch.setattr(interchange, attr, getattr(interchange, attr))
    for key in ("INTERCHANGE_COLLECTION", "INTERCHANGE_DOCS_DIR",
                "INTERCHANGE_GOLDEN", "INTERCHANGE_IGNORE", "DEMO_PROFILE"):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)
    return None


class _RecordingCol:
    """A stub Chroma collection that records the single ``add()`` build_index makes."""

    def __init__(self):
        self.added = None

    def add(self, ids=None, documents=None, metadatas=None):
        self.added = {"ids": ids, "documents": documents, "metadatas": metadatas}


class _RecordingClient:
    """A stub ``chromadb.PersistentClient``: delete is a no-op, create hands back a
    fresh recording collection (the pattern from tests/test_scored_retrieval.py)."""

    last = None

    def __init__(self, path=None):
        pass

    def delete_collection(self, name):
        pass

    def create_collection(self, name):
        _RecordingClient.last = _RecordingCol()
        return _RecordingClient.last


# --- scenario bindings -----------------------------------------------------
@scenario("apply_profile.feature",
          "The index directory is configurable and defaults to the repo's .chroma")
def test_chroma_dir_from_env():
    pass


@scenario("apply_profile.feature",
          "--profile selects corpus, collection and golden set for one process")
def test_apply_profile_selects():
    pass


@scenario("apply_profile.feature",
          "The indexing summary reports elapsed seconds and clears the snapshot cache")
def test_build_index_timed_and_cache_safe():
    pass


# --- Scenario 1: chroma_dir_from_env ---------------------------------------
@then(parsers.parse('chroma_dir_from_env with no override ends with the repo\'s "{tail}"'))
def chroma_default(tail):
    got = interchange.chroma_dir_from_env({})
    repo = pathlib.Path(interchange.__file__).parent
    assert got == str(repo / ".chroma")
    assert got.endswith("/" + tail)


@then("chroma_dir_from_env honours an expanded INTERCHANGE_CHROMA_DIR")
def chroma_expanded():
    got = interchange.chroma_dir_from_env({"INTERCHANGE_CHROMA_DIR": "~/x/chroma"})
    assert got == os.path.expanduser("~/x/chroma")
    assert os.path.isabs(got)


@then("the module CHROMA_DIR equals chroma_dir_from_env of the environment")
def chroma_module_matches():
    assert interchange.CHROMA_DIR == interchange.chroma_dir_from_env()


# --- Scenario 2: --profile / apply_profile ---------------------------------
@given(parsers.parse('an overlay defining a "{name}" profile with golden "{golden}"'))
def overlay_named_golden(tmp_path, monkeypatch, context, name, golden):
    overlay = tmp_path / "profiles.yaml"
    overlay.write_text(
        f"{name}:\n  collection: {name}\n  docs_dir: /tmp/{name}\n  golden: {golden}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INTERCHANGE_PROFILES", str(overlay))
    context["golden_input"] = golden


@when(parsers.parse('I apply the "{name}" profile'))
def apply_named(guard_profile_state, context, name):
    context["applied"] = interchange.apply_profile(name)


@then(parsers.parse('interchange DOCS_DIR ends with "{tail}"'))
def docs_dir_ends(tail):
    assert str(interchange.DOCS_DIR).endswith(tail)


@then(parsers.parse('interchange COLLECTION is "{value}"'))
def collection_is(value):
    assert interchange.COLLECTION == value


@then(parsers.parse('active_collection is "{value}"'))
def active_collection_is(value):
    assert interchange.active_collection() == value


@then(parsers.parse('os.environ {key} is "{value}"'))
def environ_is(key, value):
    assert os.environ[key] == value


@then(parsers.parse('PROFILE_TOOLS is "{tools}"'))
def profile_tools_is(tools):
    want = [t.strip() for t in tools.split(",") if t.strip()]
    assert interchange.PROFILE_TOOLS == want


@then(parsers.parse('PROFILE_RETRIEVAL mode is "{mode}"'))
def profile_retrieval_mode_is(mode):
    assert interchange.PROFILE_RETRIEVAL["mode"] == mode


@then("GOLDEN_PATH is the expanded journal golden")
def golden_expanded(context):
    assert interchange.GOLDEN_PATH == pathlib.Path(
        os.path.expanduser(context["golden_input"]))


@then(parsers.parse('GOLDEN_PATH is the repo\'s "{rel}"'))
def golden_is_repo(rel):
    repo = pathlib.Path(interchange.__file__).parent
    assert interchange.GOLDEN_PATH == repo / rel


# --- Scenario 3: build_index timing + cache drop ---------------------------
@given("a temporary corpus of two notes and a recording Chroma client")
def tmp_corpus(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("# Note A\n\nHello world alpha.\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Note B\n\nHello world beta.\n", encoding="utf-8")
    monkeypatch.setattr(interchange, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(chromadb, "PersistentClient", _RecordingClient)


@given("the snapshot cache holds a sentinel for the active collection")
def seed_snapshot_cache(context, request):
    key = interchange.active_collection()
    context["cache_key"] = key
    interchange._SNAP_CACHE[key] = "SENTINEL"
    request.addfinalizer(lambda: interchange._SNAP_CACHE.pop(key, None))


@when("I build the index")
def build_the_index(context):
    context["summary"] = interchange.build_index()


@then("the summary reports two chunks and elapsed seconds")
def summary_reports_seconds(context):
    assert re.search(r"Indexed 2 chunks from 2 files -> .* in \d+\.\d s",
                     context["summary"]), context["summary"]


@then("the snapshot cache no longer holds the active collection")
def cache_cleared(context):
    assert context["cache_key"] not in interchange._SNAP_CACHE


# --- Plain-pytest units: --profile in main() -------------------------------
def test_main_applies_profile_before_audit(monkeypatch, guard_profile_state, capsys):
    """main() applies the profile before the --audit branch runs."""
    import enterprise

    monkeypatch.setattr(enterprise, "audit_summary", lambda: "ok")
    monkeypatch.setattr("sys.argv", ["interchange.py", "--profile", "hotel", "--audit"])
    interchange.main()
    assert interchange.COLLECTION == "hotel"
    assert capsys.readouterr().out.strip() == "ok"


def test_explicit_golden_wins_over_profile(monkeypatch, guard_profile_state):
    """An explicit --golden beats the profile's golden; without it the profile's wins."""
    captured = {}

    def fake_run_eval(*args, **kwargs):
        captured["golden"] = kwargs.get("golden_path")
        return {"n": 0, "hits": 0, "hit_at_1": 0, "near_miss": 0, "absent": 0}

    monkeypatch.setattr(interchange, "run_eval", fake_run_eval)

    monkeypatch.setattr(
        "sys.argv",
        ["interchange.py", "--profile", "rail", "--eval", "--golden", "/tmp/x.jsonl"])
    interchange.main()
    assert captured["golden"] == "/tmp/x.jsonl"

    monkeypatch.setattr("sys.argv", ["interchange.py", "--profile", "rail", "--eval"])
    interchange.main()
    repo = pathlib.Path(interchange.__file__).parent
    assert captured["golden"] == repo / "eval" / "golden.jsonl"
