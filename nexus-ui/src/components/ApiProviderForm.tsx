import { useState } from "react";
import { Loader2, Plus, Trash2, CheckCircle2, XCircle, Eye, EyeOff } from "lucide-react";
import {
  PROVIDER_CATALOG,
  API_TYPE_CATALOG,
  AUTH_TYPE_CATALOG,
  type LlmProvider,
  type LlmProviderInput,
  type ProviderTestResult,
} from "../types";
import { testDraftProvider, testSavedProvider, ProviderValidationApiError } from "../lib/providersApi";

/**
 * Formulaire d'installation / modification d'un fournisseur LLM — reprend
 * les champs et règles du document fourni pour le pop-up "Connexion API" :
 * fournisseur, modèle, endpoint (HTTPS obligatoire), clé API (masquée),
 * type d'API, en-têtes personnalisés, authentification, paramètres réseau,
 * et un vrai bouton "Tester la connexion". La validation stricte
 * (RFC3986, longueurs, jeux de caractères) est appliquée par le backend
 * (api/provider_validation.py) ; ce formulaire ne fait qu'une validation
 * légère côté client pour un retour immédiat, jamais la source de vérité.
 */

/** Pré-remplissage indicatif par fournisseur connu — n'écrase jamais un
 * champ déjà modifié par l'utilisateur, et reste modifiable dans tous les
 * cas ("Personnalisé"/"Autre..." n'ont pas de pré-remplissage). */
const PROVIDER_DEFAULTS: Record<string, { endpoint?: string; modelPlaceholder: string; authType: LlmProviderInput["authType"] }> = {
  openai: { endpoint: "https://api.openai.com/v1/chat/completions", modelPlaceholder: "gpt-4.1", authType: "bearer" },
  anthropic: { endpoint: "https://api.anthropic.com/v1/messages", modelPlaceholder: "claude-opus-4", authType: "api_key" },
  openrouter: { endpoint: "https://openrouter.ai/api/v1/chat/completions", modelPlaceholder: "openai/gpt-oss-120b", authType: "bearer" },
  google_gemini: { endpoint: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", modelPlaceholder: "gemini-2.5-pro", authType: "bearer" },
  nvidia: { endpoint: "https://integrate.api.nvidia.com/v1/chat/completions", modelPlaceholder: "meta/llama-3.3-70b-instruct", authType: "bearer" },
  groq: { endpoint: "https://api.groq.com/openai/v1/chat/completions", modelPlaceholder: "llama-3.3-70b-versatile", authType: "bearer" },
  mistral: { endpoint: "https://api.mistral.ai/v1/chat/completions", modelPlaceholder: "mistral-large-latest", authType: "bearer" },
  ollama: { endpoint: "http://localhost:11434/v1/chat/completions", modelPlaceholder: "llama3.3", authType: "none" },
  lm_studio: { endpoint: "http://localhost:1234/v1/chat/completions", modelPlaceholder: "kimi-k2", authType: "none" },
  vllm: { endpoint: "http://localhost:8000/v1/chat/completions", modelPlaceholder: "deepseek-r1", authType: "none" },
  custom: { modelPlaceholder: "gpt-5.5", authType: "bearer" },
  other: { modelPlaceholder: "gpt-5.5", authType: "bearer" },
};

const MODEL_RE = /^[A-Za-z0-9._/:-]{1,128}$/;
const API_KEY_RE = /^[A-Za-z0-9._~-]{16,512}$/;
const HEADER_NAME_RE = /^[A-Za-z0-9-]{1,64}$/;

interface HeaderRow {
  id: string;
  name: string;
  value: string;
}

function headersToRows(headers: Record<string, string>): HeaderRow[] {
  return Object.entries(headers).map(([name, value], i) => ({ id: `h${i}-${name}`, name, value }));
}

interface FieldError {
  field: string;
  message: string;
}

interface ApiProviderFormProps {
  /** Présent = édition d'un fournisseur existant ; absent = installation. */
  editing?: LlmProvider;
  onCancel: () => void;
  /** Résout une fois l'enregistrement (création ou mise à jour) terminé côté backend. */
  onSave: (input: LlmProviderInput, apiKeyTouched: boolean) => Promise<void>;
}

export default function ApiProviderForm({ editing, onCancel, onSave }: ApiProviderFormProps) {
  const [provider, setProvider] = useState(editing?.provider ?? "custom");
  const [label, setLabel] = useState(editing?.label ?? "");
  const [model, setModel] = useState(editing?.model ?? "");
  const [endpoint, setEndpoint] = useState(editing?.endpoint ?? "");
  const [apiType, setApiType] = useState<LlmProviderInput["apiType"]>(editing?.apiType ?? "chat_completions");
  const [authType, setAuthType] = useState<LlmProviderInput["authType"]>(editing?.authType ?? "bearer");
  const [apiKey, setApiKey] = useState("");
  const [apiKeyTouched, setApiKeyTouched] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [headers, setHeaders] = useState<HeaderRow[]>(editing ? headersToRows(editing.headers) : []);
  const [timeoutS, setTimeoutS] = useState(editing?.timeoutS ?? 30);
  const [maxRetries, setMaxRetries] = useState(editing?.maxRetries ?? 3);
  const [http2, setHttp2] = useState(editing?.http2 ?? true);
  const [compression, setCompression] = useState(editing?.compression ?? true);

  const [fieldError, setFieldError] = useState<FieldError | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);

  function applyProviderDefaults(next: string) {
    setProvider(next);
    const defaults = PROVIDER_DEFAULTS[next];
    if (!defaults) return;
    if (!endpoint.trim() && defaults.endpoint) setEndpoint(defaults.endpoint);
    if (!editing) setAuthType(defaults.authType);
  }

  function buildInput(): LlmProviderInput {
    return {
      provider,
      label: label.trim() || PROVIDER_CATALOG.find((p) => p.value === provider)?.label || provider,
      model: model.trim(),
      endpoint: endpoint.trim(),
      apiType,
      authType,
      apiKey: apiKey.trim(),
      headers: Object.fromEntries(headers.filter((h) => h.name.trim()).map((h) => [h.name.trim(), h.value])),
      timeoutS,
      maxRetries,
      http2,
      compression,
    };
  }

  /** Validation légère côté client — retour immédiat sur les erreurs les
   * plus courantes ; le backend reste la source de vérité (voir
   * api/provider_validation.py, mêmes règles). */
  function validateClientSide(input: LlmProviderInput): FieldError | null {
    if (!input.model || !MODEL_RE.test(input.model)) {
      return { field: "model", message: "1 à 128 caractères parmi A-Z a-z 0-9 . _ - / :" };
    }
    if (!input.endpoint) {
      return { field: "endpoint", message: "URL requise" };
    }
    try {
      const url = new URL(input.endpoint);
      const isLocal = ["localhost", "127.0.0.1", "0.0.0.0"].includes(url.hostname) || url.hostname.endsWith(".localhost");
      if (url.protocol === "http:" && !isLocal) {
        return { field: "endpoint", message: "HTTPS obligatoire (http:// réservé à un hôte local/privé auto-hébergé)" };
      }
      if (url.protocol !== "https:" && url.protocol !== "http:") {
        return { field: "endpoint", message: `schéma « ${url.protocol} » interdit` };
      }
    } catch {
      return { field: "endpoint", message: "URL invalide (RFC 3986)" };
    }
    const needsKey = authType !== "none";
    const keyProvided = editing ? apiKeyTouched : true;
    if (needsKey && keyProvided && !API_KEY_RE.test(input.apiKey)) {
      return { field: "api_key", message: "16 à 512 caractères parmi A-Z a-z 0-9 - _ . ~, sans espace" };
    }
    if (needsKey && !editing && !input.apiKey) {
      return { field: "api_key", message: "clé API requise pour ce mode d'authentification" };
    }
    for (const h of headers) {
      if (!h.name.trim()) continue;
      if (!HEADER_NAME_RE.test(h.name)) {
        return { field: "headers", message: `nom d'en-tête invalide : ${h.name}` };
      }
      if (h.name.toLowerCase() === "authorization") {
        return { field: "headers", message: "l'en-tête Authorization est géré par « Authentification » ci-dessus" };
      }
      if (/[\r\n\x00]/.test(h.value)) {
        return { field: "headers", message: `valeur d'en-tête invalide pour ${h.name}` };
      }
    }
    return null;
  }

  async function handleTest() {
    const input = buildInput();
    const clientError = validateClientSide(input);
    if (clientError) {
      setFieldError(clientError);
      setTestResult(null);
      return;
    }
    setFieldError(null);
    setTesting(true);
    setTestResult(null);
    try {
      // En édition, si la clé n'a pas été retouchée, on ne peut pas tester
      // un brouillon (le backend ne connaît pas la clé enregistrée côté
      // serveur) — on teste alors le fournisseur déjà enregistré via son id
      // plutôt qu'un brouillon local.
      if (editing && !apiKeyTouched) {
        setTestResult(await testSavedProvider(editing.id));
      } else {
        setTestResult(await testDraftProvider(input));
      }
    } catch (err) {
      if (err instanceof ProviderValidationApiError) {
        setFieldError({ field: err.field, message: err.message });
      } else {
        setTestResult({ status: "error", httpStatus: null, message: "Impossible de joindre le backend Nexus.", attempts: 1 });
      }
    } finally {
      setTesting(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const input = buildInput();
    const clientError = validateClientSide(input);
    if (clientError) {
      setFieldError(clientError);
      return;
    }
    setFieldError(null);
    setSaving(true);
    try {
      await onSave(input, apiKeyTouched);
    } catch (err) {
      if (err instanceof ProviderValidationApiError) {
        setFieldError({ field: err.field, message: err.message });
      } else {
        setFieldError({ field: "_global", message: "Échec de l'enregistrement — vérifiez la connexion au backend Nexus." });
      }
    } finally {
      setSaving(false);
    }
  }

  function addHeaderRow() {
    setHeaders((prev) => [...prev, { id: crypto.randomUUID(), name: "", value: "" }]);
  }
  function updateHeaderRow(id: string, patch: Partial<HeaderRow>) {
    setHeaders((prev) => prev.map((h) => (h.id === id ? { ...h, ...patch } : h)));
  }
  function removeHeaderRow(id: string) {
    setHeaders((prev) => prev.filter((h) => h.id !== id));
  }

  const errorFor = (field: string) => (fieldError?.field === field ? fieldError.message : null);
  const modelDefaults = PROVIDER_DEFAULTS[provider];

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* ── Fournisseur ── */}
      <label className="block text-xs font-medium text-gray-600">
        Fournisseur
        <select
          value={provider}
          onChange={(e) => applyProviderDefaults(e.target.value)}
          className="mt-1 w-full rounded-md border border-gray-200 bg-white px-2.5 py-2 text-sm outline-none transition focus:border-blue-400"
        >
          {PROVIDER_CATALOG.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </label>

      {/* ── Nom (usage interne, pour distinguer plusieurs installations) ── */}
      <label className="block text-xs font-medium text-gray-600">
        Nom
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={PROVIDER_CATALOG.find((p) => p.value === provider)?.label ?? "Mon fournisseur"}
          className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm outline-none transition focus:border-blue-400"
        />
        <span className="mt-1 block text-[11px] text-gray-400">Pour vous repérer si vous installez plusieurs fournisseurs.</span>
      </label>

      {/* ── Nom du modèle ── */}
      <label className="block text-xs font-medium text-gray-600">
        Nom du modèle
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={modelDefaults?.modelPlaceholder ?? "gpt-5.5"}
          className={`mt-1 w-full rounded-md border px-2.5 py-2 text-sm outline-none transition focus:border-blue-400 ${errorFor("model") ? "border-red-300" : "border-gray-200"}`}
        />
        <span className="mt-1 block text-[11px] text-gray-400">1 à 128 caractères : lettres, chiffres, . _ - / :</span>
        {errorFor("model") && <span className="mt-1 block text-[11px] text-red-600">{errorFor("model")}</span>}
      </label>

      {/* ── URL de l'API ── */}
      <label className="block text-xs font-medium text-gray-600">
        URL de l'API
        <input
          value={endpoint}
          onChange={(e) => setEndpoint(e.target.value)}
          placeholder="https://api.example.com/v1/chat/completions"
          className={`mt-1 w-full rounded-md border px-2.5 py-2 text-sm outline-none transition focus:border-blue-400 ${errorFor("endpoint") ? "border-red-300" : "border-gray-200"}`}
        />
        <span className="mt-1 block text-[11px] text-gray-400">HTTPS obligatoire (http:// accepté uniquement pour un serveur local/privé auto-hébergé).</span>
        {errorFor("endpoint") && <span className="mt-1 block text-[11px] text-red-600">{errorFor("endpoint")}</span>}
      </label>

      {/* ── Clé API ── */}
      <label className="block text-xs font-medium text-gray-600">
        Clé API
        <div className="relative mt-1">
          <input
            type={showApiKey ? "text" : "password"}
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              setApiKeyTouched(true);
            }}
            placeholder={
              authType === "none"
                ? "aucune (authentification désactivée)"
                : editing?.hasApiKey
                  ? `${editing.apiKeyMasked ?? "••••••••"} — laisser vide pour conserver`
                  : "sk-xxxxxxxxxxxxxxxxxxxxxxxx"
            }
            disabled={authType === "none"}
            className={`w-full rounded-md border px-2.5 py-2 pr-9 text-sm outline-none transition focus:border-blue-400 disabled:bg-gray-50 disabled:text-gray-400 ${errorFor("api_key") ? "border-red-300" : "border-gray-200"}`}
          />
          <button
            type="button"
            onClick={() => setShowApiKey((v) => !v)}
            disabled={authType === "none"}
            aria-label={showApiKey ? "Masquer la clé" : "Afficher la clé"}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 disabled:opacity-30"
          >
            {showApiKey ? <EyeOff className="h-3.5 w-3.5" aria-hidden="true" /> : <Eye className="h-3.5 w-3.5" aria-hidden="true" />}
          </button>
        </div>
        <span className="mt-1 block text-[11px] text-gray-400">16 à 512 caractères : lettres, chiffres, - _ . ~ (aucun espace).</span>
        {errorFor("api_key") && <span className="mt-1 block text-[11px] text-red-600">{errorFor("api_key")}</span>}
      </label>

      {/* ── Type d'API / Authentification ── */}
      <div className="grid grid-cols-2 gap-3">
        <label className="block text-xs font-medium text-gray-600">
          Type d'API
          <select
            value={apiType}
            onChange={(e) => setApiType(e.target.value as LlmProviderInput["apiType"])}
            className="mt-1 w-full rounded-md border border-gray-200 bg-white px-2.5 py-2 text-sm outline-none transition focus:border-blue-400"
          >
            {API_TYPE_CATALOG.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </label>
        <label className="block text-xs font-medium text-gray-600">
          Authentification
          <select
            value={authType}
            onChange={(e) => setAuthType(e.target.value as LlmProviderInput["authType"])}
            className="mt-1 w-full rounded-md border border-gray-200 bg-white px-2.5 py-2 text-sm outline-none transition focus:border-blue-400"
          >
            {AUTH_TYPE_CATALOG.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </label>
      </div>
      <p className="-mt-2 text-[11px] text-gray-400">
        L'en-tête d'authentification (Authorization / x-api-key / Basic) est construit automatiquement — sa syntaxe n'est pas modifiable.
      </p>

      {/* ── En-têtes supplémentaires ── */}
      <div>
        <span className="block text-xs font-medium text-gray-600">En-têtes supplémentaires</span>
        <div className="mt-1 space-y-1.5">
          {headers.map((h) => (
            <div key={h.id} className="flex items-center gap-1.5">
              <input
                value={h.name}
                onChange={(e) => updateHeaderRow(h.id, { name: e.target.value })}
                placeholder="X-API-Version"
                className="w-1/2 rounded-md border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-blue-400"
              />
              <input
                value={h.value}
                onChange={(e) => updateHeaderRow(h.id, { value: e.target.value })}
                placeholder="2025-06-01"
                className="w-1/2 rounded-md border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-blue-400"
              />
              <button
                type="button"
                onClick={() => removeHeaderRow(h.id)}
                aria-label="Supprimer cet en-tête"
                className="shrink-0 rounded-md p-1.5 text-gray-400 hover:bg-gray-50 hover:text-red-600"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={addHeaderRow}
          className="mt-1.5 flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline"
        >
          <Plus className="h-3 w-3" aria-hidden="true" />
          Ajouter un en-tête
        </button>
        {errorFor("headers") && <span className="mt-1 block text-[11px] text-red-600">{errorFor("headers")}</span>}
      </div>

      {/* ── Paramètres réseau ── */}
      <div className="grid grid-cols-2 gap-3">
        <label className="block text-xs font-medium text-gray-600">
          Timeout (s)
          <input
            type="number"
            min={1}
            max={300}
            value={timeoutS}
            onChange={(e) => setTimeoutS(Number(e.target.value))}
            className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm outline-none transition focus:border-blue-400"
          />
        </label>
        <label className="block text-xs font-medium text-gray-600">
          Tentatives max.
          <input
            type="number"
            min={0}
            max={10}
            value={maxRetries}
            onChange={(e) => setMaxRetries(Number(e.target.value))}
            className="mt-1 w-full rounded-md border border-gray-200 px-2.5 py-2 text-sm outline-none transition focus:border-blue-400"
          />
        </label>
      </div>
      <div className="flex gap-4">
        <Toggle checked={http2} onChange={setHttp2} label="HTTP/2" />
        <Toggle checked={compression} onChange={setCompression} label="Compression" />
      </div>

      {fieldError?.field === "_global" && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{fieldError.message}</p>
      )}

      {testResult && (
        <div
          className={`flex items-start gap-2 rounded-lg px-3 py-2 text-xs ${
            testResult.status === "success" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
          }`}
        >
          {testResult.status === "success" ? (
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          ) : (
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          )}
          <span>{testResult.message}{testResult.attempts > 1 ? ` (${testResult.attempts} tentatives)` : ""}</span>
        </div>
      )}

      {/* ── Actions ── */}
      <div className="flex items-center justify-between gap-2 pt-1">
        <button
          type="button"
          onClick={handleTest}
          disabled={testing || saving}
          className="flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-40"
        >
          {testing && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          Tester la connexion
        </button>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md px-3 py-2 text-xs font-medium text-gray-500 transition hover:bg-gray-50 disabled:opacity-40"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || testing}
            className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-700 disabled:opacity-40"
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
            {editing ? "Enregistrer" : "Installer"}
          </button>
        </div>
      </div>
    </form>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-gray-600">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 shrink-0 rounded-full transition ${checked ? "bg-blue-600" : "bg-gray-200"}`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${checked ? "left-4" : "left-0.5"}`}
        />
      </button>
      {label}
    </label>
  );
}
