/**
 * Types partagés de l'interface Nexus Assistant.
 *
 * Ces types sont écrits pour correspondre au vocabulaire du backend
 * nexus_compose : phases du pipeline (8), nœuds (169), outils vendorisés (14).
 * Le jour où le backend expose un flux temps réel (WebSocket / SSE), ces
 * types sont ceux que le producteur d'événements doit respecter.
 */

export type MessageRole = "user" | "system";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  time: string;
}

/** Résumé d'une conversation passée, pour le panneau d'historique du menu Header. */
export interface ConversationSummary {
  id: string;
  title: string;
  date: string;
}

export type ApiConnectionResult = "success" | "error";

/* ── Fournisseurs LLM (dashboard "Connexion API") ─────────────────────────────
 *
 * Reflète exactement l'objet renvoyé par api/providers.py (jamais la clé API
 * en clair — voir `apiKeyMasked`/`hasApiKey`) et les règles de validation de
 * api/provider_validation.py. Voir ApiProviderForm.tsx pour le formulaire et
 * ApiConnectionDialog.tsx pour le dashboard (liste + installation).
 */

/** Catalogue de fournisseurs proposés par le menu déroulant — "custom" et
 * "other" acceptent n'importe quel endpoint compatible HTTP saisi par
 * l'utilisateur ; les autres sont de simples pré-remplissages courants. */
export const PROVIDER_CATALOG = [
  { value: "custom", label: "Personnalisé" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "google_gemini", label: "Google Gemini" },
  { value: "nvidia", label: "NVIDIA" },
  { value: "groq", label: "Groq" },
  { value: "mistral", label: "Mistral" },
  { value: "ollama", label: "Ollama" },
  { value: "lm_studio", label: "LM Studio" },
  { value: "vllm", label: "vLLM" },
  { value: "other", label: "Autre..." },
] as const;

export type ProviderCatalogValue = (typeof PROVIDER_CATALOG)[number]["value"];

export const API_TYPE_CATALOG = [
  { value: "chat_completions", label: "Chat Completions" },
  { value: "responses", label: "Responses" },
  { value: "embeddings", label: "Embeddings" },
  { value: "images", label: "Images" },
  { value: "audio", label: "Audio" },
  { value: "custom", label: "Custom" },
] as const;

export type ApiTypeValue = (typeof API_TYPE_CATALOG)[number]["value"];

export const AUTH_TYPE_CATALOG = [
  { value: "bearer", label: "Bearer Token" },
  { value: "api_key", label: "API Key" },
  { value: "basic", label: "Basic" },
  { value: "none", label: "Aucun" },
] as const;

export type AuthTypeValue = (typeof AUTH_TYPE_CATALOG)[number]["value"];

/** Un fournisseur LLM installé, tel que renvoyé par GET/POST/PATCH
 * /api/providers — la clé API n'est jamais présente en clair. */
export interface LlmProvider {
  id: string;
  provider: string;
  label: string;
  model: string;
  endpoint: string;
  apiType: ApiTypeValue;
  authType: AuthTypeValue;
  hasApiKey: boolean;
  apiKeyMasked: string | null;
  headers: Record<string, string>;
  timeoutS: number;
  maxRetries: number;
  http2: boolean;
  compression: boolean;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

/** Corps envoyé à POST /api/providers (installation) et POST /api/providers/test
 * (test d'un brouillon avant installation). */
export interface LlmProviderInput {
  provider: string;
  label: string;
  model: string;
  endpoint: string;
  apiType: ApiTypeValue;
  authType: AuthTypeValue;
  apiKey: string;
  headers: Record<string, string>;
  timeoutS: number;
  maxRetries: number;
  http2: boolean;
  compression: boolean;
}

/** Corps envoyé à PATCH /api/providers/{id} — tous les champs optionnels. */
export type LlmProviderPatch = Partial<LlmProviderInput>;

export interface ProviderTestResult {
  status: ApiConnectionResult;
  httpStatus: number | null;
  message: string;
  attempts: number;
}

/** Erreur de validation renvoyée par le backend (HTTP 422), un champ à la fois. */
export interface ProviderValidationError {
  field: string;
  message: string;
}

/* ── Pipeline (vue gauche) ─────────────────────────────────────────────────── */

export type NodeRunStatus = "pending" | "running" | "done" | "failed";

/** Un nœud individuel de l'orchestrateur (nexus_compose/orchestrator.py). */
export interface PipelineNode {
  id: string;
  /** Identifiant technique du nœud, ex. "bearer.bearer_scan". */
  tag: string;
  status: NodeRunStatus;
  /** Présent seulement si status === "failed". */
  error?: string;
}

/** Un des 8 groupes de phases de l'orchestrateur. */
export interface PipelinePhase {
  id: string;
  label: string;
  nodes: PipelineNode[];
}

export function phaseStatus(phase: PipelinePhase): NodeRunStatus {
  if (phase.nodes.some((n) => n.status === "failed")) return "failed";
  if (phase.nodes.every((n) => n.status === "done")) return "done";
  if (phase.nodes.some((n) => n.status === "running")) return "running";
  return "pending";
}

export function phaseProgress(phase: PipelinePhase): number {
  if (phase.nodes.length === 0) return 0;
  const done = phase.nodes.filter((n) => n.status === "done").length;
  return Math.round((done / phase.nodes.length) * 100);
}

/* ── Onglets ───────────────────────────────────────────────────────────────── */

export type TabId = "network" | "coding" | "security" | "registry";

/** Statut d'un des 14 outils vendorisés (pour la ligne de pastilles en bas de vue). */
export interface ToolStatus {
  id: string;
  label: string;
  passed: boolean;
}

/* ── Diagramme C4 (vue "Network") ─────────────────────────────────────────── */

export type NodeTone = "blue" | "purple" | "amber" | "green" | "red" | "gray";
export type NodeKind = "person" | "container" | "external" | "component";
export type C4Level = "system" | "container" | "component";

export interface DiagramNode {
  id: string;
  kind: NodeKind;
  tone: NodeTone;
  /** true = contour en pointillés (système externe, élément non confirmé). */
  dashed?: boolean;
  title: string;
  /** Ligne de métadonnées courte affichée dans la boîte, ex. "[Container]". */
  meta: string;
  /** Ligne de détail technique affichée dans la boîte. */
  detail?: string;

  /* Métadonnées enrichies, affichées dans le panneau de détail au clic. */
  technology?: string[];
  tags?: string[];
  owner?: string;
  linkedThreats?: string[];
  /** true = ce nœud a une vue "component" à explorer (bouton "Voir les composants"). */
  drillable?: boolean;
}

/* ── Vue Coding (fork-join de génération) ─────────────────────────────────── */

export type FileReviewStatus = "pending" | "accepted" | "needs-fix";

export interface GeneratedFile {
  id: string;
  path: string;
  summary: string;
  linesAdded: number;
  linesRemoved: number;
  status: FileReviewStatus;
}

export type BranchStatus = "running" | "done" | "failed";

export interface CodeBranch {
  id: string;
  label: string;
  agent: string;
  status: BranchStatus;
  files: GeneratedFile[];
}

/* ── Vue Sécurité ──────────────────────────────────────────────────────────── */

export type FindingSeverity = "critical" | "warning" | "info";

export interface SecurityFinding {
  id: string;
  tool: string;
  severity: FindingSeverity;
  title: string;
  detail: string;
  /** Nœud du diagramme C4 concerné, pour le lien vers l'analyse d'accessibilité. */
  relatedNodeId?: string;
  /**
   * Résultat d'une requête d'accessibilité sur le graphe de menaces Neo4j :
   * ce chemin est-il réellement atteignable depuis l'acteur d'entrée (Marchand) ?
   * undefined = accessibilité non évaluée pour ce type de finding.
   */
  reachableFromEntry?: boolean;
  ignored?: {
    reason: string;
    expiresOn: string;
  };
}

/* ── Registre (vue "Registry" / Nexus Studio, Mission 2 D5.1) ────────────────
 * Miroir camelCase, pour rester dans la convention de CE fichier (cf.
 * LlmProvider, PipelinePhase, ...), du contrat JSON snake_case documenté
 * dans Nexus_Assistant/docs/registry_schema.md — volontairement snake_case
 * sur le fil pour que nexus_compose et Nexus Brain (deux dépôts distincts,
 * sans import Python croisé) émettent exactement la même forme sans avoir
 * chacun à connaître une convention "frontend". Le mappage snake_case ->
 * camelCase se fait au même endroit que celui de providersApi.ts : dans
 * lib/registryApi.ts, jamais ici. */

export interface RegistryNode {
  id: string;
  module: string;
  moduleName: string;
  function: string;
  description: string;
  tag: string;
  /** Une des 9 phases du pipeline nexus_compose, ou "brain" pour un
   * composant cognitif Niveau 1 de Nexus Brain (hors pipeline). */
  phase: string;
  type: string;
  ioIn: string;
  ioOut: string;
  /** Fichier ou point d'entrée du code source réel. */
  ref: string;
  repo: string;
  virtual: boolean;
  subsection: string | null;
  capabilities: string[];
}

export interface RegistryEdge {
  source: string;
  target: string;
  label: string;
  type: string;
}

export interface Registry {
  nodes: RegistryNode[];
  edges: RegistryEdge[];
}
