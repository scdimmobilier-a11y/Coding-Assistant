import type LocalParser from '@/core/asr/parsers/local-parser'
import type AudioFlamingoParser from '@/core/asr/parsers/audio-flamingo-parser'
// import type CoquiASRParser from '@/core/asr/parsers/coqui-asr-parser'
// import type GoogleCloudASRParser from '@/core/asr/parsers/google-cloud-asr-parser'
// import type WatsonASRParser from '@/core/asr/parsers/watson-asr-parser'

export type ASRAudioFormat = 'wav' | 'webm'

export enum ASRProviders {
  Local = 'local',
  AudioFlamingo = 'audio-flamingo'
  // GoogleCloudASR = 'google-cloud-asr',
  // WatsonASR = 'watson-asr',
  // CoquiASR = 'coqui-asr'
}

export enum ASRParserNames {
  Local = 'local-parser',
  AudioFlamingo = 'audio-flamingo-parser'
  // GoogleCloudASR = 'google-cloud-asr-parser',
  // WatsonASR = 'watson-asr-parser',
  // CoquiASR = 'coqui-asr-parser'
}

export type ASRParser =
  | LocalParser
  | AudioFlamingoParser
  // | GoogleCloudASRParser
  // | WatsonASRParser
  // | CoquiASRParser
  | undefined
