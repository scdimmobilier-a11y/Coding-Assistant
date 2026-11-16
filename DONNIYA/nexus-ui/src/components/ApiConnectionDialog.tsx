import { useEffect, useState } from "react";
import { Plug, Loader2, X, Plus, Pencil, Trash2, CheckCircle2 } from "lucide-react";
import ApiProviderForm from "./ApiProviderForm";
import {
  listProviders,
  installProvider,
  updateProvider,
  deleteProvider,
  activateProvider,
} from "../lib/providersApi";
import type { ApiConnectionResult, LlmProvider, LlmProviderInput } from "../types";
import { PROVIDER_CATALOG } from "../types";

interface ApiConnectionDialogProps {
  onCancel: () => void;
  onResult: (result: ApiConnectionResult) => void;
}

type ViewMode = { mode: "list" } | { mode: "add" } | { mode: "edit"; provider: LlmProvider };

function providerLabel(value: string): string {
  return PROVIDER_CATALOG.find((p) => p.value === value)?.label ?? value;
}

/**
 * Pop-up "Connexion API" ouvert depuis le menu "···" du Header.
 *
 * Dashboard d'installation des fournisseurs LLM (voir api/providers.py) :
 * liste les fournisseurs déjà installés, permet d'en installer un nouveau,
 * d'en modifier ou d'en supprimer un, et d'activer celui que le système
 * doit effectivement utiliser (nexus_compose/llm_config.py lit ce choix —
 * plus aucun LLM unique codé en dur, voir sa docstring).
 *
 * `onResult` — conservé pour ne rien changer à App.tsx — n'est déclenché
 * qu'au moment d'ACTIVER un fournisseur (l'équivalent, dans ce dashboard,
 * de l'ancien "Connecter" à une seule URL) ; le reste du retour (tests,
 * enregistrement, suppression) reste affiché directement dans ce pop-up,
 * plus riche qu'un simple toast générique.
 */
export default function ApiConnectionDialog({ onCancel, onResult }: ApiConnectionDialogProps) {
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [view, setView] = useState<ViewMode>({ mode: "list" });
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    refresh();
  }, []);

  function refresh() {
    setLoading(true);
    setLoadError(false);
    listProviders()
      .then(setProviders)
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  }

  async function handleSave(input: LlmProviderInput, apiKeyTouched: boolean) {
    if (view.mode === "edit") {
      const patch: Partial<LlmProviderInput> = { ...input };
      if (!apiKeyTouched) delete patch.apiKey; // conserve la clé enregistrée côté serveur
      await updateProvider(view.provider.id, patch);
    } else {
      await installProvider(input);
    }
    setView({ mode: "list" });
    refresh();
  }

  async function handleActivate(id: string) {
    setPendingActionId(id);
    try {
      await activateProvider(id);
      refresh();
      onResult("success");
    } catch {
      onResult("error");
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleDelete(id: string) {
    setPendingActionId(id);
    try {
      await deleteProvider(id);
      setConfirmDeleteId(null);
      refresh();
    } finally {
      setPendingActionId(null);
    }
  }

  const busy = pendingActionId !== null;

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center">
      <button
        type="button"
        aria-label="Fermer"
        onClick={onCancel}
        className="absolute inset-0 bg-gray-900/30 backdrop-blur-[1px]"
      />
      <div className="relative flex max-h-[85vh] w-full max-w-md flex-col rounded-card border border-gray-200 bg-white shadow-xl">
        <div className="flex items-center gap-2.5 border-b border-gray-200 px-5 py-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50">
            <Plug className="h-4 w-4 text-blue-600" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-gray-900">Connexion API</h3>
            <p className="text-xs text-gray-400">
              {view.mode === "list" ? "Fournisseurs LLM installés" : view.mode === "edit" ? `Modifier « ${view.provider.label} »` : "Installer un fournisseur"}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Fermer"
            className="shrink-0 rounded-lg p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {view.mode !== "list" ? (
            <ApiProviderForm
              editing={view.mode === "edit" ? view.provider : undefined}
              onCancel={() => setView({ mode: "list" })}
              onSave={handleSave}
            />
          ) : loading ? (
            <div className="flex items-center justify-center py-10 text-gray-400">
              <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
            </div>
          ) : loadError ? (
            <p className="py-8 text-center text-sm text-gray-400">
              Impossible de joindre le backend Nexus. Vérifiez qu'il est bien démarré.
            </p>
          ) : (
            <div className="space-y-2">
              {providers.length === 0 && (
                <p className="py-6 text-center text-sm text-gray-400">
                  Aucun fournisseur installé — le système utilise les variables d'environnement par défaut.
                </p>
              )}
              {providers.map((p) => (
                <div key={p.id} className={`rounded-card border p-3 ${p.isActive ? "border-blue-200 bg-blue-50/40" : "border-gray-200"}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-semibold text-gray-900">{p.label}</span>
                        {p.isActive && (
                          <span className="flex shrink-0 items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                            <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                            Actif
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 truncate text-xs text-gray-500">
                        {providerLabel(p.provider)} · {p.model}
                      </p>
                      <p className="mt-0.5 truncate text-[11px] text-gray-400">{p.endpoint}</p>
                    </div>
                  </div>

                  {confirmDeleteId === p.id ? (
                    <div className="mt-2 flex items-center justify-between rounded-lg bg-white px-2.5 py-1.5 text-xs">
                      <span className="text-gray-600">Supprimer « {p.label} » ?</span>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="rounded-md px-2 py-1 font-medium text-gray-500 hover:bg-gray-50"
                        >
                          Annuler
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => handleDelete(p.id)}
                          className="rounded-md bg-red-600 px-2 py-1 font-medium text-white transition hover:bg-red-700 disabled:opacity-40"
                        >
                          Confirmer
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-2 flex gap-1.5">
                      {!p.isActive && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => handleActivate(p.id)}
                          className="flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-40"
                        >
                          {pendingActionId === p.id ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : <CheckCircle2 className="h-3 w-3" aria-hidden="true" />}
                          Activer
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setView({ mode: "edit", provider: p })}
                        className="flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50"
                      >
                        <Pencil className="h-3 w-3" aria-hidden="true" />
                        Modifier
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(p.id)}
                        className="flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 hover:text-red-600"
                      >
                        <Trash2 className="h-3 w-3" aria-hidden="true" />
                        Supprimer
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {view.mode === "list" && !loading && !loadError && (
          <div className="flex justify-end gap-2 border-t border-gray-200 px-5 py-3">
            <button
              type="button"
              onClick={() => setView({ mode: "add" })}
              className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-700"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              Ajouter un fournisseur
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
