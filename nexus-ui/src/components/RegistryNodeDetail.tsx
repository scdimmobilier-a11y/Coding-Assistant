import { ArrowLeft, ArrowRight } from "lucide-react";
import type { RegistryEdge, RegistryNode } from "../types";

interface RegistryNodeDetailProps {
  node: RegistryNode;
  /** Arêtes touchant ce nœud (source ou target) — déjà filtrées par l'appelant. */
  edges: RegistryEdge[];
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium text-gray-400">{label}</p>
      <div className="mt-0.5 text-sm text-gray-700">{children}</div>
    </div>
  );
}

/** Panneau de détail affiché dans le SidePanel de RegistryView — un nœud
 * du registre unifié (Mission 2, D5.1), tous champs NodeMeta + les arêtes
 * qui le touchent, pour que "affiche nœuds/arêtes" (le document de
 * mission) reste vrai jusque dans le détail, pas juste la liste. */
export default function RegistryNodeDetail({ node, edges }: RegistryNodeDetailProps) {
  const outgoing = edges.filter((e) => e.source === node.id);
  const incoming = edges.filter((e) => e.target === node.id);

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-medium text-gray-400">{node.moduleName}</p>
        <h4 className="break-all font-mono text-sm font-semibold text-gray-900">{node.id}</h4>
        <p className="mt-1 text-sm text-gray-600">{node.description}</p>
      </div>

      <Field label="Fonction">
        <code className="break-all rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">
          {node.function}
        </code>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Phase">{node.phase}</Field>
        <Field label="Type">{node.type}</Field>
      </div>

      <Field label="Entrée → Sortie">
        <p className="text-xs text-gray-600">{node.ioIn}</p>
        <p className="my-1 text-xs text-gray-300">↓</p>
        <p className="text-xs text-gray-600">{node.ioOut}</p>
      </Field>

      <Field label="Source">
        <p className="break-all text-xs text-gray-600">{node.ref}</p>
        {node.repo && <p className="mt-0.5 break-all text-xs text-gray-400">{node.repo}</p>}
      </Field>

      {node.capabilities.length > 0 && (
        <Field label="Capacités">
          <div className="flex flex-wrap gap-1.5">
            {node.capabilities.map((c) => (
              <span
                key={c}
                className="rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-600"
              >
                {c}
              </span>
            ))}
          </div>
        </Field>
      )}

      {(outgoing.length > 0 || incoming.length > 0) && (
        <Field label={`Arêtes (${outgoing.length + incoming.length})`}>
          <ul className="space-y-1.5">
            {outgoing.map((e, i) => (
              <li
                key={`out-${i}`}
                className="flex items-center gap-1.5 rounded-lg bg-gray-50 px-2 py-1.5 text-xs text-gray-600"
              >
                <ArrowRight className="h-3 w-3 shrink-0 text-gray-400" aria-hidden="true" />
                <span className="truncate font-mono">{e.target}</span>
                <span className="ml-auto shrink-0 text-gray-400">{e.type}</span>
              </li>
            ))}
            {incoming.map((e, i) => (
              <li
                key={`in-${i}`}
                className="flex items-center gap-1.5 rounded-lg bg-gray-50 px-2 py-1.5 text-xs text-gray-600"
              >
                <ArrowLeft className="h-3 w-3 shrink-0 text-gray-400" aria-hidden="true" />
                <span className="truncate font-mono">{e.source}</span>
                <span className="ml-auto shrink-0 text-gray-400">{e.type}</span>
              </li>
            ))}
          </ul>
        </Field>
      )}

      {node.virtual && (
        <p className="rounded-lg bg-gray-50 px-2.5 py-1.5 text-xs text-gray-400">
          Nœud virtuel — symbolique, n'exécute rien.
        </p>
      )}
    </div>
  );
}
