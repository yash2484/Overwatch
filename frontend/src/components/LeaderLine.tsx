import type * as maplibregl from "maplibre-gl";
import type { RefObject } from "react";
import { useEffect, useMemo, useRef } from "react";
import type { DetectionFeature } from "../api/types";
import { useSelection } from "../state/SelectionContext";

// Above ~6 lines the map is a thicket; the polygon halos already carry a large set. Below
// that, the line makes the claim→evidence link literal — the demo's best three seconds.
const MAX_LINES = 6;

/**
 * Draws magenta connectors from the selected claim's row (in the brief panel) to the
 * centroids of the detections it cites (on the map). A rAF loop re-projects every frame so
 * the lines stay glued through the fly-to ease and any pan/zoom. Purely presentational and
 * pointer-transparent.
 */
export function LeaderLine({
  mapRef,
  detections,
}: {
  mapRef: RefObject<maplibregl.Map | null>;
  detections: DetectionFeature[];
}) {
  const { state } = useSelection();
  const lineRefs = useRef<Array<SVGLineElement | null>>([]);
  const dotRefs = useRef<Array<SVGCircleElement | null>>([]);

  const centroids = useMemo(() => {
    const m = new Map<number, [number, number]>();
    for (const d of detections) {
      const ring = d.geometry.coordinates[0] ?? [];
      let sx = 0;
      let sy = 0;
      for (const [x, y] of ring) {
        sx += x;
        sy += y;
      }
      if (ring.length) m.set(d.properties.id, [sx / ring.length, sy / ring.length]);
    }
    return m;
  }, [detections]);

  useEffect(() => {
    const hideAll = () => {
      for (let i = 0; i < MAX_LINES; i++) {
        if (lineRefs.current[i]) lineRefs.current[i]!.style.opacity = "0";
        if (dotRefs.current[i]) dotRefs.current[i]!.style.opacity = "0";
      }
    };

    const { selectedClaim, highlightedDetections: ids } = state;
    if (selectedClaim === null || ids.length === 0 || ids.length > MAX_LINES) {
      hideAll();
      return;
    }

    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const map = mapRef.current;
      const claimEl = document.querySelector(`[data-claim-seq="${selectedClaim}"]`);
      if (!map || !claimEl) {
        hideAll();
        return;
      }
      const cr = claimEl.getBoundingClientRect();
      const ax = cr.left + 6;
      const ay = cr.top + cr.height / 2;
      const mr = map.getContainer().getBoundingClientRect();

      ids.forEach((id, i) => {
        const line = lineRefs.current[i];
        const dot = dotRefs.current[i];
        const c = centroids.get(id);
        if (!line || !dot || !c) return;
        const p = map.project(c);
        const x = mr.left + p.x;
        const y = mr.top + p.y;
        // Skip if the centroid is off the map viewport (behind the panel / out of frame).
        const onMap = p.x >= 0 && p.x <= mr.width && p.y >= 0 && p.y <= mr.height;
        line.setAttribute("x1", String(ax));
        line.setAttribute("y1", String(ay));
        line.setAttribute("x2", String(x));
        line.setAttribute("y2", String(y));
        line.style.opacity = onMap ? "0.85" : "0";
        dot.setAttribute("cx", String(x));
        dot.setAttribute("cy", String(y));
        dot.style.opacity = onMap ? "1" : "0";
      });
      for (let i = ids.length; i < MAX_LINES; i++) {
        if (lineRefs.current[i]) lineRefs.current[i]!.style.opacity = "0";
        if (dotRefs.current[i]) dotRefs.current[i]!.style.opacity = "0";
      }
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      hideAll();
    };
  }, [state, mapRef, centroids]);

  return (
    <svg
      className="pointer-events-none fixed inset-0 z-30"
      width="100%"
      height="100%"
      aria-hidden
    >
      {Array.from({ length: MAX_LINES }).map((_, i) => (
        <g key={i}>
          <line
            ref={(el) => {
              lineRefs.current[i] = el;
            }}
            style={{ stroke: "var(--color-evidence-line)", strokeWidth: 1.5, opacity: 0 }}
          />
          <circle
            ref={(el) => {
              dotRefs.current[i] = el;
            }}
            r={3.5}
            style={{ fill: "var(--color-evidence)", opacity: 0 }}
          />
        </g>
      ))}
    </svg>
  );
}
