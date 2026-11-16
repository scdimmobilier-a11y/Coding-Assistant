import { User } from "lucide-react";
import type { DiagramNode } from "../../types";
import NodeBox from "./NodeBox";

/**
 * Diagramme C4 "niveau conteneur" : une personne, un conteneur central (hub),
 * un éventail de dépendances, et un nœud secondaire optionnel relié en
 * pointillés depuis l'une des dépendances.
 *
 * Chaque nœud est cliquable et ouvre le panneau de détail (voir
 * NodeDetailPanel.tsx, câblé depuis NetworkView.tsx). Le hub porte
 * `drillable: true` dans les données de démo : son panneau de détail
 * propose un bouton pour descendre au niveau "component".
 *
 * Pour un graphe C4 arbitraire (topologie non fixée), remplacer ce composant
 * par un rendu piloté par un moteur de layout réel (dagre / elkjs) alimenté
 * par l'export JSON du générateur LikeC4 vendorisé dans
 * native/likec4/typescript/generators/src/.
 */

interface ContainerDiagramProps {
  person: DiagramNode;
  hub: DiagramNode;
  hubEdgeLabel: string;
  downstream: DiagramNode[];
  secondary?: { fromId: string; node: DiagramNode };
  selectedId?: string;
  onNodeClick: (node: DiagramNode) => void;
}

const BOX_W = 180;
const BOX_H = 70;
const GAP = 20;
const PERSON_CY = 50;
const HUB_Y = 150;
const HUB_H = 64;
const ROW_Y = 250;
const SECONDARY_Y = 350;

function elbow(x1: number, y1: number, x2: number, y2: number, midY: number) {
  if (x1 === x2) return `M ${x1} ${y1} L ${x2} ${y2}`;
  return `M ${x1} ${y1} L ${x1} ${midY} L ${x2} ${midY} L ${x2} ${y2}`;
}

export default function ContainerDiagram({
  person,
  hub,
  hubEdgeLabel,
  downstream,
  secondary,
  selectedId,
  onNodeClick,
}: ContainerDiagramProps) {
  const width = 720;

  const rowWidth = downstream.length * BOX_W + (downstream.length - 1) * GAP;
  const rowStartX = (width - rowWidth) / 2;
  const childCenters = downstream.map(
    (_, i) => rowStartX + i * (BOX_W + GAP) + BOX_W / 2,
  );

  const hubCx = width / 2;
  const hubX = hubCx - 110;
  const hubW = 220;

  const secondaryFromIndex = secondary
    ? downstream.findIndex((n) => n.id === secondary.fromId)
    : -1;
  const secondaryFromCx =
    secondaryFromIndex >= 0 ? childCenters[secondaryFromIndex] : hubCx;

  const secondaryW = 440;
  const secondaryX = width / 2 - secondaryW / 2;

  const height = secondary ? SECONDARY_Y + BOX_H + 30 : ROW_Y + BOX_H + 30;
  const elbowMidY = HUB_Y + HUB_H + (ROW_Y - (HUB_Y + HUB_H)) / 2;

  const hubEdgeLines = hubEdgeLabel.split("\n");

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      className="mx-auto max-w-2xl"
    >
      <title>Diagramme C4 — niveau conteneur</title>
      <desc>
        {person.title} appelle {hub.title}, qui dépend de{" "}
        {downstream.map((n) => n.title).join(", ")}
        {secondary ? `, dont découle ${secondary.node.title}` : ""}.
      </desc>

      <defs>
        <marker
          id="c4-arrow"
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

      {/* Personne */}
      <g
        role="button"
        tabIndex={0}
        className="cursor-pointer outline-none"
        onClick={() => onNodeClick(person)}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onNodeClick(person)}
      >
        <circle cx={hubCx} cy={PERSON_CY} r={18} className="fill-blue-50 stroke-blue-300" strokeWidth={1} />
        <foreignObject x={hubCx - 10} y={PERSON_CY - 10} width={20} height={20}>
          <User className="h-5 w-5 text-blue-600" aria-hidden="true" />
        </foreignObject>
        <text
          x={hubCx}
          y={PERSON_CY + 32}
          textAnchor="middle"
          className="fill-gray-900 text-[13px] font-semibold"
        >
          {person.title}
        </text>
        <text
          x={hubCx}
          y={PERSON_CY + 47}
          textAnchor="middle"
          className="fill-gray-400 text-[11px]"
        >
          {person.meta}
        </text>
      </g>

      {/* Personne → Hub */}
      <line
        x1={hubCx}
        y1={PERSON_CY + 58}
        x2={hubCx}
        y2={HUB_Y}
        stroke="#9CA3AF"
        strokeWidth={1}
        markerEnd="url(#c4-arrow)"
      />
      <text x={hubCx + 12} y={PERSON_CY + 74} className="fill-gray-500 text-[11px]">
        {hubEdgeLines.map((line, i) => (
          <tspan key={i} x={hubCx + 12} dy={i === 0 ? 0 : 13}>
            {line}
          </tspan>
        ))}
      </text>

      {/* Hub */}
      <NodeBox
        node={hub}
        x={hubX}
        y={HUB_Y}
        w={hubW}
        h={HUB_H}
        selected={selectedId === hub.id}
        onClick={onNodeClick}
      />

      {/* Hub → éventail */}
      {childCenters.map((cx, i) => (
        <path
          key={downstream[i].id}
          d={elbow(hubCx, HUB_Y + HUB_H, cx, ROW_Y, elbowMidY)}
          fill="none"
          stroke="#9CA3AF"
          strokeWidth={1}
          markerEnd="url(#c4-arrow)"
        />
      ))}

      {/* Éventail */}
      {downstream.map((node, i) => (
        <NodeBox
          key={node.id}
          node={node}
          x={rowStartX + i * (BOX_W + GAP)}
          y={ROW_Y}
          w={BOX_W}
          h={BOX_H}
          selected={selectedId === node.id}
          onClick={onNodeClick}
        />
      ))}

      {/* Downstream → secondaire */}
      {secondary && (
        <>
          <line
            x1={secondaryFromCx}
            y1={ROW_Y + BOX_H}
            x2={secondaryFromCx}
            y2={SECONDARY_Y}
            stroke="#9CA3AF"
            strokeWidth={1}
            strokeDasharray="4 3"
            markerEnd="url(#c4-arrow)"
          />
          <NodeBox
            node={secondary.node}
            x={secondaryX}
            y={SECONDARY_Y}
            w={secondaryW}
            h={BOX_H}
            selected={selectedId === secondary.node.id}
            onClick={onNodeClick}
          />
        </>
      )}
    </svg>
  );
}
