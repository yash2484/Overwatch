import type { DetectionFeature } from "../api/types";

/** What each vertical monitors — the "what am I looking at" line. */
export const MONITOR_LABEL: Record<string, string> = {
  port: "Port construction",
  flood: "Flood monitoring",
};

/** Human noun per change type, with an explicit plural (naive +s mangles "area of loss"). */
export const CHANGE_NOUN: Record<string, { one: string; many: string }> = {
  construction: { one: "construction site", many: "construction sites" },
  flooding: { one: "flooded area", many: "flooded areas" },
};

/** Short label for the legend. */
export const CHANGE_SHORT: Record<string, string> = {
  construction: "Construction",
  flooding: "Flooding",
};

/** CSS token per change type — the same hue the polygons use on the map. */
export const CHANGE_COLOR_VAR: Record<string, string> = {
  construction: "var(--color-change-construction)",
  flooding: "var(--color-change-water)",
};

export function monthYear(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function countByType(detections: DetectionFeature[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const d of detections) {
    const t = d.properties.change_type;
    counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  return counts;
}

/**
 * One-line finding derived purely from the detections — no brief required, so it works
 * even before (or without) an LLM brief. "12 construction sites" / "No change detected".
 */
export function findingSummary(detections: DetectionFeature[]): string {
  if (detections.length === 0) return "No change detected";
  return [...countByType(detections).entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([type, n]) => {
      const noun = CHANGE_NOUN[type] ?? { one: type.replace(/_/g, " "), many: `${type} events` };
      return `${n} ${n === 1 ? noun.one : noun.many}`;
    })
    .join(", ");
}

/** Distinct change types present, most-common first — for the legend. */
export function changeTypesPresent(detections: DetectionFeature[]): string[] {
  return [...countByType(detections).entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
}
