"""Offline unit tests for the pure parts of the workbench acceptance driver
(``scripts/workbench_accept.py``): the SSE line parser, the keepalive band logic, and
the summary shape. No server, no network — the HTTP/SSE mechanics themselves are
exercised by the gate (``make workbench-accept``, incl. ``WB_ENGINE=stub`` at $0).

The driver lives under ``scripts/`` (not an importable package), so it is loaded from
its path; its ``main()`` is guarded under ``if __name__ == "__main__"`` so importing it
here runs nothing.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_DRIVER_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "workbench_accept.py"
_spec = importlib.util.spec_from_file_location("workbench_accept", _DRIVER_PATH)
wb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb)


# --- SSE line parser -------------------------------------------------------
def _feed(parser, text):
    """Feed a raw SSE blob line by line, exactly as the readline() loop would."""
    for line in text.split("\n"):
        parser.feed_line(line)


def test_sse_parser_dispatches_frame_on_blank_line():
    parser = wb.SSEParser()
    _feed(parser, 'event: stage\ndata: {"stage": "guard", "ms": 3}\n\n')
    assert parser.frames == [("stage", {"stage": "guard", "ms": 3})]


def test_sse_parser_frame_split_across_chunks_reassembles():
    """A frame whose lines arrive one at a time (as separate socket reads would give
    them) reassembles into a single frame, dispatched only on the terminating blank."""
    parser = wb.SSEParser()
    parser.feed_line("event: done")
    assert parser.frames == []           # nothing yet
    parser.feed_line('data: {"answer_text": "an 824", "request_id": "abc"}')
    assert parser.frames == []           # still buffering until the blank line
    parser.feed_line("")
    assert parser.frames == [("done", {"answer_text": "an 824", "request_id": "abc"})]


def test_sse_parser_multiline_data_joins_with_newline():
    parser = wb.SSEParser()
    parser.feed_line("event: stage")
    parser.feed_line("data: line-one")
    parser.feed_line("data: line-two")
    parser.feed_line("")
    # not JSON, so the parser keeps the raw joined text
    assert parser.frames == [("stage", {"_raw": "line-one\nline-two"})]


def test_sse_parser_counts_keepalive_comments():
    parser = wb.SSEParser()
    parser.feed_line(": keepalive")
    parser.feed_line("")                 # blank after a comment dispatches nothing
    parser.feed_line(": keepalive")
    parser.feed_line("")
    assert parser.keepalives == 2
    assert parser.frames == []           # comments are never frames


def test_sse_parser_callbacks_fire():
    got = []
    kas = []
    parser = wb.SSEParser(on_frame=lambda e, d: got.append((e, d)),
                          on_keepalive=lambda: kas.append(1))
    _feed(parser, ': keepalive\n\nevent: stage\ndata: {"stage": "retrieve"}\n\n')
    assert kas == [1]
    assert got == [("stage", {"stage": "retrieve"})]


def test_sse_parser_two_frames_in_sequence():
    parser = wb.SSEParser()
    _feed(parser,
          'event: stage\ndata: {"stage": "guard"}\n\n'
          'event: stage\ndata: {"stage": "retrieve"}\n\n')
    assert [e for e, _ in parser.frames] == ["stage", "stage"]
    assert [d["stage"] for _, d in parser.frames] == ["guard", "retrieve"]


# --- keepalive band logic --------------------------------------------------
@pytest.mark.parametrize("generate_ms, expected", [
    (0, ("exact", 0)),
    (13999, ("exact", 0)),
    (14000, ("skip", None)),      # inside the 14-16 s guard band
    (15000, ("skip", None)),
    (16000, ("skip", None)),
    (16001, ("min", 1)),
    (30000, ("min", 1)),
])
def test_keepalive_band(generate_ms, expected):
    assert wb.keepalive_band(generate_ms) == expected


# --- summary shape ---------------------------------------------------------
def test_build_summary_shape_and_pass_flag():
    summary = wb.build_summary(
        engine="claude-code", model="claude-opus-4", calls=4, generate_ms=18000,
        keepalives=1, audit_ids=["aa11", "bb22"], fails=[], skips=["AC9"])
    assert set(summary.keys()) == {
        "engine", "model", "calls", "generate_ms", "keepalives",
        "audit_ids", "pass", "fail", "skip"}
    assert summary["pass"] is True
    assert summary["fail"] == []
    assert summary["skip"] == ["AC9"]
    assert summary["audit_ids"] == ["aa11", "bb22"]


def test_build_summary_pass_false_when_any_fail():
    summary = wb.build_summary(
        engine="stub", model="", calls=0, generate_ms=0, keepalives=0,
        audit_ids=[], fails=["AC4"], skips=["AC3", "AC8a", "AC9"])
    assert summary["pass"] is False
    assert summary["fail"] == ["AC4"]
