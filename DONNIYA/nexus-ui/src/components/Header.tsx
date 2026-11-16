import { useState } from "react";
import { Asterisk, MoreHorizontal } from "lucide-react";
import HeaderMenu from "./HeaderMenu";
import type { ConversationSummary } from "../types";

interface HeaderProps {
  status: string;
  userInitials: string;
  history: ConversationSummary[];
  onNewConversation: () => void;
  onSelectConversation: (conv: ConversationSummary) => void;
  onOpenApiDialog: () => void;
}

export default function Header({
  status,
  userInitials,
  history,
  onNewConversation,
  onSelectConversation,
  onOpenApiDialog,
}: HeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
      <div className="flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600">
          <Asterisk className="h-5 w-5 text-white" strokeWidth={2.5} aria-hidden="true" />
        </div>
        <span className="text-lg font-semibold text-gray-900">Nexus Assistant</span>

        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Menu"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className="ml-1 rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
          </button>
          {menuOpen && (
            <HeaderMenu
              history={history}
              onNewConversation={onNewConversation}
              onSelectConversation={onSelectConversation}
              onOpenApiDialog={onOpenApiDialog}
              onClose={() => setMenuOpen(false)}
            />
          )}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <span>{status}</span>
          <span
            className="h-2 w-2 rounded-full bg-green-500"
            role="status"
            aria-label={status}
          />
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-purple-100 text-sm font-semibold text-purple-700">
          {userInitials}
        </div>
      </div>
    </header>
  );
}
