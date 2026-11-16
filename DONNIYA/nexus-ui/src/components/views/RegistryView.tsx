import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Brain, Package, RefreshCw, Search } from "lucide-react";
import type { Registry, RegistryNode } from "../../types";
import { fetchRegistry } from "../../lib/registryApi";
import SidePanel from "../SidePanel";
import RegistryNodeDetail from "../RegistryNodeDetail";

/** Cf. Nexus_Assistant/docs/registry_schema.md §2.2 : "brain" est la seule
 * phase hors pipeline nexus_compose, réservée aux composants cognitifs
 * Niveau 1 de Nexus Brain (D3). */
const BRAIN_PHASE = "brain";

const EMPTY_REGISTRY: Registry = { nodes: [], edges: [] };

/**
 * Vue "Registry" — l'explorateur minimal de la Mission 2 (D5.1, "Nexus
 * Studio" au sens Niveau 2). Consomme GET /registry/full sur le PONT
 * (pas Nexus_Assistant, cf. lib/registryApi.ts) : nœuds + arêtes
 * fusionnés de nexus_compose et Nexus Brain.
 *
 * Volontairement auto-suffisante (son propre fetch/loading/erreur, son
 * propre SidePanel) plutôt que raccordée à l'état partagé d'App.tsx : rien
 * d'autre dans l'appli n'a besoin de ces données, et ça garde une
 * frontière nette avec les 3 autres vues — même esprit que "pas de fusion
 * Niveau 1 / Niveau 3" appliqué ici à l'UI.
 */
export default function RegistryView() {
  const [registry, setRegistry] = useState<Registry>(EMPTY_REGISTRY);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [phaseFilter, setPhaseFilter] = useState("");
  const [capabilityFilter, setCapabilityFilter] = useState<string | null>(null);
  const [selected, setSelected] = useState<RegistryNode | null>(null);

  function load() {
    setLoading(true);
    setLoadError(null);
    fetchRegistry()
      .then((data) => setRegistry(data))
      .catch((err: unknown) => {
        console.error("Échec du chargement du registre :", err);
        setLoadError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { nodes, edges } = registry;

  const phases = useMemo(() => [...new Set(nodes.map((n) => n.phase))].sort(), [nodes]);
  const capabilities = useMemo(
    () => [...new Set(nodes.flatMap((n) => n.capabilities))].sort(),
    [nodes],
  );

  // Signal que le pont n'a pas pu joindre nexus_compose (D4 dégrade en
  // douceur plutôt que planter — cf. registry_aggregator.py) : si TOUS les
  // nœuds reçus sont phase="brain", nexus_compose n'a rien contribué.
  const composeUnreachable = nodes.length > 0 && nodes.every((n) => n.phase === BRAIN_PHASE);

  const visible = nodes.filter((n) => {
    if (phaseFilter && n.phase !== phaseFilter) return false;
    if (capabilityFilter && !n.capabilities.includes(capabilityFilter)) return false;
    const q = query.trim().toLowerCase();
    if (q) {
      const haystack = `${n.id} ${n.description} ${n.moduleName}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  const edgesForSelected = selected
    ? edges.filter((e) => e.source === selected.id || e.target === selected.id)
    : [];

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Registre — Nexus Studio</h2>
          <p className="mt-1 text-sm text-gray-500">
            Catalogue unifié : {nodes.length} nœud{nodes.length > 1 ? "s" : ""}
            {registry.edges.length > 0 || nodes.length > 0
              ? ` · ${edges.length} arête${edges.length > 1 ? "s" : ""}`
              : ""}{" "}
            — pipeline nexus_compose et cœur cognitif Nexus Brain.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-40"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
          Actualiser
        </button>
      </div>

      {loadError && (
        <div className="mt-4 flex items-start gap-2 rounded-card border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            Impossible de joindre le pont ({import.meta.env.VITE_BRIDGE_BASE_URL ?? "http://127.0.0.1:8420"}) : {loadError}
          </span>
        </div>
      )}

      {composeUnreachable && !loadError && (
        <div className="mt-4 flex items-start gap-2 rounded-card border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            nexus_compose est injoignable pour l'instant — seuls les {nodes.length} composants Nexus
            Brain sont affichés.
          </span>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400"
            aria-hidden="true"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Chercher un id, une description…"
            className="w-64 rounded-md border border-gray-200 py-1.5 pl-8 pr-2 text-sm text-gray-700 outline-none focus:border-blue-400"
          />
        </div>
        <select
          value={phaseFilter}
          onChange={(e) => setPhaseFilter(e.target.value)}
          className="rounded-md border border-gray-200 bg-white py-1.5 px-2 text-sm text-gray-700 outline-none focus:border-blue-400"
        >
          <option value="">Toutes les phases</option>
          {phases.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      {capabilities.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {capabilities.map((cap) => {
            const active = capabilityFilter === cap;
            return (
              <button
                key={cap}
                type="button"
                onClick={() => setCapabilityFilter(active ? null : cap)}
                className={`rounded-full border px-2.5 py-1 text-xs font-medium transition ${
                  active
                    ? "border-gray-900 bg-gray-900 text-white"
                    : "border-gray-200 text-gray-600 hover:bg-gray-50"
                }`}
              >
                {cap}
              </button>
            );
          })}
        </div>
      )}

      <div className="mt-4 max-h-[28rem] divide-y divide-gray-100 overflow-y-auto rounded-card border border-gray-200">
        {loading && nodes.length === 0 && (
          <p className="p-6 text-center text-sm text-gray-400">Chargement du registre…</p>
        )}
        {!loading && !loadError && visible.length === 0 && (
          <p className="p-6 text-center text-sm text-gray-400">Aucun nœud ne correspond à ces filtres.</p>
        )}
        {visible.map((n) => {
          const Icon = n.phase === BRAIN_PHASE ? Brain : Package;
          return (
            <button
              key={n.id}
              type="button"
              onClick={() => setSelected(n)}
              className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition hover:bg-gray-50"
            >
              <Icon className="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-mono text-xs font-semibold text-gray-900">{n.id}</span>
                  <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
                    {n.phase}
                  </span>
                </div>
                <p className="truncate text-xs text-gray-500">{n.moduleName}</p>
              </div>
            </button>
          );
        })}
      </div>

      {selected && (
        <SidePanel title={selected.id} onClose={() => setSelected(null)}>
          <RegistryNodeDetail node={selected} edges={edgesForSelected} />
        </SidePanel>
      )}
    </div>
  );
}
