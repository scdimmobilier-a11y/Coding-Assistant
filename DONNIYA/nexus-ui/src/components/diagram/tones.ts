import type { NodeTone } from "../../types";

export const TONE_BOX: Record<NodeTone, string> = {
  blue: "fill-blue-50 stroke-blue-300",
  purple: "fill-purple-50 stroke-purple-300",
  amber: "fill-amber-50 stroke-amber-300",
  green: "fill-green-50 stroke-green-300",
  red: "fill-red-50 stroke-red-300",
  gray: "fill-white stroke-gray-300",
};

export const TONE_TITLE: Record<NodeTone, string> = {
  blue: "fill-blue-900",
  purple: "fill-purple-900",
  amber: "fill-amber-900",
  green: "fill-green-900",
  red: "fill-red-900",
  gray: "fill-gray-700",
};

export const TONE_META: Record<NodeTone, string> = {
  blue: "fill-blue-600",
  purple: "fill-purple-600",
  amber: "fill-amber-700",
  green: "fill-green-700",
  red: "fill-red-700",
  gray: "fill-gray-500",
};

/** Contour de sélection appliqué par-dessus la teinte quand le nœud est actif. */
export const SELECTED_RING = "stroke-blue-500";
