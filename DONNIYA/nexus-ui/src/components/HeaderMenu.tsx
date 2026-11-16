import { useEffect, useRef } from "react";
import { MessageSquarePlus, Plug, History } from "lucide-react";
import type { ConversationSummary } from "../types";

interface HeaderMenuProps {
  history: ConversationSummary[];
  onNewConversation: () => void;
  onSelectConversation: (conv: ConversationSummary) => void;
  onOpenApiDialog: () => void;
  onClose: () => void;
}

/**
 * Menu déroulant ouvert par le bouton "···" du Header.
 * Se ferme au clic externe, à l'Échap, ou après sélection d'une action.
 */
export default function HeaderMenu({
  history,
  onNewConversation,
  onSelectConversation,
  onOpenApiDialog,
  onClose,
}: HeaderMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      role="menu"
      className="absolute left-0 top-full z-30 mt-2 w-72 overflow-hidden rounded-card border border-gray-200 bg-white shadow-xl"
    >
      <button
        type="button"
        role="menuitem"
        onClick={() => {
          onNewConversation();
          onClose();
        }}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-sm font-medium text-gray-900 transition hover:bg-gray-50"
      >
        <MessageSquarePlus className="h-4 w-4 text-gray-400" aria-hidden="true" />
        Nouvelle discussion
      </button>

      <div className="border-t border-gray-100 px-4 py-2">
        <p className="flex items-center gap-1.5 text-xs font-medium text-gray-400">
          <History className="h-3.5 w-3.5" aria-hidden="true" />
          Historique
        </p>
      </div>
      <div className="max-h-56 overflow-y-auto">
        {history.map((conv) => (
          <button
            key={conv.id}
            type="button"
            role="menuitem"
            onClick={() => {
              onSelectConversation(conv);
              onClose();
            }}
            className="flex w-full flex-col items-start px-4 py-2 text-left transition hover:bg-gray-50"
          >
            <span className="truncate text-sm text-gray-700">{conv.title}</span>
            <span className="text-xs text-gray-400">{conv.date}</span>
          </button>
        ))}
      </div>

      <button
        type="button"
        role="menuitem"
        onClick={() => {
          onOpenApiDialog();
          onClose();
        }}
        className="flex w-full items-center gap-2.5 border-t border-gray-100 px-4 py-3 text-sm font-medium text-gray-900 transition hover:bg-gray-50"
      >
        <Plug className="h-4 w-4 text-gray-400" aria-hidden="true" />
        Connexion API
      </button>
    </div>
  );
}
