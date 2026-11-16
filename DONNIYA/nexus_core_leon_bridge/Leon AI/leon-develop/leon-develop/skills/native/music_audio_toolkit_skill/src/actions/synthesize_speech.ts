import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import type { ActionFunction, ActionParams } from '@sdk/types'
import { leon } from '@sdk/leon'
import { ParamsHelper } from '@sdk/params-helper'
import { Settings } from '@sdk/settings'
import ToolManager, { isMissingToolSettingsError } from '@sdk/tool-manager'
import ValleTTSTool from '@tools/music_audio/valle_tts'
import { formatFilePath } from '@sdk/utils'

interface SynthesizeSpeechSettings extends Record<string, unknown> {
  valle_language?: 'auto' | 'en' | 'zh' | 'ja' | 'mix'
  valle_voice_preset?: string
  valle_device?: 'auto' | 'cpu' | 'cuda'
}

function sanitizeFileName(value: string): string {
  const sanitized = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')

  return sanitized || 'speech'
}

/**
 * Speaks arbitrary text with VALL-E-X — Leon's "voice" tool ("la parole"),
 * usable directly by the LLM agent or chained after another skill (e.g.
 * read back a summary, or narrate translated text) via `speech_text`'s
 * context-data fallback.
 */
export const run: ActionFunction = async function (
  _params: ActionParams,
  paramsHelper: ParamsHelper
) {
  const speechText =
    paramsHelper.getActionArgument('speech_text') ||
    (paramsHelper.findActionArgumentFromContext('speech_text') as string) ||
    (paramsHelper.getContextData('speech_text') as string)

  if (!speechText) {
    leon.answer({ key: 'missing_speech_text' })
    return
  }

  try {
    const settings = new Settings<SynthesizeSpeechSettings>()
    const language = ((await settings.get('valle_language')) ||
      'auto') as NonNullable<SynthesizeSpeechSettings['valle_language']>
    const voicePreset = (await settings.get('valle_voice_preset')) as
      | string
      | undefined
    const device = ((await settings.get('valle_device')) ||
      'auto') as NonNullable<SynthesizeSpeechSettings['valle_device']>

    const referenceAudioPath = paramsHelper.getActionArgument(
      'reference_audio_path'
    ) as string | undefined

    const outputDir = await fs.promises.mkdtemp(
      path.join(os.tmpdir(), 'valle_tts_')
    )
    const outputPath = path.join(
      outputDir,
      `${sanitizeFileName(speechText.slice(0, 64))}.wav`
    )

    leon.answer({ key: 'synthesis_started' })

    const tool = await ToolManager.initTool(ValleTTSTool)
    await tool.synthesizeSpeech(
      {
        text: speechText,
        output_path: outputPath,
        language,
        voice_preset: voicePreset,
        reference_audio_path: referenceAudioPath
      },
      device
    )

    if (!fs.existsSync(outputPath)) {
      leon.answer({
        key: 'synthesis_error',
        data: { error: 'Output audio file not found' }
      })
      return
    }

    leon.answer({
      key: 'synthesis_completed',
      data: {
        audio_path: formatFilePath(outputPath)
      },
      core: {
        context_data: {
          audio_path: outputPath
        }
      }
    })
  } catch (error) {
    if (isMissingToolSettingsError(error)) {
      return
    }
    leon.answer({
      key: 'synthesis_error',
      data: { error: (error as Error).message },
      core: {
        should_stop_skill: true
      }
    })
  }
}
