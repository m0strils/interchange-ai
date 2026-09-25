"""The launchd nightly-reindex template and its installer (ADR-0016 freshness
sub-decision).

Offline and free: these checks read the committed template and installer only —
no ``launchctl``, no filesystem install. They assert the template is valid,
home-path-free property list that yields the right Label and reindex command once
substituted, and that ``install.sh`` is a runnable script wiring every placeholder
the template declares.
"""
from __future__ import annotations

import os
import plistlib
import re
import stat
from pathlib import Path

LAUNCHD_DIR = Path(__file__).resolve().parent.parent / "scripts" / "launchd"
TEMPLATE = LAUNCHD_DIR / "ai.interchange.reindex.plist.example"
INSTALL = LAUNCHD_DIR / "install.sh"

# The placeholders the template declares, as the installer's regex derives them.
PLACEHOLDER_RE = re.compile(r"__[A-Z]+__")

DUMMIES = {
    "__PROFILE__": "brain",
    "__REPO__": "/tmp/repo",
    "__CHROMA__": "/tmp/chroma",
    "__PROFILES__": "/tmp/profiles.yaml",
    "__LOG__": "/tmp/reindex.log",
}


def _substituted() -> str:
    text = TEMPLATE.read_text()
    for key, value in DUMMIES.items():
        text = text.replace(key, value)
    return text


def test_template_parses_and_yields_the_reindex_job():
    plist = plistlib.loads(_substituted().encode())
    assert plist["Label"] == "ai.interchange.reindex-brain"
    program = " ".join(plist["ProgramArguments"])
    assert "--profile brain --reindex" in program
    # nightly at 03:30, not on load
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 30}
    assert plist["RunAtLoad"] is False


def test_template_carries_no_home_path():
    raw = TEMPLATE.read_text()
    assert "/Users/" not in raw
    assert "starship" not in raw


def test_installer_is_runnable_and_wires_every_placeholder():
    assert INSTALL.exists()
    assert os.access(INSTALL, os.X_OK), "install.sh must be executable"
    mode = INSTALL.stat().st_mode
    assert mode & stat.S_IXUSR

    body = INSTALL.read_text()
    assert "set -euo pipefail" in body

    placeholders = set(PLACEHOLDER_RE.findall(TEMPLATE.read_text()))
    assert placeholders, "the template should declare __PLACEHOLDER__ tokens"
    for token in placeholders:
        assert token in body, f"install.sh does not reference {token}"
