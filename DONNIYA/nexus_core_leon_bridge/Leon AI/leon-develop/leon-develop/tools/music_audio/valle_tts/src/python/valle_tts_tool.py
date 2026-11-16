"""
valle_tts_tool
==============

Downloads and runs Plachtaa/VALL-E-X (an open-source reproduction of
Microsoft's VALL-E X zero-shot TTS model — Microsoft never released code
or weights, so this community checkpoint is the real, runnable artifact
that exists) as Leon's VALL-E speech provider ("la parole" of Leon).

This file is deliberately BOTH a plain importable module (`download_weights`,
`synthesize_speech_tasks`) and a CLI entry point (`__main__`), because unlike
`qwen3_tts`/`qwen3_asr` in this same toolkit, VALL-E-X has no prebuilt,
leon-ai-hosted binary to shell out to (see `../../tool.json` / the toolkit
README for why: this integration was prepared without publishing a new
`leon-binaries` release). Instead, `src/python/pyproject.toml` next to this
file gets its own isolated `.venv` via Leon's existing
`scripts/setup/sync-source-dependencies.js` machinery, and the Node.js side
(`../nodejs/valle_tts-tool.ts`) invokes this script directly with that
venv's Python interpreter — same net effect (one command in, files out),
one fewer moving part (no compiled binary to build/host).

Layout under `resource_path` (an assets directory Leon manages for this
tool, one per install — see `getResourcePath`/`get_resource_path` on the
Node/Python SDKs):

    <resource_path>/
      checkpoints/vallex-checkpoint.pt   VALL-E-X's own trained weights (MIT)
      vallex-src/                        the Plachtaa/VALL-E-X inference code
                                          (git-cloned; see "Why git-clone" below)
      vocos/                             charactr/vocos-encodec-24khz decoder
      whisper/medium.pt                  OpenAI Whisper, used only to
                                          auto-transcribe a *new* voice prompt
                                          when the caller doesn't supply the
                                          reference transcript themselves

Why git-clone the inference code instead of `pip install`
-----------------------------------------------------------
Plachtaa/VALL-E-X ships a same-named `VALL-E-X` package on PyPI, but it is a
metadata-only mirror of the README, not an importable, working package (the
project's own instructions, PyPI page included, all say `git clone` +
`pip install -r requirements.txt`, never `pip install vall-e-x`). Vendoring
their ~15 inference files into this repo would fork them silently out of
sync with upstream fixes; git-cloning a pinned commit on first use keeps one
canonical copy and makes the pinned version explicit and upgradable.

Honest note: upstream `Plachtaa/VALL-E-X` was archived (read-only) by its
owner in November 2025. It still clones and runs fine — archiving only
means the upstream repo itself won't receive further commits/issues — but
if it ever disappears, `VALLEX_REPO_URL`/`VALLEX_REPO_COMMIT` below is the
one place to point at a fork or mirror instead.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional, TypedDict

VALLEX_CHECKPOINT_URL = (
    "https://huggingface.co/Plachta/VALL-E-X/resolve/main/vallex-checkpoint.pt"
)
VALLEX_REPO_URL = "https://github.com/Plachtaa/VALL-E-X.git"
# Pinned so a future upstream change can't silently alter Leon's voice
# output without a deliberate bump of this constant.
VALLEX_REPO_COMMIT = "3634b9d"
VOCOS_REPO_ID = "charactr/vocos-encodec-24khz"
WHISPER_MEDIUM_URL = (
    "https://openaipublic.azureedge.net/main/whisper/models/"
    "345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt"
)
DEFAULT_VOICE_PRESET = "leon"
SAMPLE_RATE = 24_000  # VALL-E-X / Encodec's native output sample rate


class SynthesizeTask(TypedDict, total=False):
    text: str
    output_path: str
    language: str  # "en" | "zh" | "ja" | "mix", per VALL-E-X's own API
    voice_preset: str
    reference_audio_path: str
    reference_text: str


def log(*args: Any) -> None:
    print("[valle_tts]", *args, file=sys.stderr, flush=True)


def _download_with_progress(url: str, destination: Path, label: str) -> None:
    """Stream a file to disk with resumable-looking progress logging.

    Plain `urllib` rather than `requests` on purpose: this script's own
    `pyproject.toml` only needs to declare the heavy ML dependencies
    (torch, torchaudio, vocos, encodec, openai-whisper); `urllib` avoids
    adding `requests` as one more dependency just for two downloads.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(destination.suffix + ".part")

    request = urllib.request.Request(url, headers={"User-Agent": "leon-ai-valle-tts"})
    with urllib.request.urlopen(request) as response:
        total = int(response.headers.get("Content-Length", 0) or 0)
        written = 0
        last_log = 0.0

        with tmp_path.open("wb") as out_file:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out_file.write(chunk)
                written += len(chunk)

                now = time.monotonic()
                if now - last_log > 2.0:
                    if total:
                        pct = written / total * 100
                        log(f"{label}: {pct:5.1f}% ({written / 1e6:.0f}MB / {total / 1e6:.0f}MB)")
                    else:
                        log(f"{label}: {written / 1e6:.0f}MB downloaded")
                    last_log = now

    tmp_path.replace(destination)
    log(f"{label}: done -> {destination}")


def _ensure_vallex_checkpoint(resource_path: Path) -> Path:
    # Flat filename on purpose: when this tool is invoked through Leon's
    # agent/Tool path (`valle_tts-tool.ts`), `--resource_path` is exactly
    # `Tool.getResourcePath('vallex-checkpoint')`, which Leon's own
    # downloader (declared in `../../tool.json`) already populates with
    # `vallex-checkpoint.pt` directly at that path (no subfolder) — so
    # this same flat path also has to be where our own direct-download
    # fallback below looks, or the two entry points would each redownload
    # the same ~500MB file into two different places.
    checkpoint_path = resource_path / "vallex-checkpoint.pt"
    if checkpoint_path.is_file() and checkpoint_path.stat().st_size > 0:
        log(f"VALL-E-X checkpoint already present at {checkpoint_path}")
        return checkpoint_path

    log(f"Downloading VALL-E-X checkpoint from {VALLEX_CHECKPOINT_URL} ...")
    _download_with_progress(VALLEX_CHECKPOINT_URL, checkpoint_path, "vallex-checkpoint.pt")
    return checkpoint_path


def _ensure_vallex_source(resource_path: Path) -> Path:
    src_path = resource_path / "vallex-src"
    marker = src_path / ".leon-clone-complete"
    if marker.is_file():
        log(f"VALL-E-X source already present at {src_path}")
        return src_path

    if shutil.which("git") is None:
        raise RuntimeError(
            "git is required to fetch the VALL-E-X inference code on first "
            "run (see module docstring for why this isn't vendored/pip-"
            "installed instead). Install git and retry."
        )

    if src_path.exists():
        shutil.rmtree(src_path)

    log(f"Cloning {VALLEX_REPO_URL} ({VALLEX_REPO_COMMIT}) -> {src_path} ...")
    subprocess.run(
        ["git", "clone", VALLEX_REPO_URL, str(src_path)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(src_path), "checkout", VALLEX_REPO_COMMIT],
        check=True,
    )

    # Best-effort reconciliation: `src/python/pyproject.toml` (next to this
    # file) pins the core heavy deps (torch/torchaudio/vocos/whisper/...)
    # ourselves so Leon's `.venv` setup step has something to install before
    # this code even runs once. Upstream's own `requirements.txt` remains
    # the authoritative list, though, so top it up here now that we have it
    # — any package pyproject.toml already satisfied is a fast no-op for pip.
    upstream_requirements = src_path / "requirements.txt"
    if upstream_requirements.is_file():
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(upstream_requirements)],
                check=True,
            )
        except subprocess.CalledProcessError as error:
            log(
                f"Warning: could not fully reconcile upstream requirements.txt "
                f"({error}); continuing with the pinned baseline from this "
                f"tool's own pyproject.toml"
            )

    marker.write_text(f"cloned {VALLEX_REPO_COMMIT}\n")
    return src_path


def _ensure_vocos(resource_path: Path) -> Path:
    """Vocos is a small HF-hub package; its own `from_pretrained` already
    downloads+caches it, so we just point its cache at our resource dir
    rather than re-implementing HF Hub's own download/resume logic."""
    vocos_cache = resource_path / "vocos"
    vocos_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(vocos_cache / "hf-home"))
    return vocos_cache


def _ensure_whisper_medium(resource_path: Path) -> Path:
    whisper_path = resource_path / "whisper" / "medium.pt"
    if whisper_path.is_file() and whisper_path.stat().st_size > 0:
        log(f"Whisper medium already present at {whisper_path}")
        return whisper_path

    log(f"Downloading Whisper medium (used only to transcribe new voice prompts) ...")
    _download_with_progress(WHISPER_MEDIUM_URL, whisper_path, "whisper-medium.pt")
    return whisper_path


def download_weights(resource_path: Path) -> dict[str, str]:
    """Ensure every asset VALL-E-X needs is present locally, downloading
    whatever is missing. Safe to call on every run: each step is a no-op
    once its file/marker exists (see `_ensure_*` above)."""
    resource_path.mkdir(parents=True, exist_ok=True)

    checkpoint_path = _ensure_vallex_checkpoint(resource_path)
    src_path = _ensure_vallex_source(resource_path)
    vocos_path = _ensure_vocos(resource_path)
    whisper_path = _ensure_whisper_medium(resource_path)

    return {
        "checkpoint_path": str(checkpoint_path),
        "source_path": str(src_path),
        "vocos_cache_path": str(vocos_path),
        "whisper_path": str(whisper_path),
    }


_MODELS_LOADED = False


def _load_models(resource_path: Path, device: str) -> None:
    """Import VALL-E-X's own generation module and preload its models.

    Imported lazily (not at module top-level) because this module must
    remain importable — e.g. for `--function download` alone, or for unit
    tests of the download helpers above — on machines that don't have
    torch/torchaudio/vocos installed yet.
    """
    global _MODELS_LOADED

    paths = download_weights(resource_path)
    sys.path.insert(0, paths["source_path"])

    # VALL-E-X resolves its own checkpoint path as "./checkpoints/vallex-checkpoint.pt"
    # relative to the current working directory, so make that true.
    os.chdir(paths["source_path"])
    checkpoints_dir = Path(paths["source_path"]) / "checkpoints"
    checkpoints_dir.mkdir(exist_ok=True)
    linked_checkpoint = checkpoints_dir / "vallex-checkpoint.pt"
    if not linked_checkpoint.exists():
        try:
            linked_checkpoint.symlink_to(paths["checkpoint_path"])
        except OSError:
            shutil.copyfile(paths["checkpoint_path"], linked_checkpoint)

    if not _MODELS_LOADED:
        from utils.generation import preload_models  # type: ignore  # noqa: E402

        log(f"Preloading VALL-E-X models on device={device} ...")
        if device and device != "auto":
            os.environ["VALLEX_DEVICE"] = device
        preload_models()
        _MODELS_LOADED = True


def synthesize_speech_tasks(
    tasks: list[SynthesizeTask],
    resource_path: Path,
    device: str = "auto",
) -> list[SynthesizeTask]:
    """Synthesize every task's `text` to `output_path` using VALL-E-X.

    Voice: `voice_preset` selects one of VALL-E-X's bundled preset voices
    (default: Leon's own registered "leon" preset, see
    `settings.sample.json` for how to point that at a custom voice prompt);
    or supply `reference_audio_path` (+ optional `reference_text`, else
    auto-transcribed with Whisper) to zero-shot clone an arbitrary voice.
    """
    _load_models(resource_path, device)

    from utils.generation import generate_audio  # type: ignore  # noqa: E402
    from utils.prompt_making import make_prompt  # type: ignore  # noqa: E402
    import soundfile as sf  # noqa: E402

    for task in tasks:
        text = task.get("text", "")
        output_path = Path(task["output_path"])
        language = task.get("language", "auto")
        voice_preset = task.get("voice_preset") or DEFAULT_VOICE_PRESET
        reference_audio_path = task.get("reference_audio_path")

        prompt_name = voice_preset
        if reference_audio_path:
            # Zero-shot voice cloning from a caller-supplied sample. Leaving
            # `transcript` unset lets VALL-E-X fall back to its bundled
            # Whisper model to auto-transcribe the reference clip.
            prompt_name = f"_leon_custom_{Path(reference_audio_path).stem}"
            make_prompt(
                name=prompt_name,
                audio_prompt_path=reference_audio_path,
                transcript=task.get("reference_text") or None,
            )

        log(f"Synthesizing {len(text)} chars with voice='{prompt_name}' lang='{language}' -> {output_path}")
        audio_array = generate_audio(text, prompt=prompt_name, language=language)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), audio_array, SAMPLE_RATE)
        task["output_path"] = str(output_path)

    return tasks


def _read_tasks(json_file: str) -> list[SynthesizeTask]:
    data = json.loads(Path(json_file).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def main() -> None:
    parser = argparse.ArgumentParser(description="VALL-E-X speech synthesis for Leon")
    parser.add_argument(
        "--function",
        required=True,
        choices=["download", "synthesize_speech"],
        help="download: fetch/verify all weights only. "
        "synthesize_speech: run --json_file's tasks (downloads first if needed).",
    )
    parser.add_argument("--json_file", help="Path to a JSON task or list of tasks")
    parser.add_argument(
        "--resource_path",
        required=True,
        help="Directory Leon manages for this tool's downloaded assets",
    )
    parser.add_argument("--device", default="auto", help="cpu | cuda | auto")
    args = parser.parse_args()

    resource_path = Path(args.resource_path)

    if args.function == "download":
        paths = download_weights(resource_path)
        print(json.dumps(paths, indent=2))
        return

    if not args.json_file:
        parser.error("--json_file is required for --function synthesize_speech")

    tasks = _read_tasks(args.json_file)
    result = synthesize_speech_tasks(tasks, resource_path, args.device)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
