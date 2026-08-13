import type { Brief, DetectionFeature } from "../api/types";

export interface EvidenceIndex {
  byClaim: Map<number, number[]>;
  byDetection: Map<number, number[]>;
}

/**
 * The client-side join that makes the trust architecture visible: claim seq -> detection
 * ids, and the reverse. Both directions come from one pass, so they can never disagree.
 *
 * Evidence ids with no matching detection are dropped, never invented: a `stale` brief
 * legitimately cites detections that a re-run has since replaced. The reverse map records
 * claims in brief-iteration order, so panel highlighting is deterministic.
 */
export function buildEvidenceIndex(
  brief: Brief,
  detections: DetectionFeature[],
): EvidenceIndex {
  const known = new Set(detections.map((d) => d.properties.id));
  const byClaim = new Map<number, number[]>();
  const byDetection = new Map<number, number[]>();

  for (const claim of brief.claims) {
    const resolved = claim.detection_ids.filter((id) => known.has(id));
    byClaim.set(claim.seq, resolved);
    for (const id of resolved) {
      const claims = byDetection.get(id);
      if (claims) claims.push(claim.seq);
      else byDetection.set(id, [claim.seq]);
    }
  }
  return { byClaim, byDetection };
}

/** Union bounds of the given detections, or null when nothing resolves. */
export function boundsOf(
  detections: DetectionFeature[],
  ids: number[],
): [number, number, number, number] | null {
  const wanted = new Set(ids);
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  let found = false;

  for (const detection of detections) {
    if (!wanted.has(detection.properties.id)) continue;
    for (const ring of detection.geometry.coordinates) {
      for (const [x, y] of ring) {
        if (x < west) west = x;
        if (x > east) east = x;
        if (y < south) south = y;
        if (y > north) north = y;
        found = true;
      }
    }
  }
  return found ? [west, south, east, north] : null;
}
