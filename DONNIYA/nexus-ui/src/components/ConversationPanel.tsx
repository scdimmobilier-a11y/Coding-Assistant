import { useState } from "react";
import { MessageSquare, User, Asterisk, Send } from "lucide-react";
import type { ChatMessage } from "../types";

interface ConversationPanelProps {
  messages: ChatMessage[];
  onSend: (text: string) => void;
}

function Avatar({ role }: { role: ChatMessage["role"] }) {
  if (role === "user") {
    return (
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-purple-100">
        <User className="h-4 w-4 text-purple-600" aria-hidden="true" />
      </div>
    );
  }
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-blue-600">
      <Asterisk className="h-4 w-4 text-white" strokeWidth={2.5} aria-hidden="true" />
    </div>
  );
}

export default function ConversationPanel({ messages, onSend }: ConversationPanelProps) {
  const [draft, setDraft] = useState("");

  function submit() {
    const text = draft.trim();
    if (!text) return;
    onSend(text);
    setDraft("");
  }

  return (
    <section className="flex flex-1 flex-col rounded-card border border-gray-200 bg-white">
      <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3">
        <MessageSquare className="h-4 w-4 text-gray-500" aria-hidden="true" />
        <h2 className="text-sm font-semibold text-gray-900">Conversation</h2>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.map((m) => (
          <div key={m.id} className="flex items-start gap-2.5">
            <Avatar role={m.role} />
            <div className="min-w-0">
              <div className="mb-1 flex items-baseline gap-2">
                <span className="text-sm font-medium text-gray-900">
                  {m.role === "user" ? "Vous" : "Système"}
                </span>
                <span className="text-xs text-gray-400">{m.time}</span>
              </div>
              <div className="rounded-xl rounded-tl-sm bg-gray-50 px-3 py-2 text-sm text-gray-700">
                {m.text}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-gray-200 p-3">
        <div className="flex items-center gap-2 rounded-xl border border-gray-200 px-3 py-2">
          <div className="min-w-0 flex-1">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="Écrivez votre message..."
              className="w-full border-none bg-transparent text-sm text-gray-800 outline-none placeholder:text-gray-400"
            />
            <p className="mt-0.5 text-xs text-gray-400">
              Appuyer sur Entrée pour envoyer
            </p>
          </div>
          <button
            type="button"
            onClick={submit}
            aria-label="Envoyer le message"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-gray-400 transition hover:bg-gray-100 hover:text-blue-600"
          >
            <Send className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </section>
  );
}
