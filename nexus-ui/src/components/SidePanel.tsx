import { useEffect } from "react";
import { X } from "lucide-react";

interface SidePanelProps {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}

/**
 * Panneau latéral partagé, utilisé par :
 *   - PhaseDetailPanel (clic sur une phase du pipeline)
 *   - NodeDetailPanel (clic sur un nœud du diagramme C4)
 *
 * Positionné en overlay à l'intérieur du conteneur applicatif principal
 * (voir App.tsx, qui doit être `position: relative`).
 */
export default function SidePanel({ title, onClose, children }: SidePanelProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="absolute inset-0 z-20 flex justify-end">
      <button
        aria-label="Fermer le panneau"
        onClick={onClose}
        className="flex-1 bg-gray-900/20 backdrop-blur-[1px]"
      />
      <div className="flex h-full w-full max-w-sm flex-col border-l border-gray-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="rounded-lg p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
