import fs from 'node:fs'

import type { ActionFunction, ActionParams } from '@sdk/types'
import { leon } from '@sdk/leon'
import { ParamsHelper } from '@sdk/params-helper'
import { Settings } from '@sdk/settings'
import ToolManager, { isMissingToolSettingsError } from '@sdk/tool-manager'
import AudioFlamingoTool from '@tools/music_audio/audio_flamingo'
import { formatFilePath } from '@sdk/utils'

interface UnderstandAudioSettings extends Record<string, unknown> {
  audio_flamingo_device?: 'auto' | 'cpu' | 'cuda'
}

/**
 * General audio understanding via Audio Flamingo 3 — Leon's "hearing"
 * tool ("l'audition") beyond plain transcription: what's happening
 * acoustically, what instrument/genre/mood, "what is that sound",
 * describe this recording, etc. For speech-to-text specifically, prefer
 * `transcribe_audio` (which can also use `audio_flamingo` as its
 * `transcription_provider` — see that action's settings).
 */
export const run: ActionFunction = async function (
  _params: ActionParams,
  paramsHelper: ParamsHelper
) {
  const audioPathArg =
    paramsHelper.getActionArgument('audio_path') ||
    (paramsHelper.findActionArgumentFromContext('audio_path') as string)
  const audioPath = audioPathArg || paramsHelper.getContextData('audio_path')

  const question = paramsHelper.getActionArgument('question') as
    | string
    | undefined

  if (!audioPath || !fs.existsSync(audioPath)) {
    leon.answer({ key: 'audio_not_found' })
    return
  }

  try {
    const settings = new Settings<UnderstandAudioSettings>()
    const device = ((await settings.get('audio_flamingo_device')) ||
      'auto') as NonNullable<UnderstandAudioSettings['audio_flamingo_device']>

    leon.answer({
      key: 'understanding_started',
      data: { audio_path: formatFilePath(audioPath) }
    })

    const tool = await ToolManager.initTool(AudioFlamingoTool)
    const [result] = await tool.understandAudio(
      { audio_path: audioPath, question },
      device
    )

    const answer = result?.answer as string | undefined
    if (!answer) {
      leon.answer({
        key: 'understanding_error',
        data: { error: 'No answer returned' }
      })
      return
    }

    leon.answer({
      key: 'understanding_completed',
      data: { answer },
      core: {
        context_data: { audio_understanding_answer: answer }
      }
    })
  } catch (error) {
    if (isMissingToolSettingsError(error)) {
      return
    }
    leon.answer({
      key: 'understanding_error',
      data: { error: (error as Error).message },
      core: {
        should_stop_skill: true
      }
    })
  }
}
