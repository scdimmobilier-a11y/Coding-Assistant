"""
tests.test_non_regression_voice_pipeline
===========================================

Deliverable #8, scenario 3: "un test de non-régression prouvant que le
pipeline vocal de Leon (wake word/ASR/TTS) n'a subi aucune modification de
comportement."

This delivery does not bundle Leon's source (it's the person's own large
upload, not something to duplicate into a small integration package), so
this test is a checksum comparison against `leon_protected_files.sha256.json`
— hashes computed directly from the exact, unmodified Leon checkout this
integration was prepared against. Point `LEON_REPO_ROOT` at your own Leon
checkout (e.g. `.../Nexus_Assistant/Leon AI/leon-develop/leon-develop`)
to run it for real; without that env var the test is skipped rather than
faked green, since a checksum test that always silently passes would be
worse than no test at all.

This is a genuinely stronger, more falsifiable claim than "we didn't touch
ASR/TTS/hotword, trust us": if anyone (this delivery, a future patch, a
merge conflict resolution) ever changes so much as one byte of the wake
word models, the ASR providers, or the TTS synthesizers, this test fails.

It also proves the *opposite* fact for `socket-server.ts`: that this is
the ONE file that DID change, and that the shipped `socket-server.ts` in
`leon_patch/` really is byte-for-byte what you get by applying
`socket-server.patch` to the original — not a drifted copy.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

_MANIFEST_PATH = Path(__file__).parent / "leon_protected_files.sha256.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text())

_LEON_PATCH_DIR = Path(__file__).parent.parent / "leon_patch" / "server" / "src" / "core"


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _leon_repo_root() -> Path:
    root = os.environ.get("LEON_REPO_ROOT")
    if not root:
        pytest.skip(
            "LEON_REPO_ROOT not set — point it at a Leon checkout to run "
            "this test for real (see module docstring). Not faking a pass."
        )
    path = Path(root)
    if not path.is_dir():
        pytest.fail(f"LEON_REPO_ROOT={root!r} is not a directory.")
    return path


def test_asr_tts_wake_word_files_are_byte_identical_to_the_pre_integration_checkout():
    repo_root = _leon_repo_root()
    mismatches = []
    missing = []

    for rel_path, expected_hash in _MANIFEST["protected_files_sha256"].items():
        full_path = repo_root / rel_path
        if not full_path.is_file():
            missing.append(rel_path)
            continue
        actual_hash = _sha256_of(full_path)
        if actual_hash != expected_hash:
            mismatches.append((rel_path, expected_hash, actual_hash))

    assert not missing, f"Expected voice-pipeline files not found under LEON_REPO_ROOT: {missing}"
    assert not mismatches, (
        "Voice pipeline files changed relative to the pre-integration checkout "
        f"(rel_path, expected, actual): {mismatches}"
    )


def test_socket_server_original_hash_matches_the_patch_s_starting_point():
    """Confirms the .patch file's '-' side really is this Leon checkout's
    current socket-server.ts — i.e. the patch will apply cleanly, rather
    than silently conflicting because the checkout has moved on."""
    repo_root = _leon_repo_root()
    current = repo_root / _MANIFEST["socket_server_ts_relative_path"]
    assert current.is_file(), f"{current} not found."
    assert _sha256_of(current) == _MANIFEST["socket_server_ts_original_sha256"], (
        "socket-server.ts in this checkout no longer matches the version this "
        "patch was prepared against — re-diff before applying socket-server.patch."
    )


def test_shipped_patched_socket_server_matches_its_own_manifest_hash():
    """The socket-server.ts shipped inside leon_patch/ (for convenience,
    as an alternative to applying the .patch by hand) is exactly what the
    manifest says it is — catches accidental drift between the two."""
    shipped = _LEON_PATCH_DIR / "socket-server.ts"
    assert shipped.is_file()
    assert _sha256_of(shipped) == _MANIFEST["socket_server_ts_patched_sha256"]
