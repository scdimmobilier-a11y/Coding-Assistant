import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'
import { spawn } from 'node:child_process'

import { ASRParserBase } from '@/core/asr/asr-parser-base'
import { TMP_PATH, TOOLS_PATH, LEON_TOOLKITS_PATH } from '@/constants'
import { LogHelper } from '@/helpers/log-helper'
import { StringHelper } from '@/helpers/string-helper'

interface TranscriptionSegment {
  from: number
  to: number
  text: string
  speaker: string | null
}

interface TranscriptionOutput {
  duration: number
  speakers: string[]
  speaker_count: number
  segments: TranscriptionSegment[]
  metadata: { tool: string }
}

/**
 * Audio Flamingo 3 as Leon's core "ears" ("l'audition") — a batch,
 * buffer-in/text-out ASR parser matching `WatsonASRParser`'s simple
 * contract (see that file's now-commented-out source for the template
 * this follows), rather than `LocalParser`'s TCP-streaming one: AF3
 * processes a whole clip in one call, it doesn't stream partial words.
 *
 * Runs through the exact same isolated `.venv` and Python module as the
 * agent-callable `tools/music_audio/audio_flamingo` tool
 * (`AudioFlamingoTool`) — one codebase, one on-disk copy of the
 * downloaded model — see that tool's `src/nodejs/audio_flamingo-tool.ts`
 * docstring for why this doesn't run inside `tcp_server` instead
 * (`transformers` version conflict with `tcp_server`'s pinned
 * `transformers==4.27.4`).
 *
 * This only covers the speech-to-text half of what AF3 can do; its
 * broader non-speech audio *understanding* (describe a sound, answer a
 * question about a clip) is exposed separately as the
 * `understand_audio` skill action, since that's a free-form Q&A shape
 * `ASRParserBase.parse(buffer) -> string` has no room for.
 */
export default class AudioFlamingoParser extends ASRParserBase {
  protected readonly name = 'Audio Flamingo 3 ASR Parser'
  private readonly scriptPath = path.join(
    TOOLS_PATH,
    'music_audio',
    'audio_flamingo',
    'src',
    'python',
    'audio_flamingo_tool.py'
  )
  private readonly resourcePath = path.join(
    LEON_TOOLKITS_PATH,
    'music_audio',
    'assets',
    'audio-flamingo-3-hf'
  )

  constructor() {
    super()

    LogHelper.title(this.name)
    LogHelper.success('New instance')

    if (!fs.existsSync(this.scriptPath)) {
      LogHelper.error(
        `Cannot find ${this.scriptPath}. Did the "tools/music_audio/audio_flamingo" tool get removed?`
      )
    } else {
      LogHelper.success('Parser initialized')
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
   * Read audio buffer and return the transcript (decoded string)
   */
  public async parse(buffer: Buffer): Promise<string | null> {
    const audioFilePath = path.join(
      TMP_PATH,
      `${Date.now()}-${StringHelper.random(4)}.wav`
    )
    let tempDir: string | null = null

    try {
      await fs.promises.mkdir(this.resourcePath, { recursive: true })
      await fs.promises.writeFile(audioFilePath, buffer)

      tempDir = await fs.promises.mkdtemp(
        path.join(os.tmpdir(), 'audio_flamingo_parse_')
      )
      const jsonFilePath = path.join(tempDir, 'tasks.json')
      const transcriptionPath = path.join(tempDir, 'transcription.json')

      await fs.promises.writeFile(
        jsonFilePath,
        JSON.stringify([
          { audio_path: audioFilePath, output_path: transcriptionPath }
        ]),
        'utf8'
      )

      const args = [
        this.scriptPath,
        '--function',
        'transcribe_audio',
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

      const transcription = JSON.parse(
        await fs.promises.readFile(transcriptionPath, 'utf8')
      ) as TranscriptionOutput

      return transcription.segments.map((segment) => segment.text).join('\n')
    } catch (e) {
      LogHelper.error(`${this.name} - Failed to parse: ${e}`)

      return null
    } finally {
      if (fs.existsSync(audioFilePath)) {
        fs.unlinkSync(audioFilePath)
      }
      if (tempDir) {
        await fs.promises.rm(tempDir, { recursive: true, force: true })
      }
    }
  }
}
