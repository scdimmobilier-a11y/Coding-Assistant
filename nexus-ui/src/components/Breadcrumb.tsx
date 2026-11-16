import { ChevronRight } from "lucide-react";
import type { C4Level } from "../types";

interface BreadcrumbProps {
  level: C4Level;
  /** Nom du conteneur exploré, uniquement pertinent au niveau "component". */
  componentParentTitle?: string;
  onNavigate: (level: C4Level) => void;
}

const LABEL: Record<C4Level, string> = {
  system: "Système",
  container: "Conteneurs",
  component: "Composant",
};

export default function Breadcrumb({
  level,
  componentParentTitle,
  onNavigate,
}: BreadcrumbProps) {
  const crumbs: { level: C4Level; label: string }[] = [
    { level: "system", label: LABEL.system },
    { level: "container", label: LABEL.container },
  ];
  if (level === "component") {
    crumbs.push({ level: "component", label: componentParentTitle ?? LABEL.component });
  }

  return (
    <nav aria-label="Niveau C4" className="flex items-center gap-1.5 text-sm">
      {crumbs.map((c, i) => {
        const isLast = i === crumbs.length - 1;
        return (
          <span key={c.level} className="flex items-center gap-1.5">
            {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-gray-300" aria-hidden="true" />}
            <button
              type="button"
              disabled={isLast}
              onClick={() => onNavigate(c.level)}
              aria-current={isLast ? "page" : undefined}
              className={
                isLast
                  ? "font-semibold text-gray-900"
                  : "text-gray-400 transition hover:text-gray-600"
              }
            >
              {c.label}
            </button>
          </span>
        );
      })}
    </nav>
  );
}
