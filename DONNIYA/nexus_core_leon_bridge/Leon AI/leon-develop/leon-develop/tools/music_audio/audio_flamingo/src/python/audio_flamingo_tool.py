"""
audio_flamingo_tool
====================

Downloads and runs NVIDIA's Audio Flamingo 3 (`nvidia/audio-flamingo-3-hf`)
as Leon's general-purpose hearing ("l'audition") backend: unlike a plain
ASR model, AF3 is a full audio-language model — it transcribes speech, but
it can also describe *non-speech* sound (what's making that noise, what
instrument is playing, what mood a room's ambience conveys, etc.) and
answer free-form questions about a clip. See `understand_audio_tasks`
below for that second, AF3-specific capability; `transcribe_audio_tasks`
covers the speech-to-text case so this tool can also be dropped in next to
`faster_whisper`/`qwen3_asr` as another `transcription_provider` option
(see `../../../skills/native/music_audio_toolkit_skill/src/actions/transcribe_audio.ts`).

Like `valle_tts_tool.py` in this same toolkit, this file is both a plain
importable module and a CLI entry point, run through this tool's own
isolated `.venv` (see `src/python/pyproject.toml`) rather than through a
prebuilt `leon-binaries` release — AF3 needs a very recent `transformers`
(built from source as of AF3's own release), which would conflict with
`tcp_server`'s own pinned `transformers==4.27.4` if it ran there instead;
giving it its own venv, exactly like every other tool in this toolkit
already does, sidesteps that conflict entirely.

Model access note: `nvidia/audio-flamingo-3-hf` weights are released under
NVIDIA's OneWay Noncommercial License (plus the Qwen Research license for
the underlying Qwen2.5-7B backbone) — non-commercial use only. That's a
licensing fact about the weights themselves, not something this file
enforces; whoever deploys Leon with this tool enabled is responsible for
complying with it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TypedDict

MODEL_ID = "nvidia/audio-flamingo-3-hf"
# AF3 processes audio in 30s windows, 20 windows/10 minutes max per sample
# (hard limit baked into the model itself, not a choice made here).
MAX_AUDIO_SECONDS = 600


class TranscribeTask(TypedDict, total=False):
    audio_path: str
    output_path: str


class UnderstandTask(TypedDict, total=False):
    audio_path: str
    question: str
    output_path: str
    enable_thinking: bool


def log(*args: Any) -> None:
    print("[audio_flamingo]", *args, file=sys.stderr, flush=True)


def download_weights(resource_path: Path) -> dict[str, str]:
    """Ensure the AF3 checkpoint is present locally, downloading it if not.

    Unlike `valle_tts_tool.py` (a handful of individually-named files), a
    modern `transformers`-native HF repo like this one is a sharded,
    versioned snapshot (safetensors shards + tokenizer + processor config,
    whose exact file list/shard count is upstream's to change). Rather than
    hand-enumerate filenames that could silently drift, `snapshot_download`
    (part of `huggingface_hub`, already a `transformers` dependency) is the
    correct, maintained tool for exactly this job — it resumes partial
    downloads and verifies file integrity against the Hub's own manifest.
    """
    from huggingface_hub import snapshot_download

    resource_path.mkdir(parents=True, exist_ok=True)
    log(f"Ensuring {MODEL_ID} snapshot is present at {resource_path} ...")
    local_dir = snapshot_download(
        repo_id=MODEL_ID,
        local_dir=str(resource_path),
        # Skip re-verifying every shard's checksum on every run once the
        # snapshot is complete; huggingface_hub still resumes/completes
        # a partial download correctly when files are missing.
        local_files_only=False,
    )
    log(f"{MODEL_ID} ready at {local_dir}")
    return {"model_path": local_dir}


_MODEL: Any = None
_PROCESSOR: Any = None


def _load_model(resource_path: Path, device: str) -> tuple[Any, Any]:
    global _MODEL, _PROCESSOR

    if _MODEL is not None and _PROCESSOR is not None:
        return _MODEL, _PROCESSOR

    paths = download_weights(resource_path)

    import torch
    from transformers import AudioFlamingo3ForConditionalGeneration, AutoProcessor

    device_map = "auto" if device in ("auto", "", None) else device
    log(f"Loading Audio Flamingo 3 on device_map={device_map} ...")

    _PROCESSOR = AutoProcessor.from_pretrained(paths["model_path"])
    _MODEL = AudioFlamingo3ForConditionalGeneration.from_pretrained(
        paths["model_path"],
        device_map=device_map,
        torch_dtype=torch.bfloat16,
    )
    return _MODEL, _PROCESSOR


def _run_conversation(
    model: Any,
    processor: Any,
    audio_path: str,
    prompt_text: str,
    max_new_tokens: int = 500,
) -> str:
    conversation = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "audio", "path": audio_path},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        conversation,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
    ).to(model.device, dtype=model.dtype)

    outputs = model.generate(**inputs, max_new_tokens=max_new_tokens)
    decoded = processor.batch_decode(
        outputs[:, inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )
    return decoded[0].strip() if decoded else ""


def transcribe_audio_tasks(
    tasks: list[TranscribeTask],
    resource_path: Path,
    device: str = "auto",
) -> list[TranscribeTask]:
    """Speech-to-text via AF3's dedicated transcription request helper —
    this is the ASR-equivalent capability, usable as a drop-in alternative
    to `faster_whisper`/`qwen3_asr` in `transcribe_audio.ts`.

    Output matches this toolkit's shared `TranscriptionOutput` schema (see
    `../../transcription_schema.py`) so it's a genuine drop-in for that
    skill action. Honest limitation: AF3's transcription request returns
    one free-form text block, not per-word/segment timestamps the way
    `faster_whisper`'s forced alignment does — so this writes a single
    segment spanning the full clip duration rather than several finer-
    grained ones. Speaker diarization isn't part of AF3's transcription
    mode either, hence the single "unknown" speaker below.
    """
    model, processor = _load_model(resource_path, device)

    import soundfile as sf

    for task in tasks:
        audio_path = task["audio_path"]
        log(f"Transcribing {audio_path} ...")

        inputs = processor.apply_transcription_request(audio=audio_path).to(
            model.device, dtype=model.dtype
        )
        outputs = model.generate(**inputs, max_new_tokens=500)
        decoded = processor.batch_decode(
            outputs[:, inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
            strip_prefix=True,
        )
        text = decoded[0].strip() if decoded else ""

        try:
            duration = sf.info(audio_path).duration
        except Exception:  # noqa: BLE001 - best-effort only, never fatal here
            duration = 0.0

        transcription_output = {
            "duration": duration,
            "speakers": ["unknown"],
            "speaker_count": 1,
            "segments": [
                {"from": 0.0, "to": duration, "text": text, "speaker": "unknown"}
            ],
            "metadata": {"tool": "audio_flamingo"},
        }

        output_path = Path(task["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(transcription_output, ensure_ascii=False), encoding="utf-8"
        )
        task["output_path"] = str(output_path)

    return tasks


def understand_audio_tasks(
    tasks: list[UnderstandTask],
    resource_path: Path,
    device: str = "auto",
) -> list[UnderstandTask]:
    """General audio understanding / free-form Q&A — the actual "hearing"
    capability beyond plain transcription: what's happening acoustically,
    what instrument/genre/mood, describe this recording, etc. This is the
    part of "l'audition" that pure ASR (faster_whisper, qwen3_asr, and
    even AF3's own transcription mode above) does not cover on its own."""
    model, processor = _load_model(resource_path, device)

    for task in tasks:
        audio_path = task["audio_path"]
        question = task.get("question") or "Describe what you hear in this audio in detail."
        prompt = question
        if task.get("enable_thinking"):
            prompt = f"{question} Think step by step about what you hear before answering."

        log(f"Understanding {audio_path} (question: {question!r}) ...")
        answer = _run_conversation(model, processor, audio_path, prompt)

        output_path_value = task.get("output_path")
        if output_path_value:
            output_path = Path(output_path_value)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps({"question": question, "answer": answer}, ensure_ascii=False),
                encoding="utf-8",
            )
            task["output_path"] = str(output_path)
        task["answer"] = answer  # type: ignore[typeddict-unknown-key]

    return tasks


def _read_tasks(json_file: str) -> list[dict[str, Any]]:
    data = json.loads(Path(json_file).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audio Flamingo 3 hearing/understanding for Leon")
    parser.add_argument(
        "--function",
        required=True,
        choices=["download", "transcribe_audio", "understand_audio"],
        help="download: fetch/verify the model snapshot only. "
        "transcribe_audio / understand_audio: run --json_file's tasks "
        "(downloads first if needed).",
    )
    parser.add_argument("--json_file", help="Path to a JSON task or list of tasks")
    parser.add_argument(
        "--resource_path",
        required=True,
        help="Directory Leon manages for this tool's downloaded model snapshot",
    )
    parser.add_argument("--device", default="auto", help="cpu | cuda | auto | cuda:0 ...")
    args = parser.parse_args()

    resource_path = Path(args.resource_path)

    if args.function == "download":
        paths = download_weights(resource_path)
        print(json.dumps(paths, indent=2))
        return

    if not args.json_file:
        parser.error(f"--json_file is required for --function {args.function}")

    tasks = _read_tasks(args.json_file)

    if args.function == "transcribe_audio":
        result = transcribe_audio_tasks(tasks, resource_path, args.device)  # type: ignore[arg-type]
    else:
        result = understand_audio_tasks(tasks, resource_path, args.device)  # type: ignore[arg-type]

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
