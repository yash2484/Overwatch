/** Scene-raster attachment for the swipe maps.
 *
 * Extracted from MapCanvas so the style-readiness path is testable without a real map:
 * that path is where the after-image silently goes missing.
 */

import { sceneImageUrl } from "../api/client";
import type { SceneSummary } from "../api/types";

/** Image-source corners, clockwise from top-left. maplibre types this as a fixed 4-tuple. */
type ImageCorners = [
  [number, number],
  [number, number],
  [number, number],
  [number, number],
];

/** The slice of maplibre's Map surface this module touches, so tests can fake it. */
export interface RasterMap {
  /** `void` because maplibre's own signature is `boolean | void`; an unloaded map is falsy. */
  isStyleLoaded(): boolean | void;
  getLayer(id: string): unknown;
  removeLayer(id: string): void;
  getSource(id: string): unknown;
  removeSource(id: string): void;
  addSource(
    id: string,
    source: { type: "image"; url: string; coordinates: ImageCorners },
  ): void;
  addLayer(
    layer: {
      id: string;
      type: "raster";
      source: string;
      paint: Record<string, number>;
    },
    before?: string,
  ): void;
  getStyle(): { layers?: { id: string; type: string }[] };
  once(type: "idle", listener: () => void): unknown;
}

/** Latest scene asked for per map+key, so a deferred retry attaches what was last requested. */
const requested = new WeakMap<RasterMap, Map<string, SceneSummary | null>>();
/** Keys already waiting on an idle retry, so repeated deferrals don't stack listeners. */
const awaitingIdle = new WeakMap<RasterMap, Set<string>>();

/** Insert (or replace) a scene raster, clipped below the first label layer for legibility. */
export function applyRaster(
  map: RasterMap,
  key: string,
  scene: SceneSummary | null,
): void {
  const wanted = requested.get(map) ?? new Map<string, SceneSummary | null>();
  requested.set(map, wanted);
  wanted.set(key, scene);

  // Never touch sources/layers before the style is up — doing so throws "Style is not done
  // loading", which is uncaught and would blank the app.
  //
  // Deferring is not enough on its own, and that was the bug: the caller's readiness flag
  // flips exactly once, on maplibre's `load`, and the scene id never changes afterwards, so
  // nothing re-ran this. The after map loses that race routinely because it is jump-synced
  // to the before map's camera in the same tick its flag flips — the jump starts new basemap
  // tile loads, so isStyleLoaded() reads false right when the effect fires. The raster was
  // dropped for good and the pane showed bare basemap under the detection polygons until a
  // reload happened to win. So own the retry here rather than trusting the caller to re-fire.
  if (!map.isStyleLoaded()) {
    const pending = awaitingIdle.get(map) ?? new Set<string>();
    awaitingIdle.set(map, pending);
    if (!pending.has(key)) {
      pending.add(key);
      map.once("idle", () => {
        pending.delete(key);
        applyRaster(map, key, wanted.get(key) ?? null);
      });
    }
    return;
  }
  const id = `scene-${key}`;
  if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(id)) map.removeSource(id);
  if (!scene) return;
  const [w, s, e, n] = scene.bounds;
  map.addSource(id, {
    type: "image",
    url: sceneImageUrl(scene.id),
    coordinates: [
      [w, n],
      [e, n],
      [e, s],
      [w, s],
    ],
  });
  const firstSymbol = map
    .getStyle()
    .layers?.find((l: { type: string }) => l.type === "symbol")?.id;
  map.addLayer(
    {
      id,
      type: "raster",
      source: id,
      paint: { "raster-opacity": 1, "raster-fade-duration": 0 },
    },
    firstSymbol,
  );
}
