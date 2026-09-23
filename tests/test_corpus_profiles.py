"""Executable acceptance criteria for corpus profiles as portable data (ADR-0016).

Gherkin lives in ``features/corpus_profiles.feature``. The behavior under test is
profile-loading only: the ``INTERCHANGE_PROFILES`` overlay merge, plus the
``persona`` / ``retrieval`` / ``tools`` accessors and ``profile_for_collection``.

Offline discipline (mirrors ``test_vault_corpus.py``): no Chroma, no embeddings,
no network. The overlay is a throwaway YAML file under ``tmp_path`` with
``INTERCHANGE_PROFILES`` monkeypatched at it (the autouse ``isolated_profiles``
fixture disables the machine's real overlay by default). Symbols are imported
inside each step, the ``test_a2a.py`` convention.
"""
from __future__ import annotations

import textwrap

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("corpus_profiles.feature")


def _write_overlay(tmp_path, monkeypatch, text: str):
    """Write an overlay YAML under tmp_path and point INTERCHANGE_PROFILES at it."""
    path = tmp_path / "profiles.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    monkeypatch.setenv("INTERCHANGE_PROFILES", str(path))
    return path


def _raw_profile(name: str) -> dict:
    """The merged profile block for ``name`` with its name attached, WITHOUT the
    ``docs_dir`` expansion ``load_profile`` does — enough for the persona /
    retrieval / tools accessors, which never read ``docs_dir``."""
    from a2a_agent.profiles import load_profiles

    return {"name": name, **load_profiles()[name]}


# --- Given -----------------------------------------------------------------
@given(parsers.parse('an overlay that sets vault docs_dir to "{docs_dir}"'))
def overlay_vault_docs_dir(context, tmp_path, monkeypatch, docs_dir):
    from a2a_agent.profiles import PROFILES_PATH

    context["committed_before"] = PROFILES_PATH.read_bytes()
    _write_overlay(tmp_path, monkeypatch, f"""
        vault:
          docs_dir: {docs_dir}
    """)


@given(parsers.parse(
    'an overlay that defines a "{name}" profile with collection "{collection}" '
    'and docs_dir "{docs_dir}"'))
def overlay_new_profile(context, tmp_path, monkeypatch, name, collection, docs_dir):
    _write_overlay(tmp_path, monkeypatch, f"""
        {name}:
          collection: {collection}
          docs_dir: {docs_dir}
    """)


@given(parsers.parse(
    'an overlay that defines a "{name}" profile with collection "{collection}", '
    'docs_dir "{docs_dir}" and retrieval mode "{mode}"'))
def overlay_new_profile_retrieval(
    context, tmp_path, monkeypatch, name, collection, docs_dir, mode):
    _write_overlay(tmp_path, monkeypatch, f"""
        {name}:
          collection: {collection}
          docs_dir: {docs_dir}
          retrieval:
            mode: {mode}
    """)


@given(parsers.parse('an overlay that sets vault ignore to "{pattern}"'))
def overlay_vault_ignore(context, tmp_path, monkeypatch, pattern):
    _write_overlay(tmp_path, monkeypatch, f"""
        vault:
          ignore:
            - "{pattern}"
    """)


@given("the overlay is disabled")
def overlay_disabled(monkeypatch):
    monkeypatch.setenv("INTERCHANGE_PROFILES", "")


@given("INTERCHANGE_PROFILES points at a nonexistent path")
def overlay_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERCHANGE_PROFILES", str(tmp_path / "does-not-exist.yaml"))


@given("INTERCHANGE_VAULT_DIR is unset")
def vault_dir_unset(monkeypatch):
    monkeypatch.delenv("INTERCHANGE_VAULT_DIR", raising=False)


@given(parsers.parse('INTERCHANGE_VAULT_DIR is set to "{value}"'))
def vault_dir_set(monkeypatch, value):
    monkeypatch.setenv("INTERCHANGE_VAULT_DIR", value)


# --- When ------------------------------------------------------------------
@when(parsers.parse('I load the "{name}" profile'))
def load_named_profile(context, name):
    from a2a_agent.profiles import load_profile

    context["profile"] = load_profile(name)


@when(parsers.parse('I try to load the "{name}" profile'))
def try_load_named_profile(context, name):
    from a2a_agent.profiles import load_profile

    try:
        context["profile"] = load_profile(name)
    except SystemExit as exc:
        context["systemexit"] = exc


@when(parsers.parse('I read the retrieval of the "{name}" profile'))
def read_retrieval(context, name):
    from a2a_agent.profiles import profile_retrieval

    try:
        context["retrieval"] = profile_retrieval(_raw_profile(name))
    except ValueError as exc:
        context["valueerror"] = exc


# --- Then ------------------------------------------------------------------
@then(parsers.parse('the profile\'s docs_dir is "{docs_dir}"'))
def profile_docs_dir_is(context, docs_dir):
    assert context["profile"]["docs_dir"] == docs_dir


@then(parsers.parse('the profile\'s collection is "{collection}"'))
def profile_collection_is(context, collection):
    assert context["profile"]["collection"] == collection


@then("the committed profiles.yaml is byte-for-byte unchanged")
def committed_unchanged(context):
    from a2a_agent.profiles import PROFILES_PATH

    assert PROFILES_PATH.read_bytes() == context["committed_before"]


@then(parsers.parse('the profile\'s exported env has INTERCHANGE_COLLECTION "{value}"'))
def exported_env_collection(context, value):
    from a2a_agent.profiles import profile_env

    assert profile_env(context["profile"])["INTERCHANGE_COLLECTION"] == value


@then(parsers.parse('the profile\'s ignore list is exactly "{pattern}"'))
def ignore_list_is(context, pattern):
    assert context["profile"]["ignore"] == [pattern]


@then(parsers.parse('it exits plainly naming "{var}"'))
def exits_naming(context, var):
    assert "systemexit" in context, "expected a SystemExit"
    assert var in str(context["systemexit"])


@then(parsers.parse('the profile for collection "{collection}" is named "{name}"'))
def profile_for_collection_named(collection, name):
    from a2a_agent.profiles import profile_for_collection

    found = profile_for_collection(collection)
    assert found is not None and found["name"] == name


@then(parsers.parse('there is no profile for collection "{collection}"'))
def no_profile_for_collection(collection):
    from a2a_agent.profiles import profile_for_collection

    assert profile_for_collection(collection) is None


@then(parsers.parse('the "{name}" profile\'s tools are "{tools}"'))
def profile_tools_are(name, tools):
    from a2a_agent.profiles import profile_tools

    want = [t.strip() for t in tools.split(",") if t.strip()]
    assert profile_tools(_raw_profile(name)) == want


@then(parsers.parse('the "{name}" profile\'s retrieval is mode "{mode}" rerank none'))
def profile_retrieval_default(name, mode):
    from a2a_agent.profiles import profile_retrieval

    assert profile_retrieval(_raw_profile(name)) == {"mode": mode, "rerank": None}


@then(parsers.parse('the "{name}" profile\'s retrieval mode is "{mode}"'))
def profile_retrieval_mode(name, mode):
    from a2a_agent.profiles import profile_retrieval

    assert profile_retrieval(_raw_profile(name))["mode"] == mode


@then(parsers.parse('a ValueError names "{token}"'))
def valueerror_names(context, token):
    assert "valueerror" in context, "expected a ValueError"
    assert token in str(context["valueerror"])


@then(parsers.parse('the "{name}" profile persona mentions "{needle}"'))
def persona_mentions(name, needle):
    from a2a_agent.profiles import profile_persona

    persona = profile_persona(_raw_profile(name))
    assert persona is not None and needle in persona


@then(parsers.parse('the "{name}" profile has no persona'))
def persona_absent(name):
    from a2a_agent.profiles import profile_persona

    assert profile_persona(_raw_profile(name)) is None


# --- Plain-pytest units (overlay_path / golden expansion) ------------------
def test_overlay_path_expands_tilde(tmp_path, monkeypatch):
    from a2a_agent.profiles import overlay_path

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "custom.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("INTERCHANGE_PROFILES", "~/custom.yaml")
    assert overlay_path() == tmp_path / "custom.yaml"


def test_overlay_path_default_when_unset(tmp_path, monkeypatch):
    from a2a_agent.profiles import overlay_path

    # Env unset => the default (~/.interchange/profiles.yaml), expanded; None when
    # that file does not exist on a fresh HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("INTERCHANGE_PROFILES", raising=False)
    assert overlay_path() is None
    default = tmp_path / ".interchange" / "profiles.yaml"
    default.parent.mkdir(parents=True)
    default.write_text("{}\n", encoding="utf-8")
    assert overlay_path() == default


def test_golden_in_overlay_expands_tilde(tmp_path, monkeypatch):
    from a2a_agent.profiles import load_profile

    monkeypatch.setenv("HOME", str(tmp_path))
    overlay = tmp_path / "profiles.yaml"
    overlay.write_text(
        "journal:\n  collection: journal\n  docs_dir: /tmp/j\n  golden: ~/g.jsonl\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INTERCHANGE_PROFILES", str(overlay))
    profile = load_profile("journal")
    assert profile["golden"] == str(tmp_path / "g.jsonl")


def test_overlay_empty_string_disables(monkeypatch):
    from a2a_agent.profiles import overlay_path

    monkeypatch.setenv("INTERCHANGE_PROFILES", "")
    assert overlay_path() is None
