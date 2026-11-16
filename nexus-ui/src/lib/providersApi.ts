/**
 * Client de l'API "Connexion API" (dashboard des fournisseurs LLM) —
 * GET/POST/PATCH/DELETE /api/providers, activate/deactivate, test de
 * connexion. Même convention que pipelineApi.ts (API_BASE, jsonOrThrow).
 *
 * Le backend (api/providers.py) répond déjà en camelCase pour tout ce qui
 * est LU (LlmProvider, ProviderTestResult) — seul ce qui est ENVOYÉ dans le
 * corps d'une requête (création/mise à jour) doit être converti en
 * snake_case, format attendu par les modèles Pydantic ProviderIn/Patch.
 */

import type {
  LlmProvider,
  LlmProviderInput,
  LlmProviderPatch,
  ProviderTestResult,
  ProviderValidationError,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

/** Erreur de validation (HTTP 422) remontée telle quelle depuis le backend,
 * pour que le formulaire puisse surligner le champ fautif. */
export class ProviderValidationApiError extends Error {
  field: string;
  constructor(detail: ProviderValidationError) {
    super(detail.message);
    this.field = detail.field;
  }
}

async function jsonOrThrow<T>(res: Response, what: string): Promise<T> {
  if (res.status === 422) {
    const body = await res.json().catch(() => null);
    if (body?.detail?.field) throw new ProviderValidationApiError(body.detail);
  }
  if (!res.ok) {
    throw new Error(`${what} a échoué (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function toApiPayload(input: LlmProviderInput) {
  return {
    provider: input.provider,
    label: input.label,
    model: input.model,
    endpoint: input.endpoint,
    api_type: input.apiType,
    auth_type: input.authType,
    api_key: input.apiKey || null,
    headers: input.headers,
    timeout_s: input.timeoutS,
    max_retries: input.maxRetries,
    http2: input.http2,
    compression: input.compression,
  };
}

function toApiPatchPayload(patch: LlmProviderPatch) {
  const out: Record<string, unknown> = {};
  if (patch.provider !== undefined) out.provider = patch.provider;
  if (patch.label !== undefined) out.label = patch.label;
  if (patch.model !== undefined) out.model = patch.model;
  if (patch.endpoint !== undefined) out.endpoint = patch.endpoint;
  if (patch.apiType !== undefined) out.api_type = patch.apiType;
  if (patch.authType !== undefined) out.auth_type = patch.authType;
  if (patch.apiKey !== undefined) out.api_key = patch.apiKey || null;
  if (patch.headers !== undefined) out.headers = patch.headers;
  if (patch.timeoutS !== undefined) out.timeout_s = patch.timeoutS;
  if (patch.maxRetries !== undefined) out.max_retries = patch.maxRetries;
  if (patch.http2 !== undefined) out.http2 = patch.http2;
  if (patch.compression !== undefined) out.compression = patch.compression;
  return out;
}

export async function listProviders(): Promise<LlmProvider[]> {
  const res = await fetch(`${API_BASE}/api/providers`);
  return jsonOrThrow(res, "GET /api/providers");
}

export async function installProvider(input: LlmProviderInput): Promise<LlmProvider> {
  const res = await fetch(`${API_BASE}/api/providers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(toApiPayload(input)),
  });
  return jsonOrThrow(res, "POST /api/providers");
}

export async function updateProvider(id: string, patch: LlmProviderPatch): Promise<LlmProvider> {
  const res = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(toApiPatchPayload(patch)),
  });
  return jsonOrThrow(res, `PATCH /api/providers/${id}`);
}

export async function deleteProvider(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(id)}`, { method: "DELETE" });
  return jsonOrThrow(res, `DELETE /api/providers/${id}`);
}

export async function activateProvider(id: string): Promise<LlmProvider> {
  const res = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(id)}/activate`, { method: "POST" });
  return jsonOrThrow(res, `POST /api/providers/${id}/activate`);
}

export async function deactivateProvider(id: string): Promise<LlmProvider> {
  const res = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(id)}/deactivate`, { method: "POST" });
  return jsonOrThrow(res, `POST /api/providers/${id}/deactivate`);
}

/** Teste un fournisseur déjà installé (reprend sa clé API enregistrée). */
export async function testSavedProvider(id: string): Promise<ProviderTestResult> {
  const res = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(id)}/test`, { method: "POST" });
  return jsonOrThrow(res, `POST /api/providers/${id}/test`);
}

/** Teste un brouillon AVANT de l'installer — ne touche jamais la base. */
export async function testDraftProvider(input: LlmProviderInput): Promise<ProviderTestResult> {
  const res = await fetch(`${API_BASE}/api/providers/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(toApiPayload(input)),
  });
  return jsonOrThrow(res, "POST /api/providers/test");
}
