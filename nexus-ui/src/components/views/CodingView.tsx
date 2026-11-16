import { GitBranch, Loader2, CheckCircle2, XCircle, Check, RotateCcw } from "lucide-react";
import type { CodeBranch, BranchStatus, GeneratedFile } from "../../types";

/**
 * Vue "Coding" — génération parallèle par les agents (crewAI, OpenHands,
 * OpenManus-RL, cf. unified_system/bridge.py). Chaque branche produit des
 * fichiers ; chaque fichier attend une décision explicite avant fusion vers
 * PRODUCTION. Le bandeau de tête affiche toujours la dette de revue en cours
 * — le nombre de diffs en attente — pour éviter qu'elle s'accumule
 * silencieusement quand plusieurs agents tournent en même temps.
 */

const BRANCH_ICON: Record<BranchStatus, typeof Loader2> = {
  running: Loader2,
  done: CheckCircle2,
  failed: XCircle,
};

const BRANCH_ICON_CLASS: Record<BranchStatus, string> = {
  running: "text-blue-500 animate-spin",
  done: "text-green-500",
  failed: "text-red-500",
};

const STATUS_BADGE: Record<GeneratedFile["status"], string> = {
  pending: "bg-amber-100 text-amber-700",
  accepted: "bg-green-100 text-green-700",
  "needs-fix": "bg-red-100 text-red-700",
};

const STATUS_LABEL: Record<GeneratedFile["status"], string> = {
  pending: "En attente",
  accepted: "Accepté",
  "needs-fix": "À corriger",
};

interface CodingViewProps {
  branches: CodeBranch[];
  onAcceptFile: (branchId: string, fileId: string) => void;
  onRequestFix: (branchId: string, fileId: string) => void;
}

function FileRow({
  file,
  onAccept,
  onFix,
}: {
  file: GeneratedFile;
  onAccept: () => void;
  onFix: () => void;
}) {
  return (
    <div className="flex items-center gap-3 border-t border-gray-100 px-4 py-2.5 first:border-t-0">
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-xs text-gray-700">{file.path}</p>
        <p className="mt-0.5 truncate text-xs text-gray-400">{file.summary}</p>
      </div>
      <span className="shrink-0 text-xs tabular-nums text-green-600">+{file.linesAdded}</span>
      <span className="shrink-0 text-xs tabular-nums text-red-500">-{file.linesRemoved}</span>
      <span
        className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[file.status]}`}
      >
        {STATUS_LABEL[file.status]}
      </span>
      {file.status === "pending" && (
        <div className="flex shrink-0 gap-1">
          <button
            type="button"
            onClick={onAccept}
            aria-label="Accepter"
            className="rounded-md p-1.5 text-green-600 transition hover:bg-green-50"
          >
            <Check className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={onFix}
            aria-label="Demander une correction"
            className="rounded-md p-1.5 text-red-500 transition hover:bg-red-50"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}

export default function CodingView({
  branches,
  onAcceptFile,
  onRequestFix,
}: CodingViewProps) {
  const pendingCount = branches.reduce(
    (sum, b) => sum + b.files.filter((f) => f.status === "pending").length,
    0,
  );
  const activeCount = branches.filter((b) => b.status === "running").length;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-lg font-semibold text-gray-900">Génération de code</h2>
      <p className="mt-1 text-sm text-gray-500">
        Fichiers produits en parallèle par crewAI · OpenHands · OpenManus-RL.
      </p>

      <div
        className={`mt-4 flex items-center justify-between rounded-card border px-4 py-3 text-sm ${
          pendingCount > 0
            ? "border-amber-200 bg-amber-50 text-amber-800"
            : "border-green-200 bg-green-50 text-green-700"
        }`}
      >
        <span>
          <strong>{activeCount}</strong> branche{activeCount !== 1 ? "s" : ""} active
          {activeCount !== 1 ? "s" : ""}
        </span>
        <span>
          <strong>{pendingCount}</strong> diff{pendingCount !== 1 ? "s" : ""} en attente de
          revue
        </span>
      </div>

      <div className="mt-4 space-y-4">
        {branches.map((branch) => {
          const Icon = BRANCH_ICON[branch.status];
          return (
            <div key={branch.id} className="overflow-hidden rounded-card border border-gray-200">
              <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-4 py-2.5">
                <GitBranch className="h-4 w-4 text-gray-400" aria-hidden="true" />
                <span className="text-sm font-medium text-gray-900">{branch.label}</span>
                <span className="text-xs text-gray-400">· {branch.agent}</span>
                <Icon className={`ml-auto h-4 w-4 ${BRANCH_ICON_CLASS[branch.status]}`} aria-hidden="true" />
              </div>
              <div>
                {branch.files.map((file) => (
                  <FileRow
                    key={file.id}
                    file={file}
                    onAccept={() => onAcceptFile(branch.id, file.id)}
                    onFix={() => onRequestFix(branch.id, file.id)}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
