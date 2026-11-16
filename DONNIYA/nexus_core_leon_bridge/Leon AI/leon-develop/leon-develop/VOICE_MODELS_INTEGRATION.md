# VALL-E-X (speech) & Audio Flamingo 3 (hearing) integration

This document describes an addition made on top of the stock Leon codebase:
giving Leon a new voice (VALL-E-X) and a new pair of ears (NVIDIA Audio
Flamingo 3), on top of the existing "local" ASR/TTS engine. It's written in
the same spirit as `docs/DECISIONS.md` in the neighboring
`nexus_core_leon_bridge/` package: a plain account of what was built, why
it was built that way, and what is and isn't verified.

## What's here

| Capability | Model | Lives at |
|---|---|---|
| Speech (TTS) | VALL-E-X (`Plachtaa/VALL-E-X`) | `tools/music_audio/valle_tts/` |
| Hearing (ASR + audio understanding) | Audio Flamingo 3 (`nvidia/audio-flamingo-3-hf`) | `tools/music_audio/audio_flamingo/` |

Each is wired in at **two** levels:

1. **Core voice pipeline** — `config.sample.yml`'s `voice.tts.provider: valle-x`
   and `voice.asr.provider: audio-flamingo` make these Leon's actual voice
   and ears, alongside the existing `local` provider
   (`server/src/core/tts/synthesizers/valle-x-synthesizer.ts`,
   `server/src/core/asr/parsers/audio-flamingo-parser.ts`).
2. **Agent-callable tools** — `ValleTTSTool` / `AudioFlamingoTool` in the
   `music_audio` toolkit, callable directly by the LLM agent or from other
   skills (see the new `synthesize_speech` and `understand_audio` actions
   in `skills/native/music_audio_toolkit_skill/`). Audio Flamingo 3's
   *non-speech* understanding (describe a sound, answer a free-form
   question about a clip) only exists at this level — `ASRParserBase.parse`
   returns a single transcript string, which has no room for "what
   instrument is that" style answers.

Both entry points share one Python implementation and one on-disk copy of
the downloaded weights (`<LEON_HOME>/toolkits/music_audio/assets/...`), so
using both doesn't download or load anything twice.

## Why a separate `.venv` per tool, not `tcp_server`

Leon's existing local ASR/TTS engine (`tcp_server/`) pins
`transformers==4.27.4` for its own MeloTTS-style text front-end and
faster-whisper ASR. Audio Flamingo 3 needs a current `transformers` release
(`AudioFlamingo3ForConditionalGeneration` didn't exist in 4.27.4's era); VALL-E-X
needs its own stack too (`vocos`, `encodec`, `openai-whisper`). Rather than
upgrading `tcp_server`'s pinned dependency (and risking the existing local
voice pipeline), each new tool gets its own isolated `.venv`, created
automatically by Leon's existing
`scripts/setup/sync-source-dependencies.js` from the `pyproject.toml` next
to each tool's Python source — the exact same mechanism every other tool in
the `music_audio` toolkit already relies on (`qwen3_tts`, `qwen3_asr`,
`faster_whisper`, ...). Nothing new was invented for this; it's the same
machinery pointed at two more tools.

## Why no prebuilt binary (unlike `qwen3_tts`/`qwen3_asr`)

Those two ship a compiled, `leon-binaries`-hosted executable per platform.
Building and publishing an equivalent release for VALL-E-X/Audio Flamingo 3
was out of scope here (it requires a build pipeline and a hosting release
this change doesn't have access to). Instead, both tools run as plain
Python through their own `.venv`, invoked with `skipBinaryDownload: true`
and the venv's own interpreter as the "binary" — a codepath the shared
`Tool.executeCommand()` SDK method already supports (used elsewhere for
built-ins like `bash`), so this isn't a new mechanism either, just a
different existing one than `qwen3_tts` happens to use.

## Model access notes

- **VALL-E-X**: MIT-licensed weights, but upstream `Plachtaa/VALL-E-X` was
  **archived (read-only) by its owner in November 2025**. It still clones
  and runs fine — archiving only means no further upstream commits — but if
  the repo ever disappears, `VALLEX_REPO_URL`/`VALLEX_REPO_COMMIT` in
  `tools/music_audio/valle_tts/src/python/valle_tts_tool.py` is the one
  place to point at a fork or mirror instead.
- **Audio Flamingo 3**: released under NVIDIA's OneWay Noncommercial
  License plus the Qwen Research License for its Qwen2.5-7B backbone —
  **non-commercial use only**. That's a fact about the weights, not
  something this integration enforces; whoever deploys Leon with this tool
  enabled is responsible for complying with it.

## What's verified vs. not

Built and reviewed in a sandboxed environment with **no GPU and no
network access to `huggingface.co`**, so, honestly:

- ✅ Verified: every file here is syntactically valid (`python3 -m
  py_compile` on both `.py` files; `esbuild` parse-check on every new/edited
  `.ts` file). JSON manifests (`tool.json`, `skill.json`, `toolkit.json`,
  locale files) all parse. The exact NVIDIA/`transformers` usage
  (`AudioFlamingo3ForConditionalGeneration`, `apply_chat_template`,
  `apply_transcription_request`) and the VALL-E-X usage (`generate_audio`,
  `make_prompt`, the checkpoint/Whisper download URLs) were checked against
  each project's own current documentation, not written from memory alone.
  The patch from `nexus_core_leon_bridge/leon_patch/` was applied to this
  same checkout and its hash matches that package's own manifest exactly.
- ❌ Not verified: actually downloading either model's weights, loading them,
  or running inference — this sandbox has neither the GPU nor the network
  access (`huggingface.co` isn't reachable from it) to do so. The first real
  run, on a machine with both, is the actual test of this integration.
- Dependency versions in each tool's `pyproject.toml` are a reasonable
  baseline, not a guarantee: `valle_tts`'s reconciles itself against
  upstream's `requirements.txt` on first clone (see that file's
  `_ensure_vallex_source`); `audio_flamingo`'s tracks `transformers` from
  its `main` branch on purpose, since AF3 support there is recent and still
  moving.

## Non-regression

`nexus_core_leon_bridge/tests/leon_protected_files.sha256.json` asserts
that the bridge integration alone doesn't touch Leon's voice pipeline
files. This change **does** touch four of those files on purpose
(registering two new providers): `server/src/core/tts/types.ts`,
`server/src/core/tts/tts.ts`, `server/src/core/asr/types.ts`,
`server/src/core/asr/asr-provider.ts`. Their expected hashes in that
manifest were updated to match the new, intentional content; every other
previously-protected file (both parser/synthesizer base classes, every
*other* parser/synthesizer, the wake-word engine) is untouched and still
checked against its original hash.
