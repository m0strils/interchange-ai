"""onnxruntime telemetry is switched off before any session exists (ADR-0018 P2 /
microsoft/onnxruntime#24579): the 1DS uploader thread otherwise races process
exit on macOS and aborts the interpreter after the eval has already printed.
Offline: asserts the import-time side effects, never creates a session."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_env_flag_is_set_on_import():
    import interchange  # noqa: F401  (already imported by conftest; the flag persists)

    assert os.environ.get("ORT_DISABLE_TELEMETRY") == "1"


def test_api_call_is_made_when_onnxruntime_is_present():
    import interchange

    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        assert interchange.ORT_TELEMETRY_DISABLED is False
        return
    assert interchange.ORT_TELEMETRY_DISABLED is True


def test_fresh_process_sets_the_flag_before_onnxruntime_loads():
    # A fresh interpreter: the env var must be set by the time onnxruntime is
    # first imported, which is the only moment it is honoured.
    code = (
        "import os, sys; sys.path.insert(0, %r); "
        "assert 'onnxruntime' not in sys.modules; import interchange; "
        "print(os.environ['ORT_DISABLE_TELEMETRY'])" % str(REPO)
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, timeout=120, env={**os.environ, "INTERCHANGE_PROFILES": ""})
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.strip() == "1"
