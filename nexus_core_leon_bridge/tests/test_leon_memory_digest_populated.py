"""
tests/test_leon_memory_digest_populated.py
================================================

§7 (`MISSION_couple_leon_nexusbrain.md`) required test: "le digest atteint
bien `apply_leon_context_digest` avant le premier tour."

The RECEIVING half of this is already covered by
`tests/test_e2e_simulated.py::test_leon_memory_digest_is_loaded_as_runtime_context_before_the_turn`
(built before D4, still green — it feeds `leon_memory_digest` in
manually, simulating what Leon now actually sends). What D4 adds is the
SENDING half, entirely in `leon_patch/server/src/core/socket-server.ts`
— TypeScript, run inside Leon's own Node process, which this Python
sandbox cannot start (no installed Leon dependency tree — see
`leon_patch/PATCH_NOTES.md`, "Validation performed", same limitation the
rest of this patch already had).

Given that constraint, this is a **source-level** test: it parses the
actual patched TypeScript (both the `leon_patch/` mirror and — since
that's the file that actually runs — the real copy under
`Nexus_Assistant/Leon AI/leon-develop/leon-develop/`) and asserts the
wiring is genuinely present and internally consistent, not just that a
comment claims it is. It is not a substitute for a real Node/`pnpm test`
run — see `leon_patch/PATCH_NOTES.md` for what that would additionally
confirm.
"""

from __future__ import annotations

import re
from pathlib import Path

_BRIDGE_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BRIDGE_ROOT.parent

_LEON_PATCH_SOCKET_SERVER = (
    _BRIDGE_ROOT / "leon_patch" / "server" / "src" / "core" / "socket-server.ts"
)
_REAL_LEON_SOCKET_SERVER = (
    _REPO_ROOT
    / "Nexus_Assistant"
    / "Leon AI"
    / "leon-develop"
    / "leon-develop"
    / "server"
    / "src"
    / "core"
    / "socket-server.ts"
)
_NEXUS_BRIDGE_CLIENT = _BRIDGE_ROOT / "leon_patch" / "server" / "src" / "core" / "nexus-bridge-client.ts"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file not found: {path}"
    return path.read_text(encoding="utf-8")


def test_leon_memory_digest_field_exists_on_the_bridge_client_options():
    src = _read(_NEXUS_BRIDGE_CLIENT)
    assert "leonMemoryDigest?: string" in src
    assert "context['leon_memory_digest'] = leonMemoryDigest" in src


def test_socket_server_imports_memory_manager():
    src = _read(_LEON_PATCH_SOCKET_SERVER)
    # Same import block as HTTP_SERVER/BRAIN/etc — from '@/core', not a
    # separate/new import path (no second way to reach Leon's memory).
    match = re.search(r"import\s*\{([^}]*)\}\s*from '@/core'", src)
    assert match, "no `from '@/core'` import block found"
    assert "MEMORY_MANAGER" in match.group(1)


def test_socket_server_builds_and_forwards_the_digest_before_the_bridge_call():
    src = _read(_LEON_PATCH_SOCKET_SERVER)

    build_idx = src.find("MEMORY_MANAGER.buildPlanningMemoryPack(utterance)")
    call_idx = src.find("await processViaNexusBridge(utterance, {")
    assert build_idx != -1, "buildPlanningMemoryPack call not found"
    assert call_idx != -1, "processViaNexusBridge call not found"
    assert build_idx < call_idx, "digest must be built BEFORE the bridge call, not after"

    # Forwarded under the exact field name nexus-bridge-client.ts expects.
    between = src[build_idx:call_idx + 400]
    assert "leonMemoryDigest" in between


def test_digest_retrieval_failure_does_not_crash_the_turn():
    """Same defensive shape as pulse-manager.ts's own use of the same
    call — a memory-recall failure must degrade to no-digest, not throw
    out of handleOwnerMessage."""
    src = _read(_LEON_PATCH_SOCKET_SERVER)
    build_idx = src.find("MEMORY_MANAGER.buildPlanningMemoryPack(utterance)")
    assert build_idx != -1
    window = src[max(0, build_idx - 200):build_idx + 400]
    assert "try {" in window and "catch (error)" in window


def test_real_leon_checkout_and_the_leon_patch_mirror_agree():
    """The file that actually runs (under `Nexus_Assistant/Leon AI/...`)
    must carry the exact same D4 wiring as the reference copy kept in
    `leon_patch/` for patch-generation purposes — same guarantee the
    project already relied on for D1's original patch (see
    `leon_patch/PATCH_NOTES.md`)."""
    mirror = _read(_LEON_PATCH_SOCKET_SERVER)
    real = _read(_REAL_LEON_SOCKET_SERVER)
    assert mirror == real, "leon_patch/ mirror and the real Leon checkout have diverged"


def test_regenerated_patch_file_reproduces_the_current_socket_server_exactly():
    """The unified diff (`socket-server.patch`) is meant to be a faithful,
    reproducible record of every change vs. pristine upstream Leon — not
    just documentation prose. This actually applies it (via a reconstructed
    pristine file) rather than trusting the diff hunks by inspection."""
    import shutil
    import subprocess
    import tempfile

    patch_path = _LEON_PATCH_SOCKET_SERVER.parent / "socket-server.patch"
    assert patch_path.exists()
    patch_text = patch_path.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        current = tmp_path / "current.ts"
        shutil.copy(_LEON_PATCH_SOCKET_SERVER, current)

        # Reconstruct pristine (pre-Nexus) by reversing the patch...
        reverse = subprocess.run(
            ["patch", "-R", "-o", str(tmp_path / "pristine.ts"), str(current)],
            input=patch_text, capture_output=True, text=True,
        )
        assert reverse.returncode == 0, reverse.stderr

        # ...then re-apply forward and confirm it reproduces the current file.
        rebuilt = tmp_path / "rebuilt.ts"
        shutil.copy(tmp_path / "pristine.ts", rebuilt)
        forward = subprocess.run(
            ["patch", str(rebuilt)], input=patch_text, capture_output=True, text=True,
        )
        assert forward.returncode == 0, forward.stderr
        assert rebuilt.read_text(encoding="utf-8") == current.read_text(encoding="utf-8")
