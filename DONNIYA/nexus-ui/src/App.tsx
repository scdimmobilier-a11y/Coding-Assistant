import { useEffect, useState } from "react";
import Header from "./components/Header";
import ConversationPanel from "./components/ConversationPanel";
import PipelinePanel from "./components/PipelinePanel";
import TabBar from "./components/TabBar";
import SidePanel from "./components/SidePanel";
import PhaseDetailPanel from "./components/PhaseDetailPanel";
import NodeDetailPanel from "./components/NodeDetailPanel";
import ApiConnectionDialog from "./components/ApiConnectionDialog";
import ApiStatusToast from "./components/ApiStatusToast";
import NetworkView from "./components/views/NetworkView";
import CodingView from "./components/views/CodingView";
import SecurityView from "./components/views/SecurityView";
import RegistryView from "./components/views/RegistryView";
import {
  mockMessages,
  mockToolStatus,
  mockContainerLevel,
  mockComponentLevel,
  mockSystemLevel,
  mockConversationHistory,
} from "./data/mockPipeline";
import type {
  ChatMessage,
  TabId,
  PipelinePhase,
  C4Level,
  DiagramNode,
  SecurityFinding,
  CodeBranch,
  ConversationSummary,
  ApiConnectionResult,
  NodeRunStatus,
} from "./types";
import {
  fetchPhases,
  runPipeline,
  retryNode as apiRetryNode,
  retryPhase as apiRetryPhase,
  subscribeToPipelineEvents,
  fetchFindings,
  ignoreFinding as apiIgnoreFinding,
  unignoreFinding as apiUnignoreFinding,
  fetchBranches,
  acceptFile as apiAcceptFile,
  requestFileFix as apiRequestFileFix,
  createConversation,
  fetchConversation,
} from "./lib/pipelineApi";
import { phaseLabel } from "./lib/phaseLabels";

/** Retrouve les métadonnées complètes d'un nœud à partir de son id, quel que soit le niveau C4. */
function findNodeById(id: string): DiagramNode | undefined {
  const all: DiagramNode[] = [
    mockSystemLevel.person,
    mockSystemLevel.system,
    mockContainerLevel.person,
    mockContainerLevel.hub,
    ...mockContainerLevel.downstream,
    mockContainerLevel.secondary.node,
    ...mockComponentLevel.chain,
    mockComponentLevel.branch.node,
  ];
  return all.find((n) => n.id === id);
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>(mockMessages);

  // Étape 2 du prompt de fusion : plus de mockPhases/mockFindings/
  // mockBranches en état initial — chargés depuis le backend au montage
  // (voir le useEffect ci-dessous). Vide par défaut plutôt que mock, pour
  // ne jamais afficher de données mock comme si elles étaient réelles.
  const [phases, setPhases] = useState<PipelinePhase[]>([]);
  const [findings, setFindings] = useState<SecurityFinding[]>([]);
  const [branches, setBranches] = useState<CodeBranch[]>([]);

  const [activeTab, setActiveTab] = useState<TabId>("network");

  // Pipeline : phase actuellement ouverte dans le panneau latéral.
  const [openPhaseId, setOpenPhaseId] = useState<string | null>(null);

  // Network : niveau C4 courant + nœud sélectionné (panneau latéral).
  // Hors périmètre de la fusion (aucun endpoint /api/diagram spécifié dans
  // le prompt) — reste alimenté par les données mock, volontairement.
  const [c4Level, setC4Level] = useState<C4Level>("container");
  const [selectedNode, setSelectedNode] = useState<DiagramNode | null>(null);

  // Header : historique des discussions (aucune limite — voir handleNewConversation)
  // + pop-up de connexion API.
  const [history, setHistory] = useState<ConversationSummary[]>(mockConversationHistory);
  const [apiDialogOpen, setApiDialogOpen] = useState(false);
  const [apiToast, setApiToast] = useState<ApiConnectionResult | null>(null);

  // Chargement de l'état initial réel depuis le backend (Étape 2/3). En
  // cas d'échec, on reste sur un état vide plutôt qu'un repli silencieux
  // vers les données mock (voir contrainte de l'Étape 3) — le toast
  // d'erreur signale explicitement le problème.
  useEffect(() => {
    fetchPhases()
      .then((infos) => {
        setPhases(infos.map((info) => ({ id: info.id, label: phaseLabel(info.id), nodes: [] })));
      })
      .catch((err) => {
        console.error("Échec du chargement des phases :", err);
        setApiToast("error");
      });

    fetchFindings()
      .then(setFindings)
      .catch((err) => {
        console.error("Échec du chargement des findings :", err);
        setApiToast("error");
      });

    fetchBranches()
      .then(setBranches)
      .catch((err) => {
        console.error("Échec du chargement des branches de code :", err);
        setApiToast("error");
      });
  }, []);

  function nowLabel() {
    const now = new Date();
    return `Aujourd'hui, ${now.getHours()}:${String(now.getMinutes()).padStart(2, "0")}`;
  }

  /**
   * Archive la conversation en cours dans l'historique avant de la remplacer.
   * Ne crée pas d'entrée si aucun message utilisateur n'a encore été envoyé
   * (conversation vide — rien de significatif à garder).
   * `setHistory` n'impose aucune limite : chaque appel ajoute une entrée en
   * tête de liste, sans plafond ni troncature.
   */
  function archiveCurrentConversation() {
    const firstUserMessage = messages.find((m) => m.role === "user");
    if (!firstUserMessage) return;
    const title =
      firstUserMessage.text.length > 48
        ? `${firstUserMessage.text.slice(0, 48)}…`
        : firstUserMessage.text;
    const id = crypto.randomUUID();
    const date = nowLabel();
    setHistory((prev) => [{ id, title, date }, ...prev]);

    // Le vrai titre devrait être généré par le LLM plutôt que tronqué
    // naïvement — hors périmètre de la fusion frontend/backend elle-même,
    // laissé tel quel intentionnellement.
    createConversation(id, title, date, messages).catch((err) => {
      console.error("Échec de la persistance de la conversation :", err);
      setApiToast("error");
    });
  }

  function handleNewConversation() {
    archiveCurrentConversation();
    setMessages([
      {
        id: crypto.randomUUID(),
        role: "system",
        text: "Nouvelle discussion. Décrivez votre besoin en voix ou en texte.",
        time: nowLabel().split(", ")[1],
      },
    ]);
  }

  function handleSelectConversation(conv: ConversationSummary) {
    archiveCurrentConversation();
    fetchConversation(conv.id)
      .then((full) => {
        setMessages(full.transcript as ChatMessage[]);
      })
      .catch((err) => {
        console.error("Échec du chargement de la conversation :", err);
        setApiToast("error");
        setMessages([
          {
            id: crypto.randomUUID(),
            role: "system",
            text: `Impossible de charger "${conv.title}" (${conv.date}).`,
            time: nowLabel().split(", ")[1],
          },
        ]);
      });
  }

  function handleApiResult(result: ApiConnectionResult) {
    setApiDialogOpen(false);
    setApiToast(result);
  }

  /**
   * Fusionne un événement SSE de nœud dans l'état `phases`. Si la phase ou
   * le nœud n'existent pas encore (garde défensive — en usage normal,
   * fetchPhases() au montage a déjà créé toutes les phases connues), ils
   * sont créés à la volée plutôt que silencieusement ignorés.
   */
  function applyNodeEvent(phaseId: string, nodeId: string, status: NodeRunStatus, error?: string) {
    setPhases((prev) => {
      const existingPhase = prev.find((p) => p.id === phaseId);
      if (!existingPhase) {
        return [
          ...prev,
          { id: phaseId, label: phaseLabel(phaseId), nodes: [{ id: nodeId, tag: nodeId, status, error }] },
        ];
      }
      return prev.map((p) => {
        if (p.id !== phaseId) return p;
        const existingNode = p.nodes.find((n) => n.id === nodeId);
        if (!existingNode) {
          return { ...p, nodes: [...p.nodes, { id: nodeId, tag: nodeId, status, error }] };
        }
        return {
          ...p,
          nodes: p.nodes.map((n) => (n.id === nodeId ? { ...n, status, error } : n)),
        };
      });
    });
  }

  function subscribeAndApply(runId: string) {
    subscribeToPipelineEvents(runId, (event) => {
      if (event.type === "node") {
        applyNodeEvent(event.phaseId, event.nodeId, event.status, event.error);
      } else if (event.type === "error") {
        console.error("Pipeline :", event.message);
        setApiToast("error");
      }
    });
  }

  function handleSend(text: string) {
    const now = new Date();
    const time = `${now.getHours()}:${String(now.getMinutes()).padStart(2, "0")}`;
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", text, time },
    ]);

    // Étape 1b : pipeline complet (10 phases réelles), plus limité à
    // "elicit" seule comme en Étape 1a.
    runPipeline(text)
      .then(({ run_id }) => subscribeAndApply(run_id))
      .catch((err) => {
        console.error("Échec du déclenchement du pipeline :", err);
        setApiToast("error");
      });
  }

  // ── Pipeline : relance d'un nœud ou d'une phase ──────────────────────────────
  function retryNode(phaseId: string, nodeId: string) {
    setPhases((prev) =>
      prev.map((p) =>
        p.id !== phaseId
          ? p
          : {
              ...p,
              nodes: p.nodes.map((n) =>
                n.id === nodeId ? { ...n, status: "running", error: undefined } : n,
              ),
            },
      ),
    );
    apiRetryNode(nodeId)
      .then(({ run_id }) => subscribeAndApply(run_id))
      .catch((err) => {
        console.error(`Échec du retry du nœud ${nodeId} :`, err);
        setApiToast("error");
      });
  }

  function retryPhase(phaseId: string) {
    setPhases((prev) =>
      prev.map((p) =>
        p.id !== phaseId
          ? p
          : { ...p, nodes: p.nodes.map((n) => ({ ...n, status: "running", error: undefined })) },
      ),
    );
    apiRetryPhase(phaseId)
      .then(({ run_id }) => subscribeAndApply(run_id))
      .catch((err) => {
        console.error(`Échec du retry de la phase ${phaseId} :`, err);
        setApiToast("error");
      });
  }

  // ── Network : sélection de nœud + drill-down ─────────────────────────────────
  function handleNodeClick(node: DiagramNode) {
    setSelectedNode(node);
  }

  function handleDrillDown() {
    setC4Level("component");
    setSelectedNode(null);
  }

  function handleLevelChange(level: C4Level) {
    setC4Level(level);
    setSelectedNode(null);
  }

  // ── Coding : décisions de revue ───────────────────────────────────────────────
  function acceptFile(branchId: string, fileId: string) {
    setBranches((prev) =>
      prev.map((b) =>
        b.id !== branchId
          ? b
          : { ...b, files: b.files.map((f) => (f.id === fileId ? { ...f, status: "accepted" } : f)) },
      ),
    );
    apiAcceptFile(fileId).catch((err) => {
      console.error(`Échec de l'acceptation du fichier ${fileId} :`, err);
      setApiToast("error");
    });
  }

  function requestFix(branchId: string, fileId: string) {
    setBranches((prev) =>
      prev.map((b) =>
        b.id !== branchId
          ? b
          : { ...b, files: b.files.map((f) => (f.id === fileId ? { ...f, status: "needs-fix" } : f)) },
      ),
    );
    apiRequestFileFix(fileId).catch((err) => {
      console.error(`Échec de la demande de correction du fichier ${fileId} :`, err);
      setApiToast("error");
    });
  }

  // ── Security : ignorer / réactiver un finding ────────────────────────────────
  function ignoreFinding(id: string, reason: string, expiresOn: string) {
    setFindings((prev) =>
      prev.map((f) => (f.id === id ? { ...f, ignored: { reason, expiresOn } } : f)),
    );
    apiIgnoreFinding(id, reason, expiresOn).catch((err) => {
      console.error(`Échec de l'ignore du finding ${id} :`, err);
      setApiToast("error");
    });
  }

  function unignoreFinding(id: string) {
    setFindings((prev) =>
      prev.map((f) => (f.id === id ? { ...f, ignored: undefined } : f)),
    );
    // Ce endpoint n'avait pas de `// TODO :` dans le code d'origine,
    // contrairement à ignoreFinding — câblé quand même (voir Étape 3 du
    // prompt de fusion).
    apiUnignoreFinding(id).catch((err) => {
      console.error(`Échec de l'unignore du finding ${id} :`, err);
      setApiToast("error");
    });
  }

  const openPhase = phases.find((p) => p.id === openPhaseId) ?? null;

  const pendingReview = branches.reduce(
    (sum, b) => sum + b.files.filter((f) => f.status === "pending").length,
    0,
  );
  const criticalOpen = findings.filter((f) => f.severity === "critical" && !f.ignored).length;

  const linkedFindingsForSelectedNode = selectedNode
    ? findings.filter((f) => f.relatedNodeId === selectedNode.id)
    : [];

  return (
    <div className="mx-auto flex h-screen max-w-6xl flex-col p-4">
      <div className="relative flex flex-1 flex-col overflow-hidden rounded-app border border-gray-200 bg-white shadow-app">
        <Header
          status="Prêt"
          userInitials="IK"
          history={history}
          onNewConversation={handleNewConversation}
          onSelectConversation={handleSelectConversation}
          onOpenApiDialog={() => setApiDialogOpen(true)}
        />

        <div className="flex flex-1 gap-4 overflow-hidden p-4">
          <div className="flex w-80 shrink-0 flex-col gap-4">
            <ConversationPanel messages={messages} onSend={handleSend} />
            <PipelinePanel phases={phases} onSelectPhase={setOpenPhaseId} />
          </div>

          <div className="flex flex-1 flex-col overflow-hidden rounded-card border border-gray-200">
            <TabBar
              active={activeTab}
              onChange={setActiveTab}
              badges={{ coding: pendingReview, security: criticalOpen }}
            />

            {activeTab === "network" && (
              <NetworkView
                level={c4Level}
                onLevelChange={handleLevelChange}
                selectedNodeId={selectedNode?.id}
                onNodeClick={handleNodeClick}
                toolStatus={mockToolStatus}
              />
            )}
            {activeTab === "coding" && (
              <CodingView
                branches={branches}
                onAcceptFile={acceptFile}
                onRequestFix={requestFix}
              />
            )}
            {activeTab === "security" && (
              <SecurityView
                findings={findings}
                onIgnore={ignoreFinding}
                onUnignore={unignoreFinding}
              />
            )}
            {activeTab === "registry" && <RegistryView />}
          </div>
        </div>

        {openPhase && (
          <SidePanel title={`Phase — ${openPhase.label}`} onClose={() => setOpenPhaseId(null)}>
            <PhaseDetailPanel
              phase={openPhase}
              onRetryNode={(nodeId) => retryNode(openPhase.id, nodeId)}
              onRetryPhase={() => retryPhase(openPhase.id)}
            />
          </SidePanel>
        )}

        {selectedNode && (
          <SidePanel title="Détail du nœud" onClose={() => setSelectedNode(null)}>
            <NodeDetailPanel
              node={findNodeById(selectedNode.id) ?? selectedNode}
              linkedFindings={linkedFindingsForSelectedNode}
              onDrillDown={selectedNode.drillable ? handleDrillDown : undefined}
            />
          </SidePanel>
        )}

        {apiDialogOpen && (
          <ApiConnectionDialog
            onCancel={() => setApiDialogOpen(false)}
            onResult={handleApiResult}
          />
        )}

        {apiToast && (
          <ApiStatusToast result={apiToast} onDismiss={() => setApiToast(null)} />
        )}
      </div>
    </div>
  );
}
