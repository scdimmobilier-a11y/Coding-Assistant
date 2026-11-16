import { Check } from "lucide-react";
import Breadcrumb from "../Breadcrumb";
import SystemDiagram from "../diagram/SystemDiagram";
import ContainerDiagram from "../diagram/ContainerDiagram";
import ComponentDiagram from "../diagram/ComponentDiagram";
import type { C4Level, DiagramNode, ToolStatus } from "../../types";
import {
  mockSystemLevel,
  mockContainerLevel,
  mockComponentLevel,
} from "../../data/mockPipeline";

interface NetworkViewProps {
  level: C4Level;
  onLevelChange: (level: C4Level) => void;
  selectedNodeId?: string;
  onNodeClick: (node: DiagramNode) => void;
  toolStatus: ToolStatus[];
}

const TITLE: Record<C4Level, string> = {
  system: "Vue C4 – Niveau Système",
  container: "Vue C4 – Niveau Conteneur",
  component: "Vue C4 – Niveau Composant",
};

const SUBTITLE: Record<C4Level, string> = {
  system: "Vue d'ensemble simplifiée de la plateforme.",
  container: "Représentation des composants déployables et de leurs interactions.",
  component: "Détail interne du conteneur Payment Service.",
};

export default function NetworkView({
  level,
  onLevelChange,
  selectedNodeId,
  onNodeClick,
  toolStatus,
}: NetworkViewProps) {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mb-1">
        <Breadcrumb
          level={level}
          componentParentTitle={mockComponentLevel.parentTitle}
          onNavigate={onLevelChange}
        />
      </div>

      <div className="mb-4 mt-2">
        <h2 className="text-lg font-semibold text-gray-900">{TITLE[level]}</h2>
        <p className="mt-1 text-sm text-gray-500">{SUBTITLE[level]}</p>
      </div>

      <div className="rounded-card border border-gray-200 bg-white p-6">
        {level === "system" && (
          <SystemDiagram
            person={mockSystemLevel.person}
            system={mockSystemLevel.system}
            selectedId={selectedNodeId}
            onNodeClick={onNodeClick}
          />
        )}
        {level === "container" && (
          <ContainerDiagram
            person={mockContainerLevel.person}
            hub={mockContainerLevel.hub}
            hubEdgeLabel={mockContainerLevel.hubEdgeLabel}
            downstream={mockContainerLevel.downstream}
            secondary={mockContainerLevel.secondary}
            selectedId={selectedNodeId}
            onNodeClick={onNodeClick}
          />
        )}
        {level === "component" && (
          <ComponentDiagram
            chain={mockComponentLevel.chain}
            branch={mockComponentLevel.branch}
            selectedId={selectedNodeId}
            onNodeClick={onNodeClick}
          />
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-3">
        {toolStatus.map((tool) => (
          <div
            key={tool.id}
            className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm text-gray-700"
          >
            {tool.label}
            {tool.passed && (
              <Check className="h-4 w-4 text-green-600" aria-hidden="true" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
