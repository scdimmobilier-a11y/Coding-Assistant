/**
 * lib/registryApi.ts
 * ────────────────────
 * Mission 2 (Meta Framework / Nexus Studio) — livrable D5.1.
 *
 * Contrairement à pipelineApi.ts / providersApi.ts / securityApi.ts (tous
 * Nexus_Assistant, port 8000 par défaut), ce client parle au PONT
 * (`nexus_core_leon_bridge`, port 8420 par défaut, cf. son README —
 * "uvicorn bridge.server:app --host 127.0.0.1 --port 8420") : c'est là
 * qu'habite `GET /registry/full`, le catalogue déjà fusionné
 * (nexus_compose + Nexus Brain, cf. bridge/registry_aggregator.py::D4).
 * D'où une variable d'env séparée, VITE_BRIDGE_BASE_URL, plutôt que de
 * réutiliser VITE_API_BASE_URL qui désigne une origine différente.
 */

import type { Registry, RegistryEdge, RegistryNode } from "../types";

const BRIDGE_BASE = import.meta.env.VITE_BRIDGE_BASE_URL ?? "http://127.0.0.1:8420";

/** Forme brute reçue sur le fil — snake_case, cf. types.ts. */
interface RawRegistryNode {
  id: string;
  module: string;
  module_name: string;
  function: string;
  description: string;
  tag: string;
  phase: string;
  type: string;
  io_in: string;
  io_out: string;
  ref: string;
  repo: string;
  virtual: boolean;
  subsection: string | null;
  capabilities: string[];
}

interface RawRegistry {
  nodes: RawRegistryNode[];
  edges: RegistryEdge[]; // déjà camelCase-compatible : source/target/label/type
}

async function jsonOrThrow<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${what} a échoué (${res.status}) : ${body || res.statusText}`);
  }
  return (await res.json()) as T;
}

function mapNode(raw: RawRegistryNode): RegistryNode {
  return {
    id: raw.id,
    module: raw.module,
    moduleName: raw.module_name,
    function: raw.function,
    description: raw.description,
    tag: raw.tag,
    phase: raw.phase,
    type: raw.type,
    ioIn: raw.io_in,
    ioOut: raw.io_out,
    ref: raw.ref,
    repo: raw.repo,
    virtual: raw.virtual,
    subsection: raw.subsection,
    capabilities: raw.capabilities,
  };
}

/**
 * GET /registry/full — le catalogue fusionné complet. Pas de paramètre
 * `capability` ici : ce client charge tout une fois, RegistryView filtre
 * côté client (183 nœuds tient largement en mémoire, pas besoin d'un
 * aller-retour réseau par filtre — cf. le composant pour le détail).
 */
export async function fetchRegistry(): Promise<Registry> {
  const res = await fetch(`${BRIDGE_BASE}/registry/full`);
  const raw = await jsonOrThrow<RawRegistry>(res, "GET /registry/full");
  return {
    nodes: raw.nodes.map(mapNode),
    edges: raw.edges,
  };
}
