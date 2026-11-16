import { ArrowRight, ShieldAlert } from "lucide-react";
import type { DiagramNode, SecurityFinding } from "../types";

interface NodeDetailPanelProps {
  node: DiagramNode;
  linkedFindings: SecurityFinding[];
  onDrillDown?: () => void;
}

export default function NodeDetailPanel({
  node,
  linkedFindings,
  onDrillDown,
}: NodeDetailPanelProps) {
  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-medium text-gray-400">{node.meta}</p>
        <h4 className="text-base font-semibold text-gray-900">{node.title}</h4>
        {node.detail && <p className="mt-1 text-sm text-gray-500">{node.detail}</p>}
      </div>

      {node.owner && (
        <div>
          <p className="text-xs font-medium text-gray-400">Responsable</p>
          <p className="text-sm text-gray-700">{node.owner}</p>
        </div>
      )}

      {node.technology && node.technology.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-gray-400">Technologie</p>
          <div className="flex flex-wrap gap-1.5">
            {node.technology.map((t) => (
              <span
                key={t}
                className="rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-600"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {node.tags && node.tags.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-gray-400">Tags</p>
          <div className="flex flex-wrap gap-1.5">
            {node.tags.map((t) => (
              <span
                key={t}
                className="rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-600"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {linkedFindings.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-gray-400">Menaces liées</p>
          <ul className="space-y-1.5">
            {linkedFindings.map((f) => (
              <li
                key={f.id}
                className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 px-2.5 py-2 text-xs text-red-700"
              >
                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {f.title}
              </li>
            ))}
          </ul>
        </div>
      )}

      {node.drillable && onDrillDown && (
        <button
          type="button"
          onClick={onDrillDown}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
        >
          Voir les composants
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
