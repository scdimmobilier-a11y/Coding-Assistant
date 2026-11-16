/**
 * Client de l'API backend — Étapes 1a et 1b du prompt de fusion. Un seul
 * fichier pour tous les appels réseau du frontend, pour éviter de disperser
 * des `fetch(...)` ad hoc dans App.tsx (cohérent avec "reste minimal").
 */

import type {
  CodeBranch,
  ConversationSummary,
  NodeRunStatus,
  SecurityFinding,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function jsonOrThrow<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) {
    throw new Error(`${what} a échoué (${res.status})`);
  }
  return res.json() as Promise<T>;
}

/* ── Pipeline ──────────────────────────────────────────────────────────────── */

export interface PhaseInfo {
  id: string;
  nodeCount: number;
}

export interface PipelineNodeEvent {
  type: "node";
  phaseId: string;
  nodeId: string;
  status: NodeRunStatus;
  error?: string;
}
export interface PipelineDoneEvent {
  type: "done";
}
export interface PipelineErrorEvent {
  type: "error";
  message: string;
}
export type PipelineEvent = PipelineNodeEvent | PipelineDoneEvent | PipelineErrorEvent;

export interface RunPipelineResponse {
  run_id: string;
  phases: string[];
}

export interface RetryResponse {
  run_id: string;
}

export async function fetchPhases(): Promise<PhaseInfo[]> {
  const res = await fetch(`${API_BASE}/api/pipeline/phases`);
  return jsonOrThrow(res, "GET /api/pipeline/phases");
}

/** `phase` omis -> pipeline complet (10 phases réelles, voir Étape 1b). */
export async function runPipeline(instruction: string, phase?: string): Promise<RunPipelineResponse> {
  const res = await fetch(`${API_BASE}/api/pipeline/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(phase ? { instruction, phase } : { instruction }),
  });
  return jsonOrThrow(res, "POST /api/pipeline/run");
}

export async function retryNode(nodeId: string): Promise<RetryResponse> {
  const res = await fetch(`${API_BASE}/api/pipeline/nodes/${encodeURIComponent(nodeId)}/retry`, {
    method: "POST",
  });
  return jsonOrThrow(res, `POST /api/pipeline/nodes/${nodeId}/retry`);
}

export async function retryPhase(phaseId: string): Promise<RetryResponse> {
  const res = await fetch(`${API_BASE}/api/pipeline/phases/${encodeURIComponent(phaseId)}/retry`, {
    method: "POST",
  });
  return jsonOrThrow(res, `POST /api/pipeline/phases/${phaseId}/retry`);
}

/**
 * Ouvre le flux SSE pour un run et appelle `onEvent` pour chaque événement
 * reçu. Retourne une fonction pour fermer la connexion manuellement.
 */
export function subscribeToPipelineEvents(runId: string, onEvent: (event: PipelineEvent) => void): () => void {
  const source = new EventSource(`${API_BASE}/api/pipeline/events?run_id=${encodeURIComponent(runId)}`);

  source.onmessage = (message: MessageEvent<string>) => {
    const event = JSON.parse(message.data) as PipelineEvent;
    onEvent(event);
    if (event.type === "done" || event.type === "error") {
      source.close();
    }
  };

  source.onerror = () => {
    // EventSource retente automatiquement après une coupure réseau
    // transitoire ; si le run est déjà terminé, la connexion a déjà été
    // fermée ci-dessus. On ferme explicitement pour éviter une boucle de
    // reconnexion contre un run_id qui n'existe plus côté serveur.
    source.close();
  };

  return () => source.close();
}

/* ── Sécurité ──────────────────────────────────────────────────────────────── */

export async function fetchFindings(): Promise<SecurityFinding[]> {
  const res = await fetch(`${API_BASE}/api/security/findings`);
  return jsonOrThrow(res, "GET /api/security/findings");
}

export async function ignoreFinding(id: string, reason: string, expiresOn: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/security/findings/${encodeURIComponent(id)}/ignore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, expiresOn }),
  });
  if (!res.ok) throw new Error(`POST /api/security/findings/${id}/ignore a échoué (${res.status})`);
}

export async function unignoreFinding(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/security/findings/${encodeURIComponent(id)}/unignore`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`POST /api/security/findings/${id}/unignore a échoué (${res.status})`);
}

/* ── Génération de code ───────────────────────────────────────────────────── */

export async function fetchBranches(): Promise<CodeBranch[]> {
  const res = await fetch(`${API_BASE}/api/codegen/branches`);
  return jsonOrThrow(res, "GET /api/codegen/branches");
}

export async function acceptFile(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/codegen/files/${encodeURIComponent(id)}/accept`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /api/codegen/files/${id}/accept a échoué (${res.status})`);
}

export async function requestFileFix(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/codegen/files/${encodeURIComponent(id)}/request-fix`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /api/codegen/files/${id}/request-fix a échoué (${res.status})`);
}

/* ── Conversations ────────────────────────────────────────────────────────── */

export interface ConversationDetail extends ConversationSummary {
  transcript: unknown[];
}

export async function createConversation(
  id: string,
  title: string,
  date: string,
  transcript: unknown[],
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, title, date, transcript }),
  });
  if (!res.ok) throw new Error(`POST /api/conversations a échoué (${res.status})`);
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  const res = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(id)}`);
  return jsonOrThrow(res, `GET /api/conversations/${id}`);
}
