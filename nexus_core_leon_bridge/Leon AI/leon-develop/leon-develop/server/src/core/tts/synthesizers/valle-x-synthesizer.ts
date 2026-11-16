import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'
import { spawn } from 'node:child_process'

import type { LongLanguageCode } from '@/types'
import type { SynthesizeResult } from '@/core/tts/types'
import { LANG, TMP_PATH, TOOLS_PATH, LEON_TOOLKITS_PATH } from '@/constants'
import { TTS } from '@/core'
import { TTSSynthesizerBase } from '@/core/tts/tts-synthesizer-base'
import { LogHelper } from '@/helpers/log-helper'
import { StringHelper } from '@/helpers/string-helper'

/**
 * VALL-E-X as Leon's core voice ("la parole") — a batch, non-streaming
 * counterpart to `LocalSynthesizer`. Runs through the exact same isolated
 * `.venv` and Python module as the agent-callable
 * `tools/music_audio/valle_tts` tool (`ValleTTSTool`), so both entry
 * points share one codebase and one on-disk copy of the downloaded
 * weights (`<LEON_TOOLKITS_PATH>/music_audio/assets/vallex-checkpoint/` —
 * the same path `Tool.getResourcePath('vallex-checkpoint')` resolves to).
 * See the docstring at the top of that tool's
 * `src/python/valle_tts_tool.py` for why this doesn't go through
 * `tcp_server` (the "local" ASR/TTS engine) instead: version-pinning
 * conflicts with `tcp_server`'s own `transformers==4.27.4`.
 *
 * Unlike `LocalSynthesizer`'s event-streaming approach, this returns a
 * real `{ audioFilePath, duration }` once the whole clip is written, the
 * same simple contract `WatsonTTSSynthesizer`/`FliteSynthesizer` use — no
 * TCP dispatch, no dedicated event wiring needed on top of what `TTS.forward()`
 * already does for every non-local synthesizer.
 */
export default class ValleXSynthesizer extends TTSSynthesizerBase {
  protected readonly name = 'VALL-E-X TTS Synthesizer'
  protected readonly lang = LANG as LongLanguageCode
  private readonly scriptPath = path.join(
    TOOLS_PATH,
    'music_audio',
    'valle_tts',
    'src',
    'python',
    'valle_tts_tool.py'
  )
  private readonly resourcePath = path.join(
    LEON_TOOLKITS_PATH,
    'music_audio',
    'assets',
    'vallex-checkpoint'
  )

  constructor(lang: LongLanguageCode) {
    super()

    LogHelper.title(this.name)
    LogHelper.success('New instance')

    this.lang = lang

    if (!fs.existsSync(this.scriptPath)) {
      LogHelper.error(
        `Cannot find ${this.scriptPath}. Did the "tools/music_audio/valle_tts" tool get removed?`
      )
    } else {
      LogHelper.success('Synthesizer initialized')
    }
  }

  private getVenvPythonPath(): string {
    const pythonSourceDir = path.dirname(this.scriptPath)
    const isWindows = process.platform === 'win32'

    return path.join(
      pythonSourceDir,
      '.venv',
      isWindows ? 'Scripts' : 'bin',
      isWindows ? 'python.exe' : 'python'
    )
  }

  /**
   * `lang` here is Leon's own long language code (e.g. `en-US`, `fr-FR`);
   * VALL-E-X only distinguishes English/Chinese/Japanese/mixed, so this
   * narrows to what it understands and otherwise lets it auto-detect.
   */
  private toVallexLanguage(): 'en' | 'zh' | 'ja' | 'auto' {
    if (this.lang.startsWith('en')) return 'en'
    if (this.lang.startsWith('zh')) return 'zh'
    if (this.lang.startsWith('ja')) return 'ja'

    return 'auto'
  }

  public async synthesize(speech: string): Promise<SynthesizeResult | null> {
    const audioFilePath = path.join(
      TMP_PATH,
      `${Date.now()}-${StringHelper.random(4)}.wav`
    )

    let tempDir: string | null = null

    try {
      await fs.promises.mkdir(this.resourcePath, { recursive: true })

      tempDir = await fs.promises.mkdtemp(
        path.join(os.tmpdir(), 'valle_x_synth_')
      )
      const jsonFilePath = path.join(tempDir, 'tasks.json')

      await fs.promises.writeFile(
        jsonFilePath,
        JSON.stringify([
          {
            text: speech,
            output_path: audioFilePath,
            language: this.toVallexLanguage(),
            voice_preset: 'leon'
          }
        ]),
        'utf8'
      )

      const args = [
        this.scriptPath,
        '--function',
        'synthesize_speech',
        '--json_file',
        jsonFilePath,
        '--resource_path',
        this.resourcePath,
        '--device',
        'auto'
      ]

      await new Promise<void>((resolve, reject) => {
        const child = spawn(this.getVenvPythonPath(), args, {
          windowsHide: true
        })
        let stderr = ''

        child.stderr.on('data', (chunk: Buffer) => {
          stderr += chunk.toString()
        })
        child.on('error', reject)
        child.on('close', (code) => {
          if (code === 0) {
            resolve()
          } else {
            reject(new Error(`exited with code ${code}: ${stderr.slice(-2_000)}`))
          }
        })
      })

      const duration = await this.getAudioDuration(audioFilePath)

      TTS.em.emit('saved', duration)

      return {
        audioFilePath,
        duration
      }
    } catch (e) {
      LogHelper.error(`${this.name} - Failed to synthesize speech: ${e}`)

      return null
    } finally {
      if (tempDir) {
        await fs.promises.rm(tempDir, { recursive: true, force: true })
      }
    }
  }
}
