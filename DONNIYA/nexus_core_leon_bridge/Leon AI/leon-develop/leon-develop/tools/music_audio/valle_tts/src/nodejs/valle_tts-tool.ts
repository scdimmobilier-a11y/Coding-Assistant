import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { Tool } from '@sdk/base-tool'
import { ToolkitConfig } from '@sdk/toolkit-config'

const RESOURCE_NAME = 'vallex-checkpoint'
const DEFAULT_SETTINGS: Record<string, unknown> = {
  default_voice_preset: 'leon',
  default_language: 'auto'
}
const REQUIRED_SETTINGS: string[] = []

export interface SynthesizeSpeechTask {
  text: string
  output_path: string
  language?: 'auto' | 'en' | 'zh' | 'ja' | 'mix'
  voice_preset?: string
  reference_audio_path?: string
  reference_text?: string
  [key: string]: unknown
}

/**
 * VALL-E-X (Plachtaa/VALL-E-X) as an agent-callable Leon tool — Leon's
 * "voice" ("la parole"), zero-shot multilingual TTS + voice cloning.
 *
 * Unlike `Qwen3TTSTool` in this same toolkit, this tool has no prebuilt
 * `leon-binaries` release to shell out to (see the docstring at the top of
 * `../python/valle_tts_tool.py` for why). Instead it runs through its own
 * isolated `.venv`, created automatically next to that Python source by
 * Leon's existing `scripts/setup/sync-source-dependencies.js` (driven by
 * `../python/pyproject.toml`) — the exact same mechanism every other tool
 * in this toolkit already relies on for its Python side, just without an
 * extra compiled-binary layer on top.
 */
export default class ValleTTSTool extends Tool {
  private static readonly TOOLKIT = 'music_audio'
  private readonly config: ReturnType<typeof ToolkitConfig.load>

  constructor() {
    super()
    this.config = ToolkitConfig.load(ValleTTSTool.TOOLKIT, this.toolName)
    this.settings = ToolkitConfig.loadToolSettings(
      ValleTTSTool.TOOLKIT,
      this.toolName,
      DEFAULT_SETTINGS
    )
    this.requiredSettings = REQUIRED_SETTINGS
    this.checkRequiredSettings(this.toolName)
  }

  get toolName(): string {
    return 'valle_tts'
  }

  get toolkit(): string {
    return ValleTTSTool.TOOLKIT
  }

  get description(): string {
    return this.config['description']
  }

  /**
   * Resolve this tool's own venv Python interpreter, created next to
   * `valle_tts_tool.py` on first `pnpm install` (see class docstring).
   */
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
      'valle_tts_tool.py'
    )
  }

  /**
   * Synthesize speech from text using VALL-E-X. `output_path` in each task
   * is where the resulting WAV file is written; tasks are returned as-is
   * (already carrying the output paths the caller chose) once synthesis
   * completes, mirroring `Qwen3TTSTool.runTasks`'s own contract.
   */
  async synthesizeSpeech(
    tasks: SynthesizeSpeechTask | SynthesizeSpeechTask[],
    device = 'auto'
  ): Promise<SynthesizeSpeechTask[]> {
    const taskArray = Array.isArray(tasks) ? tasks : [tasks]
    let tempDir: string | null = null

    try {
      // Ensures the checkpoint is downloaded (idempotent) and returns the
      // directory it (and, on first run, the cloned VALL-E-X source /
      // Vocos / Whisper caches) live in — see `download_weights()` in
      // `valle_tts_tool.py`.
      const resourcePath = await this.getResourcePath(RESOURCE_NAME)

      tempDir = await fs.promises.mkdtemp(
        path.join(os.tmpdir(), 'valle_tts_tasks_')
      )
      const jsonFilePath = path.join(tempDir, 'tasks.json')

      const tasksWithDefaults = taskArray.map((task) => ({
        voice_preset: this.settings['default_voice_preset'],
        language: this.settings['default_language'],
        ...task
      }))

      await fs.promises.writeFile(
        jsonFilePath,
        JSON.stringify(tasksWithDefaults, null, 2),
        'utf8'
      )

      await this.executeCommand({
        binaryName: this.getVenvPythonPath(),
        args: [
          this.getScriptPath(),
          '--function',
          'synthesize_speech',
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

      return taskArray
    } catch (error: unknown) {
      throw new Error(`VALL-E-X execution failed: ${(error as Error).message}`)
    } finally {
      if (tempDir) {
        await fs.promises.rm(tempDir, { recursive: true, force: true })
      }
    }
  }
}
