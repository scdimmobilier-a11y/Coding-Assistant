import { useState } from "react";
import {
  ShieldAlert,
  ShieldQuestion,
  ShieldCheck,
  Wrench,
  EyeOff,
  Route,
} from "lucide-react";
import type { SecurityFinding, FindingSeverity } from "../../types";

/**
 * Vue "Security" — résultats consolidés Semgrep · Bearer · CodeQL · STRIDE.
 *
 * Le badge "Atteignable depuis Marchand" est calculé côté backend par une
 * requête sur le graphe de menaces Neo4j (voir native/neo4j/python/neo4j —
 * driver vendorisé — et le pattern Cypher `MATCH p=(start)-[*1..N]->(end)`
 * documenté dans nexus_vendor). C'est un signal que ni Snyk ni GitHub
 * Advanced Security ne peuvent calculer nativement : eux voient le code,
 * Nexus voit aussi le graphe d'architecture qui en découle.
 */

const SEVERITY_STYLE: Record<
  FindingSeverity,
  { box: string; icon: typeof ShieldAlert; iconClass: string; label: string; chip: string }
> = {
  critical: {
    box: "border-red-200 bg-red-50",
    icon: ShieldAlert,
    iconClass: "text-red-600",
    label: "Critique",
    chip: "bg-red-100 text-red-700",
  },
  warning: {
    box: "border-amber-200 bg-amber-50",
    icon: ShieldQuestion,
    iconClass: "text-amber-600",
    label: "Avertissement",
    chip: "bg-amber-100 text-amber-700",
  },
  info: {
    box: "border-gray-200 bg-gray-50",
    icon: ShieldCheck,
    iconClass: "text-gray-500",
    label: "Info",
    chip: "bg-gray-100 text-gray-600",
  },
};

interface SecurityViewProps {
  findings: SecurityFinding[];
  onIgnore: (id: string, reason: string, expiresOn: string) => void;
  onUnignore: (id: string) => void;
}

function IgnoreForm({
  onConfirm,
  onCancel,
}: {
  onConfirm: (reason: string, expiresOn: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const defaultExpiry = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
  const [expiresOn, setExpiresOn] = useState(defaultExpiry);

  return (
    <div className="mt-2 space-y-2 rounded-lg border border-gray-200 bg-white p-3">
      <label className="block text-xs font-medium text-gray-600">
        Raison (obligatoire)
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Ex. faux positif, non exploitable dans ce contexte..."
          className="mt-1 w-full rounded-md border border-gray-200 px-2 py-1.5 text-sm outline-none focus:border-blue-400"
        />
      </label>
      <label className="block text-xs font-medium text-gray-600">
        Expire le
        <input
          type="date"
          value={expiresOn}
          onChange={(e) => setExpiresOn(e.target.value)}
          className="mt-1 w-full rounded-md border border-gray-200 px-2 py-1.5 text-sm outline-none focus:border-blue-400"
        />
      </label>
      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-3 py-1.5 text-xs font-medium text-gray-500 hover:bg-gray-50"
        >
          Annuler
        </button>
        <button
          type="button"
          disabled={!reason.trim()}
          onClick={() => onConfirm(reason.trim(), expiresOn)}
          className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white transition disabled:opacity-40"
        >
          Confirmer l'ignorance
        </button>
      </div>
    </div>
  );
}

export default function SecurityView({ findings, onIgnore, onUnignore }: SecurityViewProps) {
  const [activeFilter, setActiveFilter] = useState<FindingSeverity | null>(null);
  const [ignoringId, setIgnoringId] = useState<string | null>(null);

  const counts: Record<FindingSeverity, number> = {
    critical: findings.filter((f) => f.severity === "critical").length,
    warning: findings.filter((f) => f.severity === "warning").length,
    info: findings.filter((f) => f.severity === "info").length,
  };

  const visible = activeFilter
    ? findings.filter((f) => f.severity === activeFilter)
    : findings;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-lg font-semibold text-gray-900">Rapport d'audit</h2>
      <p className="mt-1 text-sm text-gray-500">
        Résultats consolidés Semgrep · Bearer · CodeQL · Threat Model STRIDE.
      </p>

      <div className="mt-4 flex gap-2">
        {(Object.keys(counts) as FindingSeverity[]).map((sev) => {
          const style = SEVERITY_STYLE[sev];
          const isActive = activeFilter === sev;
          return (
            <button
              key={sev}
              type="button"
              onClick={() => setActiveFilter(isActive ? null : sev)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                isActive
                  ? "border-gray-900 bg-gray-900 text-white"
                  : `border-transparent ${style.chip}`
              }`}
            >
              {style.label}
              <span className="tabular-nums">{counts[sev]}</span>
            </button>
          );
        })}
        {activeFilter && (
          <button
            type="button"
            onClick={() => setActiveFilter(null)}
            className="text-xs text-gray-400 underline-offset-2 hover:underline"
          >
            Effacer le filtre
          </button>
        )}
      </div>

      <div className="mt-4 space-y-3">
        {visible.map((f) => {
          const style = SEVERITY_STYLE[f.severity];
          const Icon = style.icon;
          return (
            <div key={f.id} className={`rounded-card border p-4 ${style.box}`}>
              <div className="flex items-start gap-3">
                <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${style.iconClass}`} aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-900">{f.title}</span>
                    <span className="text-xs text-gray-400">· {f.tool}</span>
                  </div>
                  <p className="mt-0.5 text-sm text-gray-500">{f.detail}</p>

                  {f.reachableFromEntry !== undefined && (
                    <div
                      className={`mt-2 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
                        f.reachableFromEntry
                          ? "bg-red-100 text-red-700"
                          : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      <Route className="h-3 w-3" aria-hidden="true" />
                      {f.reachableFromEntry
                        ? "Atteignable depuis Marchand"
                        : "Non atteignable depuis l'entrée"}
                    </div>
                  )}

                  {f.ignored ? (
                    <div className="mt-2 flex items-center justify-between rounded-lg bg-white/60 px-2.5 py-1.5 text-xs text-gray-500">
                      <span>
                        Ignoré : {f.ignored.reason} · expire le {f.ignored.expiresOn}
                      </span>
                      <button
                        type="button"
                        onClick={() => onUnignore(f.id)}
                        className="font-medium text-gray-700 underline-offset-2 hover:underline"
                      >
                        Réactiver
                      </button>
                    </div>
                  ) : ignoringId === f.id ? (
                    <IgnoreForm
                      onCancel={() => setIgnoringId(null)}
                      onConfirm={(reason, expiresOn) => {
                        onIgnore(f.id, reason, expiresOn);
                        setIgnoringId(null);
                      }}
                    />
                  ) : (
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        className="flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50"
                      >
                        <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
                        Corriger
                      </button>
                      <button
                        type="button"
                        onClick={() => setIgnoringId(f.id)}
                        className="flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50"
                      >
                        <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
                        Ignorer
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        {visible.length === 0 && (
          <p className="py-8 text-center text-sm text-gray-400">
            Aucun finding pour cette sévérité.
          </p>
        )}
      </div>
    </div>
  );
}
