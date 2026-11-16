/**
 * Étape 2 du prompt de fusion : mapping centralisé id -> libellé FR pour
 * les 10 phases réelles du backend (voir Nexus_Assistant/api/state.py pour
 * la correction de l'hypothèse "8 phases" — il y en a en réalité 10 :
 * elicit, arch, net, policy, threat, graph, codegen, audit, report,
 * deploy). Un seul fichier, pas de chaînes dupliquées ailleurs dans le
 * frontend.
 */

const PHASE_LABELS_FR: Record<string, string> = {
  elicit: "Élicitation des besoins",
  arch: "Architecture",
  net: "Réseau",
  policy: "Politiques",
  threat: "Modélisation des menaces",
  graph: "Graphe de menaces",
  codegen: "Génération de code",
  audit: "Audit sécurité",
  report: "Rapport",
  deploy: "Déploiement",
};

/** Retombe sur l'id brut si jamais le backend expose une phase pas encore
 * répertoriée ici — plus sûr qu'un libellé manquant qui casserait
 * l'affichage. */
export function phaseLabel(phaseId: string): string {
  return PHASE_LABELS_FR[phaseId] ?? phaseId;
}
