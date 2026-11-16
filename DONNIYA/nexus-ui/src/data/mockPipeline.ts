import type {
  ChatMessage,
  PipelinePhase,
  DiagramNode,
  SecurityFinding,
  CodeBranch,
  ToolStatus,
  ConversationSummary,
} from "../types";

/**
 * Données de démonstration.
 * À remplacer par les données réelles renvoyées par l'API / le flux
 * temps réel de nexus_compose (voir README.md, section "Brancher le backend").
 */

export const mockMessages: ChatMessage[] = [
  {
    id: "m1",
    role: "user",
    text: "Prêt. Décrivez votre besoin en voix ou en texte.",
    time: "10:24",
  },
  {
    id: "m2",
    role: "system",
    text: "Bien reçu. Je suis prêt à vous aider. Que souhaitez-vous construire aujourd'hui ?",
    time: "10:24",
  },
];

/**
 * Les 8 groupes de phases de l'orchestrateur, avec un nœud par outil réel.
 * La phase "Audit SAST" contient volontairement un nœud en échec
 * (binaire bearer introuvable), pour donner un exemple réel de l'état
 * d'erreur — cohérent avec ToolNotFoundError dans nexus_vendor.
 */
export const mockPhases: PipelinePhase[] = [
  {
    id: "architecture",
    label: "Architecture",
    nodes: [
      { id: "n1", tag: "q2d.q2d_generate", status: "done" },
      { id: "n2", tag: "likec4.likec4_validate", status: "done" },
      { id: "n3", tag: "likec4.likec4_export_json", status: "done" },
      { id: "n4", tag: "c4if.c4if_export_diagram", status: "done" },
      { id: "n5", tag: "struct.structurizr_export", status: "done" },
      { id: "n6", tag: "likec4.likec4_codegen_react", status: "done" },
      { id: "n7", tag: "c4if.c4if_validate_architecture", status: "done" },
      { id: "n8", tag: "struct.structurizr_validate", status: "done" },
    ],
  },
  {
    id: "reseau",
    label: "Réseau",
    nodes: [
      { id: "n9", tag: "clab.clab_deploy", status: "done" },
      { id: "n10", tag: "clab.clab_inspect", status: "done" },
      { id: "n11", tag: "clab.clab_graph", status: "done" },
    ],
  },
  {
    id: "opa",
    label: "Politique OPA",
    nodes: [
      { id: "n12", tag: "opa.opa_check", status: "done" },
      { id: "n13", tag: "opa.opa_eval", status: "done" },
      { id: "n14", tag: "opa.opa_test", status: "done" },
    ],
  },
  {
    id: "analyse-reseau",
    label: "Analyse réseau",
    nodes: [
      { id: "n15", tag: "bf.bf_init_snapshot", status: "done" },
      { id: "n16", tag: "bf.bf_get_routes", status: "done" },
      { id: "n17", tag: "bf.bf_reachability", status: "done" },
    ],
  },
  {
    id: "threat-model",
    label: "Threat model",
    nodes: [
      { id: "n18", tag: "pytm.pytm_process", status: "done" },
      { id: "n19", tag: "tmdd.tmdd_compile", status: "done" },
      { id: "n20", tag: "neo4j.match_where_chemin_variable", status: "done" },
      { id: "n21", tag: "td.td_save_model", status: "done" },
      { id: "n22", tag: "tmdd.generate_agent_prompt", status: "done" },
    ],
  },
  {
    id: "sast",
    label: "Audit SAST",
    nodes: [
      { id: "n23", tag: "semgrep.semgrep_scan", status: "done" },
      {
        id: "n24",
        tag: "bearer.bearer_scan",
        status: "failed",
        error: "ToolNotFoundError : binaire 'bearer' introuvable sur ce runner.",
      },
      { id: "n25", tag: "codeql.codeql_database_analyze", status: "done" },
    ],
  },
  {
    id: "rapport",
    label: "Rapport",
    nodes: [
      { id: "n26", tag: "tmdd.tmdd_report_html", status: "pending" },
      { id: "n27", tag: "td.td_export", status: "pending" },
    ],
  },
  {
    id: "codegen",
    label: "Codegen",
    nodes: [
      { id: "n28", tag: "codegen.unified_system", status: "pending" },
      { id: "n29", tag: "codegen.tests_unified_system", status: "pending" },
      { id: "n30", tag: "codegen.docs_unified_system", status: "pending" },
    ],
  },
];

/* ── Diagramme C4 — 3 niveaux ─────────────────────────────────────────────── */

export const mockSystemLevel = {
  person: {
    id: "marchand",
    kind: "person",
    tone: "blue",
    title: "Marchand",
    meta: "[Person]",
  } satisfies DiagramNode,
  system: {
    id: "nexus-platform",
    kind: "container",
    tone: "purple",
    title: "Nexus Payment Platform",
    meta: "[System]",
    detail: "Vue simplifiée — zoomez sur \u00abConteneurs\u00bb pour le détail",
    tags: ["paiement", "production"],
  } satisfies DiagramNode,
};

export const mockContainerLevel = {
  person: {
    id: "marchand",
    kind: "person",
    tone: "blue",
    title: "Marchand",
    meta: "[Person]",
  } satisfies DiagramNode,

  hub: {
    id: "payment-service",
    kind: "container",
    tone: "purple",
    title: "Payment Service",
    meta: "[Container]",
    detail: "FastAPI · JWT · Neo4j",
    technology: ["FastAPI", "Python 3.12", "JWT", "Neo4j driver"],
    tags: ["microservice interne", "PCI-scope"],
    owner: "Équipe Paiements",
    linkedThreats: ["f2", "f3"],
    drillable: true,
  } satisfies DiagramNode,

  hubEdgeLabel: "Effectue un paiement\n(POST /payments)",

  downstream: [
    {
      id: "stripe",
      kind: "external",
      tone: "gray",
      dashed: true,
      title: "Stripe API",
      meta: "[Système Externe]",
      detail: "Paiement via HTTPS",
      technology: ["REST API externe"],
      tags: ["tiers", "PCI géré par Stripe"],
    } satisfies DiagramNode,
    {
      id: "neo4j",
      kind: "container",
      tone: "amber",
      title: "Neo4j",
      meta: "[Container]",
      detail: "Graphe de menaces (Bolt)",
      technology: ["Neo4j 6.2", "Bolt protocol"],
      tags: ["stockage", "threat graph"],
      linkedThreats: ["f3"],
    } satisfies DiagramNode,
    {
      id: "postgres",
      kind: "container",
      tone: "green",
      title: "PostgreSQL",
      meta: "[Container]",
      detail: "Données & Transactions (SQL)",
      technology: ["PostgreSQL 16"],
      tags: ["stockage", "transactionnel"],
    } satisfies DiagramNode,
  ] as DiagramNode[],

  secondary: {
    fromId: "neo4j",
    node: {
      id: "threat-model",
      kind: "container",
      tone: "red",
      dashed: true,
      title: "Threat Model STRIDE",
      meta: "[Container]",
      detail: "4 menaces · 2 critiques · python · tmdd",
      technology: ["pytm", "tmdd"],
      tags: ["sécurité"],
      linkedThreats: ["f2", "f3"],
    } satisfies DiagramNode,
  },
};

/** Vue "component" — drill-down du conteneur Payment Service. */
export const mockComponentLevel = {
  parentId: "payment-service",
  parentTitle: "Payment Service",
  chain: [
    {
      id: "auth-middleware",
      kind: "component",
      tone: "purple",
      title: "AuthMiddleware",
      meta: "[Component]",
      detail: "Vérifie le JWT entrant",
      technology: ["fastapi.middleware"],
      linkedThreats: ["f3"],
    } satisfies DiagramNode,
    {
      id: "payment-controller",
      kind: "component",
      tone: "purple",
      title: "PaymentController",
      meta: "[Component]",
      detail: "Route POST /payments",
      technology: ["fastapi.APIRouter"],
      linkedThreats: ["f2"],
    } satisfies DiagramNode,
    {
      id: "stripe-client",
      kind: "component",
      tone: "gray",
      dashed: true,
      title: "StripeClient",
      meta: "[Component]",
      detail: "Appelle l'API Stripe",
      technology: ["httpx"],
    } satisfies DiagramNode,
  ] as DiagramNode[],
  branch: {
    fromId: "payment-controller",
    node: {
      id: "threat-logger",
      kind: "component",
      tone: "red",
      dashed: true,
      title: "ThreatLogger",
      meta: "[Component]",
      detail: "Journalise vers Neo4j",
      technology: ["neo4j driver"],
    } satisfies DiagramNode,
  },
};

/* ── Vue Coding — génération parallèle ────────────────────────────────────── */

export const mockBranches: CodeBranch[] = [
  {
    id: "b1",
    label: "API",
    agent: "crewAI",
    status: "done",
    files: [
      {
        id: "f_types",
        path: "payment_service/models.py",
        summary: "Types Pydantic PaymentRequest / PaymentResponse",
        linesAdded: 42,
        linesRemoved: 0,
        status: "accepted",
      },
      {
        id: "f_controller",
        path: "payment_service/main.py",
        summary: "Endpoint POST /payments + dépendance verify_jwt",
        linesAdded: 68,
        linesRemoved: 3,
        status: "pending",
      },
      {
        id: "f_openapi",
        path: "payment_service/openapi.yaml",
        summary: "Schéma OpenAPI généré depuis les routes FastAPI",
        linesAdded: 120,
        linesRemoved: 0,
        status: "pending",
      },
    ],
  },
  {
    id: "b2",
    label: "Tests",
    agent: "OpenHands",
    status: "running",
    files: [
      {
        id: "f_unit",
        path: "tests/test_payments.py",
        summary: "Tests unitaires du endpoint /payments",
        linesAdded: 54,
        linesRemoved: 0,
        status: "accepted",
      },
      {
        id: "f_integration",
        path: "tests/test_integration_stripe.py",
        summary: "Test d'intégration avec un mock Stripe",
        linesAdded: 31,
        linesRemoved: 0,
        status: "needs-fix",
      },
    ],
  },
];

export const mockToolStatus: ToolStatus[] = [
  { id: "semgrep", label: "Semgrep", passed: true },
  { id: "bearer", label: "Bearer", passed: false },
  { id: "codeql", label: "CodeQL", passed: true },
];

/* ── Vue Sécurité ──────────────────────────────────────────────────────────── */

export const mockFindings: SecurityFinding[] = [
  {
    id: "f1",
    tool: "CodeQL",
    severity: "warning",
    title: "Secret potentiel en variable d'environnement",
    detail: "CWE-312 · main.py:14",
    relatedNodeId: "payment-service",
    reachableFromEntry: false,
  },
  {
    id: "f2",
    tool: "STRIDE",
    severity: "critical",
    title: "Injection possible sur /payments",
    detail: "Tampering · aucune validation d'entrée détectée",
    relatedNodeId: "payment-controller",
    reachableFromEntry: true,
  },
  {
    id: "f3",
    tool: "STRIDE",
    severity: "critical",
    title: "Contournement d'authentification possible",
    detail: "Spoofing · vérifier la validation du token JWT",
    relatedNodeId: "auth-middleware",
    reachableFromEntry: true,
  },
];

/* ── Historique des conversations (menu Header) ──────────────────────────── */

export const mockConversationHistory: ConversationSummary[] = [
  { id: "c1", title: "Payment Service — pipeline paiement", date: "Aujourd'hui, 10:24" },
  { id: "c2", title: "Refonte auth JWT + Neo4j", date: "Hier, 16:02" },
  { id: "c3", title: "Threat model — service de notifications", date: "27 juin" },
  { id: "c4", title: "Déploiement Containerlab — topologie DMZ", date: "22 juin" },
];
