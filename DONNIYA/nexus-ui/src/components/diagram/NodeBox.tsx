import type { DiagramNode } from "../../types";
import { TONE_BOX, TONE_TITLE, TONE_META, SELECTED_RING } from "./tones";

interface NodeBoxProps {
  node: DiagramNode;
  x: number;
  y: number;
  w: number;
  h: number;
  selected?: boolean;
  onClick?: (node: DiagramNode) => void;
}

/**
 * Rectangle C4 générique, réutilisé par ContainerDiagram, ComponentDiagram et
 * SystemDiagram. Cliquable : ouvre le panneau de détail du nœud (App.tsx).
 */
export default function NodeBox({ node, x, y, w, h, selected, onClick }: NodeBoxProps) {
  const lines = [node.meta, node.detail].filter(Boolean) as string[];

  return (
    <g
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={onClick ? "cursor-pointer outline-none" : undefined}
      onClick={() => onClick?.(node)}
      onKeyDown={(e) => {
        if (onClick && (e.key === "Enter" || e.key === " ")) onClick(node);
      }}
    >
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={8}
        strokeWidth={selected ? 2 : 1}
        strokeDasharray={node.dashed ? "4 3" : undefined}
        className={`${TONE_BOX[node.tone]} ${selected ? SELECTED_RING : ""} transition-[stroke-width]`}
      />
      <text
        x={x + w / 2}
        y={y + (lines.length ? 24 : h / 2)}
        textAnchor="middle"
        dominantBaseline="central"
        className={`text-[13px] font-semibold ${TONE_TITLE[node.tone]}`}
      >
        {node.title}
      </text>
      {lines.map((line, i) => (
        <text
          key={i}
          x={x + w / 2}
          y={y + 42 + i * 15}
          textAnchor="middle"
          dominantBaseline="central"
          className={`text-[11px] ${TONE_META[node.tone]}`}
        >
          {line}
        </text>
      ))}
    </g>
  );
}
