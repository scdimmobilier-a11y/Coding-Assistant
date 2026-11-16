import type { DiagramNode } from "../../types";
import NodeBox from "./NodeBox";

/**
 * Diagramme C4 "niveau composant" — drill-down depuis un conteneur.
 * Chaîne horizontale simple + une branche secondaire optionnelle, cohérent
 * visuellement avec ContainerDiagram mais sans la personne/le hub du dessus
 * (le composant parent est indiqué par NetworkView via le fil d'Ariane).
 */

interface ComponentDiagramProps {
  chain: DiagramNode[];
  branch?: { fromId: string; node: DiagramNode };
  selectedId?: string;
  onNodeClick: (node: DiagramNode) => void;
}

const BOX_W = 170;
const BOX_H = 68;
const GAP = 50;
const ROW_Y = 40;
const BRANCH_Y = 150;

export default function ComponentDiagram({
  chain,
  branch,
  selectedId,
  onNodeClick,
}: ComponentDiagramProps) {
  const width = chain.length * BOX_W + (chain.length - 1) * GAP + 40;
  const startX = 20;
  const centers = chain.map((_, i) => startX + i * (BOX_W + GAP) + BOX_W / 2);

  const branchFromIndex = branch ? chain.findIndex((n) => n.id === branch.fromId) : -1;
  const branchFromCx = branchFromIndex >= 0 ? centers[branchFromIndex] : width / 2;

  const height = branch ? BRANCH_Y + BOX_H + 20 : ROW_Y + BOX_H + 20;

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" className="mx-auto max-w-3xl">
      <title>Diagramme C4 — niveau composant</title>
      <desc>
        {chain.map((n) => n.title).join(" → ")}
        {branch ? `, avec ${branch.node.title} en branche depuis ${branch.fromId}` : ""}.
      </desc>
      <defs>
        <marker
          id="c4-arrow-comp"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path
            d="M2 1L8 5L2 9"
            fill="none"
            stroke="#9CA3AF"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </marker>
      </defs>

      {centers.slice(0, -1).map((cx, i) => (
        <line
          key={chain[i].id}
          x1={cx + BOX_W / 2}
          y1={ROW_Y + BOX_H / 2}
          x2={centers[i + 1] - BOX_W / 2}
          y2={ROW_Y + BOX_H / 2}
          stroke="#9CA3AF"
          strokeWidth={1}
          markerEnd="url(#c4-arrow-comp)"
        />
      ))}

      {chain.map((node, i) => (
        <NodeBox
          key={node.id}
          node={node}
          x={centers[i] - BOX_W / 2}
          y={ROW_Y}
          w={BOX_W}
          h={BOX_H}
          selected={selectedId === node.id}
          onClick={onNodeClick}
        />
      ))}

      {branch && (
        <>
          <line
            x1={branchFromCx}
            y1={ROW_Y + BOX_H}
            x2={branchFromCx}
            y2={BRANCH_Y}
            stroke="#9CA3AF"
            strokeWidth={1}
            strokeDasharray="4 3"
            markerEnd="url(#c4-arrow-comp)"
          />
          <NodeBox
            node={branch.node}
            x={branchFromCx - BOX_W / 2}
            y={BRANCH_Y}
            w={BOX_W}
            h={BOX_H}
            selected={selectedId === branch.node.id}
            onClick={onNodeClick}
          />
        </>
      )}
    </svg>
  );
}
