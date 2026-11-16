import { Workflow, AlertCircle } from "lucide-react";
import { phaseStatus, phaseProgress } from "../types";
import type { PipelinePhase } from "../types";

interface PipelinePanelProps {
  phases: PipelinePhase[];
  onSelectPhase: (phaseId: string) => void;
}

const BAR_COLOR: Record<string, string> = {
  pending: "bg-gray-200",
  running: "bg-blue-500",
  done: "bg-green-500",
  failed: "bg-red-500",
};

const DOT_CLASS: Record<string, string> = {
  pending: "border-gray-300 bg-white",
  running: "border-blue-500 bg-blue-500 animate-pulse",
  done: "border-green-500 bg-green-500",
  failed: "border-red-500 bg-red-500",
};

function PhaseItem({
  phase,
  onSelect,
}: {
  phase: PipelinePhase;
  onSelect: () => void;
}) {
  const status = phaseStatus(phase);
  const pct = phaseProgress(phase);

  return (
    <button
      type="button"
      onClick={onSelect}
      className="group rounded-lg text-left transition hover:bg-gray-50"
    >
      <p className="mb-1.5 flex items-center gap-1 truncate text-xs font-medium text-gray-600">
        {phase.label}
        {status === "failed" && (
          <AlertCircle className="h-3 w-3 shrink-0 text-red-500" aria-hidden="true" />
        )}
      </p>
      <div className="flex items-center gap-1.5">
        <span
          className={`h-2 w-2 shrink-0 rounded-full border ${DOT_CLASS[status]}`}
          aria-hidden="true"
        />
        <div className="h-px flex-1 bg-gray-200">
          <div
            className={`h-px transition-all ${BAR_COLOR[status]}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </button>
  );
}

export default function PipelinePanel({ phases, onSelectPhase }: PipelinePanelProps) {
  const completed = phases.filter((p) => phaseStatus(p) === "done").length;
  const hasFailure = phases.some((p) => phaseStatus(p) === "failed");

  return (
    <section className="rounded-card border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <Workflow className="h-4 w-4 text-gray-500" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-gray-900">Pipeline</h2>
        </div>
        <span className={`text-xs ${hasFailure ? "font-medium text-red-600" : "text-gray-400"}`}>
          {completed} / {phases.length} phases
        </span>
      </div>

      <div className="grid grid-cols-4 gap-x-2 gap-y-2 p-2">
        {phases.map((phase) => (
          <PhaseItem
            key={phase.id}
            phase={phase}
            onSelect={() => onSelectPhase(phase.id)}
          />
        ))}
      </div>
    </section>
  );
}
