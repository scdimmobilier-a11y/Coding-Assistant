import axios from 'axios'

import { BRAIN } from '@/core'
import { LogHelper } from '@/helpers/log-helper'
import { CONFIG_STATE } from '@/core/config-states/config-state'
import { RoutingMode } from '@/types'

/**
 * Nexus Core <-> Leon bridge client
 * ====================================
 *
 * This is the ONLY new file the Nexus Core integration adds on Leon's
 * side, and `socket-server.ts`'s call site is the ONLY existing file it
 * touches (one import line + one replaced block — see PATCH_NOTES.md).
 * Everything upstream (wake word, ASR, audio capture) and downstream
 * (TTS, the answer queue, the socket/HTTP client protocols) is untouched:
 * this module receives already-transcribed text and hands back text for
 * `BRAIN.talk()` to speak exactly as Leon's native NLU used to.
 *
 * Leon no longer decides HOW to route an utterance — Nexus Core does.
 * This module's only two jobs are:
 *   1. carry text to the bridge and back (mission's "il transporte du
 *      texte dans les deux sens"),
 *   2. remember, per session, whether Nexus Core is mid-pause — so the
 *      NEXT utterance in that session is sent to /resume_paused instead
 *      of starting a fresh turn. The bridge itself tracks the underlying
 *      `goal_key`; Leon only ever needs to know its own `sessionId`.
 */

const NEXUS_BRIDGE_HOST = process.env['NEXUS_BRIDGE_HOST'] || '127.0.0.1'
const NEXUS_BRIDGE_PORT = process.env['NEXUS_BRIDGE_PORT'] || '8420'
const NEXUS_BRIDGE_BASE_URL = `http://${NEXUS_BRIDGE_HOST}:${NEXUS_BRIDGE_PORT}`
const NEXUS_BRIDGE_TIMEOUT_MS = Number(
  process.env['NEXUS_BRIDGE_TIMEOUT_MS'] || 8000
)

interface NexusTurnResult {
  response: string
  mode_used: string
  paused: boolean
  goal_key?: string | null
}

interface ProcessViaNexusBridgeOptions {
  sessionId: string
  ownerMessageId: string
  forcedRoutingMode?: string
  /**
   * Short digest of anything Leon's own memory-manager/persona context
   * assembly already has for this session. Optional — Nexus Core copes
   * fine without it (see nexus_core_leon_bridge/docs/DECISIONS.md,
   * "Memory"). Left undefined for now; wiring PERSONA's existing context
   * digest through here is a same-shaped follow-up, not a redesign.
   */
  leonMemoryDigest?: string
}

// sessionId -> true while Nexus Core is PAUSED and awaiting the human's
// reply for that session. A plain in-memory Map is enough because this
// bridge is a single local process next to Leon (per the mission's "pont
// HTTP local"), same assumption the bridge server itself makes.
const sessionsAwaitingResume = new Map<string, boolean>()

function resolveRoutingMode(forcedRoutingMode?: string): string {
  if (
    forcedRoutingMode === RoutingMode.Controlled ||
    forcedRoutingMode === RoutingMode.Agent ||
    forcedRoutingMode === RoutingMode.Smart
  ) {
    return forcedRoutingMode
  }

  return String(
    CONFIG_STATE.getRoutingModeState().getRoutingMode() || RoutingMode.Smart
  ).toLowerCase()
}

/**
 * Very small placeholder for classifying a reply to a pause confirmation
 * as approval or rejection. Leon already has real sentiment/intent
 * classification inside its native NLU (now bypassed) — swapping this for
 * that (or for a dedicated tiny yes/no intent) is a natural follow-up,
 * intentionally left out of this minimal patch. Defaulting unrecognized
 * replies to "approved" keeps the common case ("yes", "go ahead", "do
 * it") working without a wrong-sounding refusal on unclear input.
 */
function looksLikeRejection(utterance: string): boolean {
  const normalized = utterance.trim().toLowerCase()
  const rejectionWords = [
    'no',
    'nope',
    'cancel',
    'stop',
    'don\u2019t',
    'do not',
    'non',
    'annule'
  ]
  return rejectionWords.some((word) => normalized.includes(word))
}

async function postToBridge(
  path: '/handle_turn' | '/resume_paused',
  body: Record<string, unknown>
): Promise<NexusTurnResult> {
  const response = await axios.post<NexusTurnResult>(
    `${NEXUS_BRIDGE_BASE_URL}${path}`,
    body,
    { timeout: NEXUS_BRIDGE_TIMEOUT_MS }
  )
  return response.data
}

/**
 * Replaces the old `NLU.process(utterance, {...})` call at the
 * interception point in socket-server.ts. Speaks the result through
 * Leon's existing, unmodified `BRAIN.talk()` -> answer-queue -> TTS
 * pipeline, exactly like the native NLU pipeline used to.
 */
export async function processViaNexusBridge(
  utterance: string,
  options: ProcessViaNexusBridgeOptions
): Promise<NexusTurnResult | undefined> {
  const { sessionId, ownerMessageId, forcedRoutingMode, leonMemoryDigest } =
    options
  const mode = resolveRoutingMode(forcedRoutingMode)
  const context: Record<string, unknown> = { owner_message_id: ownerMessageId }
  if (leonMemoryDigest) {
    context['leon_memory_digest'] = leonMemoryDigest
  }

  let result: NexusTurnResult

  try {
    if (sessionsAwaitingResume.get(sessionId)) {
      const approved = !looksLikeRejection(utterance)
      result = await postToBridge('/resume_paused', {
        session_id: sessionId,
        approved,
        human_input: { raw_utterance: utterance },
        context
      })
    } else {
      result = await postToBridge('/handle_turn', {
        user_input: utterance,
        context,
        mode,
        session_id: sessionId
      })
    }
  } catch (e) {
    LogHelper.title('Nexus Bridge')
    LogHelper.error(`Failed to reach the Nexus Core bridge: ${e}`)

    await BRAIN.talk(
      {
        speech:
          "I couldn't reach my reasoning engine just now. Please try again in a moment.",
        text:
          "I couldn't reach my reasoning engine just now. Please try again in a moment."
      },
      true
    )
    return undefined
  }

  sessionsAwaitingResume.set(sessionId, result.paused)

  await BRAIN.talk({ speech: result.response, text: result.response }, true)

  LogHelper.title('Nexus Bridge')
  LogHelper.info(
    `Turn handled by Nexus Core (mode: ${result.mode_used}, paused: ${result.paused})`
  )

  return result
}
