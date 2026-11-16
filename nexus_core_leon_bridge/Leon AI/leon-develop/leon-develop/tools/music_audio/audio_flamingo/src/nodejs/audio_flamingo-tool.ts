import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { Tool } from '@sdk/base-tool'
import { ToolkitConfig } from '@sdk/toolkit-config'
import { LEON_TOOLKITS_PATH } from '@bridge/constants'

const MODEL_DIR_NAME = 'audio-flamingo-3-hf'
const DEFAULT_SETTINGS: Record<string, unknown> = {
  default_device: 'auto'
}
const REQUIRED_SETTINGS: string[] = []

export interface TranscribeAudioTask {
  audio_path: string
  output_path: string
  [key: string]: unknown
}

export interface UnderstandAudioTask {
  audio_path: string
  question?: string
  output_path?: string
  enable_thinking?: boolean
  [key: string]: unknown
}

/**
 * NVIDIA Audio Flamingo 3 as an agent-callable Leon tool — Leon's
 * general-purpose "hearing" ("l'audition"): speech transcription
 * (`transcribeAudio`) plus free-form audio understanding (`understandAudio`)
 * that plain ASR doesn't offer (sound events, music, mood, "what is that
 * noise").
 *
 * `nvidia/audio-flamingo-3-hf` ships as a modern, sharded `transformers`
 * checkpoint (safetensors shards whose exact file list is upstream's to
 * change) rather than a handful of individually-named files, so — unlike
 * `ValleTTSTool`, and unlike every other tool in this toolkit — this one
 * does NOT declare a `resources` map in `../../tool.json` and does NOT use
 * `Tool.getResourcePath()`. `huggingface_hub.snapshot_download` (already a
 * `transformers` dependency, and literally what NVIDIA's own model card
 * shows in its PEFT usage example) is the correct, maintained tool for
 * that job instead — see `download_weights()` in `../python/audio_flamingo_tool.py`.
 * This method only computes *where* that snapshot should live, reusing the
 * same `<LEON_TOOLKITS_PATH>/<toolkit>/assets/` convention `getResourcePath`
 * itself uses, so the model still lands in the expected place on disk.
 *
 * Also — like `ValleTTSTool` — runs through its own isolated `.venv`
 * (`../python/pyproject.toml`), separate from `tcp_server`'s pinned
 * `transformers==4.27.4`, since AF3 needs a current `transformers` release.
 */
export default class AudioFlamingoTool extends Tool {
  private static readonly TOOLKIT = 'music_audio'
  private readonly config: ReturnType<typeof ToolkitConfig.load>

  constructor() {
    super()
    this.config = ToolkitConfig.load(AudioFlamingoTool.TOOLKIT, this.toolName)
    this.settings = ToolkitConfig.loadToolSettings(
      AudioFlamingoTool.TOOLKIT,
      this.toolName,
      DEFAULT_SETTINGS
    )
    this.requiredSettings = REQUIRED_SETTINGS
    this.checkRequiredSettings(this.toolName)
  }

  get toolName(): string {
    return 'audio_flamingo'
  }

  get toolkit(): string {
    return AudioFlamingoTool.TOOLKIT
  }

  get description(): string {
    return this.config['description']
  }

  private getVenvPythonPath(): string {
    const pythonSourceDir = path.resolve(
      this.getToolDir(import.meta.url),
      '..',
      'python'
    )
    const isWindows = process.platform === 'win32'

    return path.join(
      pythonSourceDir,
      '.venv',
      isWindows ? 'Scripts' : 'bin',
      isWindows ? 'python.exe' : 'python'
    )
  }

  private getScriptPath(): string {
    return path.resolve(
      this.getToolDir(import.meta.url),
      '..',
      'python',
      'audio_flamingo_tool.py'
    )
  }

  private async getModelResourcePath(): Promise<string> {
    const resourcePath = path.join(
      LEON_TOOLKITS_PATH,
      AudioFlamingoTool.TOOLKIT,
      'assets',
      MODEL_DIR_NAME
    )
    await fs.promises.mkdir(resourcePath, { recursive: true })
    return resourcePath
  }

  private async runScript(
    functionName: 'transcribe_audio' | 'understand_audio',
    tasks: Record<string, unknown>[],
    device: string
  ): Promise<Record<string, unknown>[]> {
    let tempDir: string | null = null

    try {
      const resourcePath = await this.getModelResourcePath()

      tempDir = await fs.promises.mkdtemp(
        path.join(os.tmpdir(), 'audio_flamingo_tasks_')
      )
      const jsonFilePath = path.join(tempDir, 'tasks.json')

      await fs.promises.writeFile(
        jsonFilePath,
        JSON.stringify(tasks, null, 2),
        'utf8'
      )

      const stdout = await this.executeCommand({
        binaryName: this.getVenvPythonPath(),
        args: [
          this.getScriptPath(),
          '--function',
          functionName,
          '--json_file',
          jsonFilePath,
          '--resource_path',
          resourcePath,
          '--device',
          device
        ],
        options: { sync: true },
        skipBinaryDownload: true
      })

      // The script prints the final task list as JSON on stdout (see
      // `main()` in `../python/audio_flamingo_tool.py`) — parsed back here
      // so e.g. `understand_audio`'s `answer` field reaches the caller even
      // when no `output_path` was given.
      try {
        const parsed: unknown = JSON.parse(stdout)
        if (Array.isArray(parsed)) {
          return parsed as Record<string, unknown>[]
        }
      } catch {
        // Fall through to returning the original tasks below — the run
        // still succeeded (executeCommand would have thrown otherwise),
        // this only means stdout wasn't clean JSON to parse back.
      }

      return tasks
    } finally {
      if (tempDir) {
        await fs.promises.rm(tempDir, { recursive: true, force: true })
      }
    }
  }

  /**
   * Convenience wrapper matching `Qwen3ASRTool.transcribeToFile`'s calling
   * convention exactly, so this tool is a genuine drop-in
   * `transcription_provider` option in
   * `../../../skills/native/music_audio_toolkit_skill/src/actions/transcribe_audio.ts`.
   */
  async transcribeToFile(
    inputPath: string,
    outputPath: string,
    device = 'auto'
  ): Promise<string> {
    await this.transcribeAudio(
      { audio_path: inputPath, output_path: outputPath },
      device
    )
    return outputPath
  }

  /**
   * Speech-to-text via Audio Flamingo 3's dedicated transcription request —
   * a drop-in alternative to `faster_whisper`/`qwen3_asr` for
   * `transcribe_audio.ts`. Writes each task's transcript to its
   * `output_path` following this toolkit's shared `TranscriptionOutput`
   * schema (see `../python/audio_flamingo_tool.py` for the honest caveat
   * on single-segment timestamps).
   */
  async transcribeAudio(
    tasks: TranscribeAudioTask | TranscribeAudioTask[],
    device?: string
  ): Promise<TranscribeAudioTask[]> {
    const taskArray = Array.isArray(tasks) ? tasks : [tasks]

    try {
      const result = await this.runScript(
        'transcribe_audio',
        taskArray,
        device ?? (this.settings['default_device'] as string)
      )
      return result as TranscribeAudioTask[]
    } catch (error: unknown) {
      throw new Error(
        `Audio Flamingo 3 transcription failed: ${(error as Error).message}`
      )
    }
  }

  /**
   * General audio understanding / free-form Q&A — describes non-speech
   * sound, answers a question about a clip. Each returned task carries an
   * `answer` field; `{ "question": "...", "answer": "..." }` is also
   * written to `output_path` if one was provided.
   */
  async understandAudio(
    tasks: UnderstandAudioTask | UnderstandAudioTask[],
    device?: string
  ): Promise<UnderstandAudioTask[]> {
    const taskArray = Array.isArray(tasks) ? tasks : [tasks]

    try {
      const result = await this.runScript(
        'understand_audio',
        taskArray,
        device ?? (this.settings['default_device'] as string)
      )
      return result as UnderstandAudioTask[]
    } catch (error: unknown) {
      throw new Error(
        `Audio Flamingo 3 understanding failed: ${(error as Error).message}`
      )
    }
  }
}
