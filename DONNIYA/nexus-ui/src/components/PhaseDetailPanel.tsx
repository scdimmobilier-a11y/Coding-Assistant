import { CheckCircle2, XCircle, Loader2, Circle, RotateCw } from "lucide-react";
import type { PipelinePhase, NodeRunStatus } from "../types";

const STATUS_ICON: Record<NodeRunStatus, typeof Circle> = {
  pending: Circle,
  running: Loader2,
  done: CheckCircle2,
  failed: XCircle,
};

const STATUS_CLASS: Record<NodeRunStatus, string> = {
  pending: "text-gray-300",
  running: "text-blue-500 animate-spin",
  done: "text-green-500",
  failed: "text-red-500",
};

interface PhaseDetailPanelProps {
  phase: PipelinePhase;
  onRetryNode: (nodeId: string) => void;
  onRetryPhase: () => void;
}

export default function PhaseDetailPanel({
  phase,
  onRetryNode,
  onRetryPhase,
}: PhaseDetailPanelProps) {
  const hasFailed = phase.nodes.some((n) => n.status === "failed");

  return (
    <div className="space-y-3">
      {hasFailed && (
        <button
          type="button"
          onClick={onRetryPhase}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-red-700"
        >
          <RotateCw className="h-4 w-4" aria-hidden="true" />
          Relancer la phase "{phase.label}"
        </button>
      )}

      <ul className="divide-y divide-gray-100">
        {phase.nodes.map((node) => {
          const Icon = STATUS_ICON[node.status];
          return (
            <li key={node.id} className="flex items-start gap-2.5 py-2.5">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${STATUS_CLASS[node.status]}`} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-xs text-gray-700">{node.tag}</p>
                {node.error && (
                  <p className="mt-1 text-xs text-red-600">{node.error}</p>
                )}
              </div>
              {node.status === "failed" && (
                <button
                  type="button"
                  onClick={() => onRetryNode(node.id)}
                  className="shrink-0 rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 transition hover:bg-gray-50"
                >
                  Relancer
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
