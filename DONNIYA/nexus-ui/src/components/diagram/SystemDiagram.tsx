import { User } from "lucide-react";
import type { DiagramNode } from "../../types";
import NodeBox from "./NodeBox";

/** Diagramme C4 "niveau système" — la vue la plus zoomée. */

interface SystemDiagramProps {
  person: DiagramNode;
  system: DiagramNode;
  selectedId?: string;
  onNodeClick: (node: DiagramNode) => void;
}

export default function SystemDiagram({
  person,
  system,
  selectedId,
  onNodeClick,
}: SystemDiagramProps) {
  const width = 500;
  const cx = width / 2;

  return (
    <svg width="100%" viewBox={`0 0 ${width} 220`} role="img" className="mx-auto max-w-md">
      <title>Diagramme C4 — niveau système</title>
      <desc>
        {person.title} utilise {system.title}.
      </desc>
      <defs>
        <marker
          id="c4-arrow-sys"
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

      <g
        role="button"
        tabIndex={0}
        className="cursor-pointer outline-none"
        onClick={() => onNodeClick(person)}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onNodeClick(person)}
      >
        <circle cx={cx} cy={40} r={18} className="fill-blue-50 stroke-blue-300" strokeWidth={1} />
        <foreignObject x={cx - 10} y={30} width={20} height={20}>
          <User className="h-5 w-5 text-blue-600" aria-hidden="true" />
        </foreignObject>
        <text x={cx} y={72} textAnchor="middle" className="fill-gray-900 text-[13px] font-semibold">
          {person.title}
        </text>
      </g>

      <line
        x1={cx}
        y1={90}
        x2={cx}
        y2={110}
        stroke="#9CA3AF"
        strokeWidth={1}
        markerEnd="url(#c4-arrow-sys)"
      />

      <NodeBox
        node={system}
        x={cx - 150}
        y={110}
        w={300}
        h={80}
        selected={selectedId === system.id}
        onClick={onNodeClick}
      />
    </svg>
  );
}
