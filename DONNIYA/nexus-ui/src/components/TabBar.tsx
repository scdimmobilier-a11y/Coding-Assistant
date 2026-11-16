import { Network, Code2, ShieldCheck, Boxes } from "lucide-react";
import type { TabId } from "../types";

const TABS: { id: TabId; label: string; icon: typeof Network }[] = [
  { id: "network", label: "Network", icon: Network },
  { id: "coding", label: "Coding", icon: Code2 },
  { id: "security", label: "Security", icon: ShieldCheck },
  { id: "registry", label: "Registry", icon: Boxes },
];

interface TabBarProps {
  active: TabId;
  onChange: (tab: TabId) => void;
  /** Compteurs optionnels affichés en badge (dette de revue, findings critiques...). */
  badges?: Partial<Record<TabId, number>>;
}

export default function TabBar({ active, onChange, badges = {} }: TabBarProps) {
  return (
    <div
      role="tablist"
      aria-label="Vues du projet"
      className="flex gap-2 border-b border-gray-200 bg-white px-4 pt-3"
    >
      {TABS.map(({ id, label, icon: Icon }) => {
        const isActive = id === active;
        const badge = badges[id];
        return (
          <button
            key={id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(id)}
            className={`flex items-center gap-2 rounded-t-lg border-b-2 px-4 py-2.5 text-sm font-medium transition ${
              isActive
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            {label}
            {!!badge && (
              <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
                {badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
