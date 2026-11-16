import { useEffect } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import type { ApiConnectionResult } from "../types";

interface ApiStatusToastProps {
  result: ApiConnectionResult;
  onDismiss: () => void;
}

/**
 * Bulle de statut, auto-fermée après 5 s.
 * "success"/"error" générique — réutilisé pour plusieurs actions (retry
 * pipeline, sauvegarde, etc.), pas seulement la connexion API ; voir
 * ApiConnectionDialog.tsx pour le cas précis "fournisseur activé".
 */
export default function ApiStatusToast({ result, onDismiss }: ApiStatusToastProps) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 5000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  const success = result === "success";

  return (
    <div className="absolute left-1/2 top-4 z-40 -translate-x-1/2">
      <div
        role="status"
        className={`flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium shadow-lg ${
          success ? "bg-green-600 text-white" : "bg-red-600 text-white"
        }`}
      >
        {success ? (
          <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
        ) : (
          <XCircle className="h-4 w-4" aria-hidden="true" />
        )}
        {success ? "Fournisseur activé" : "Une erreur est survenue"}
      </div>
    </div>
  );
}
