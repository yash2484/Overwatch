import { GeoJsonLayer } from "@deck.gl/layers";
import { MapboxOverlay } from "@deck.gl/mapbox";
import * as maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { sceneImageUrl } from "../api/client";
import type {
  Aoi,
  DetectionFeature,
  DetectionProperties,
  SceneSummary,
} from "../api/types";

// deck.gl's GeoJsonLayer<T> makes T the *properties* type; accessors receive a GeoJSON
// Feature whose .properties is T. A structural param avoids importing geojson's Feature.
type DetFeature = { properties: DetectionProperties };
import type { EvidenceIndex } from "../evidence";
import { boundsOf } from "../evidence";
import { useSelection } from "../state/SelectionContext";

// Carto dark-matter is a graphite vector basemap; we tint its background to our surround
// token so the map reads as one system with the chrome, not bolted on. No API key needed.
const BASEMAP_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

// Change-type fills mirror the CSS tokens exactly (OKLCH -> sRGB). DATA, not decoration.
const CHANGE_FILL: Record<string, [number, number, number]> = {
  construction: [238, 151, 51],
  vegetation_loss: [242, 113, 106],
  flooding: [50, 179, 230],
};
const NEUTRAL: [number, number, number] = [160, 168, 178];
const EVIDENCE: [number, number, number] = [239, 109, 201]; // --color-evidence

const fillFor = (t: string) => CHANGE_FILL[t] ?? NEUTRAL;

interface Props {
  aoi: Aoi;
  before: SceneSummary | null;
  after: SceneSummary | null;
  detections: DetectionFeature[];
  index: EvidenceIndex | null;
  swipe: number;
}

function bboxOf(aoi: Aoi): [number, number, number, number] {
  const coords = aoi.geometry.coordinates.flat();
  const lngs = coords.map((c) => c[0]);
  const lats = coords.map((c) => c[1]);
  return [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)];
}

/** Push the vector basemap toward our graphite surround so it recedes behind the imagery. */
function tintBasemap(map: maplibregl.Map) {
  try {
    if (map.getLayer("background")) {
      map.setPaintProperty("background", "background-color", "#181b1f");
    }
    for (const layer of map.getStyle().layers ?? []) {
      if (layer.type === "fill" && /water/i.test(layer.id)) {
        map.setPaintProperty(layer.id, "fill-color", "#141b24");
      }
    }
  } catch {
    // A style without these layers is not fatal — the basemap just stays its default dark.
  }
}

/** Insert (or replace) a scene raster, clipped below the first label layer for legibility. */
function applyRaster(map: maplibregl.Map, key: string, scene: SceneSummary | null) {
  // Never touch sources/layers before the style is up — doing so throws "Style is not done
  // loading", which is uncaught and would blank the app. The ready flag re-fires this once
  // the style loads.
  if (!map.isStyleLoaded()) return;
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
    { id, type: "raster", source: id, paint: { "raster-opacity": 1, "raster-fade-duration": 0 } },
    firstSymbol,
  );
}

function detectionLayer(
  detections: DetectionFeature[],
  highlighted: number[],
  pickable: boolean,
  onPick: (id: number) => void,
) {
  const hi = new Set(highlighted);
  return new GeoJsonLayer<DetectionProperties>({
    id: "detections",
    data: { type: "FeatureCollection", features: detections } as never,
    pickable,
    stroked: true,
    filled: true,
    getFillColor: (f: DetFeature) => {
      const [r, g, b] = fillFor(f.properties.change_type);
      return [r, g, b, hi.has(f.properties.id) ? 120 : 45];
    },
    // Selection is a STATE — stroke weight + magenta halo — never a fill-hue swap, so the
    // change-type colour survives selection and meaning is never carried by colour alone.
    getLineColor: (f: DetFeature) =>
      hi.has(f.properties.id)
        ? [...EVIDENCE, 255]
        : [...fillFor(f.properties.change_type), 210],
    getLineWidth: (f: DetFeature) => (hi.has(f.properties.id) ? 4 : 1.5),
    lineWidthUnits: "pixels",
    updateTriggers: {
      getFillColor: highlighted,
      getLineColor: highlighted,
      getLineWidth: highlighted,
    },
    transitions: { getLineWidth: 180, getFillColor: 180, getLineColor: 180 },
    onClick: pickable
      ? ({ object }) => {
          if (object) onPick((object as DetFeature).properties.id);
          return true;
        }
      : undefined,
  });
}

export function MapCanvas({ aoi, before, after, detections, index, swipe }: Props) {
  const beforeRef = useRef<HTMLDivElement>(null);
  const afterRef = useRef<HTMLDivElement>(null);
  const beforeMap = useRef<maplibregl.Map | null>(null);
  const afterMap = useRef<maplibregl.Map | null>(null);
  const overlayBottom = useRef<MapboxOverlay | null>(null);
  const overlayTop = useRef<MapboxOverlay | null>(null);
  const { state, dispatch } = useSelection();

  // Latest selection/index in refs so the picking callback never goes stale without
  // re-initialising the map.
  const stateRef = useRef(state);
  stateRef.current = state;
  const indexRef = useRef(index);
  indexRef.current = index;
  const [readyB, setReadyB] = useState(false);
  const [readyA, setReadyA] = useState(false);

  // --- init both maps once ---
  useEffect(() => {
    if (!beforeRef.current || !afterRef.current || beforeMap.current) return;
    // Switching AOI tears down and recreates the maps; the new maps aren't loaded yet, so
    // reset readiness or the raster effects fire against an unloaded style.
    setReadyB(false);
    setReadyA(false);
    const bounds = bboxOf(aoi);
    const common = {
      style: BASEMAP_STYLE,
      bounds,
      fitBoundsOptions: { padding: 48 },
      attributionControl: false as const,
    };
    const b = new maplibregl.Map({ container: beforeRef.current, ...common });
    // The after map never receives events (its container is pointer-events:none); it only
    // follows the before map.
    const a = new maplibregl.Map({
      container: afterRef.current,
      ...common,
      interactive: false,
    });

    const oBottom = new MapboxOverlay({ interleaved: true, layers: [] });
    const oTop = new MapboxOverlay({ interleaved: true, layers: [] });
    b.addControl(oBottom);
    a.addControl(oTop);

    const onPick = (id: number) => {
      const claimSeqs = indexRef.current?.byDetection.get(id) ?? [];
      dispatch({ type: "selectDetection", claimSeqs, detectionId: id });
    };

    const sync = () => {
      a.jumpTo({
        center: b.getCenter(),
        zoom: b.getZoom(),
        bearing: b.getBearing(),
        pitch: b.getPitch(),
      });
    };
    b.on("move", sync);
    b.on("load", () => {
      tintBasemap(b);
      setReadyB(true);
      sync();
    });
    a.on("load", () => {
      tintBasemap(a);
      setReadyA(true);
    });

    // Container height can be 0 at init (layout/fonts not settled) — maplibre then falls
    // back to a 300px canvas. A ResizeObserver keeps both maps sized to the container.
    const ro = new ResizeObserver(() => {
      b.resize();
      a.resize();
    });
    if (beforeRef.current) ro.observe(beforeRef.current);

    beforeMap.current = b;
    afterMap.current = a;
    overlayBottom.current = oBottom;
    overlayTop.current = oTop;
    // Prime pick handler closure via a first layer set.
    oBottom.setProps({ layers: [detectionLayer(detections, state.highlightedDetections, true, onPick)] });
    oTop.setProps({ layers: [detectionLayer(detections, state.highlightedDetections, false, onPick)] });

    return () => {
      ro.disconnect();
      b.remove();
      a.remove();
      beforeMap.current = null;
      afterMap.current = null;
      overlayBottom.current = null;
      overlayTop.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aoi.slug]);

  // --- (re)apply rasters once the style is ready and whenever the scene changes ---
  useEffect(() => {
    if (readyB && beforeMap.current) applyRaster(beforeMap.current, "before", before);
  }, [readyB, before?.id]);
  useEffect(() => {
    if (readyA && afterMap.current) applyRaster(afterMap.current, "after", after);
  }, [readyA, after?.id]);

  // --- restyle detections on selection (both overlays, so highlight shows on both sides) ---
  useEffect(() => {
    const onPick = (id: number) => {
      const claimSeqs = indexRef.current?.byDetection.get(id) ?? [];
      dispatch({ type: "selectDetection", claimSeqs, detectionId: id });
    };
    overlayBottom.current?.setProps({
      layers: [detectionLayer(detections, state.highlightedDetections, true, onPick)],
    });
    overlayTop.current?.setProps({
      layers: [detectionLayer(detections, state.highlightedDetections, false, onPick)],
    });
  }, [detections, state.highlightedDetections, dispatch]);

  // --- the swipe: clip the AFTER map from the left ---
  useEffect(() => {
    if (afterRef.current) {
      afterRef.current.style.clipPath = `inset(0 0 0 ${swipe * 100}%)`;
    }
  }, [swipe]);

  // --- ease to the selected claim's evidence ---
  useEffect(() => {
    const b = beforeMap.current;
    if (!b || state.highlightedDetections.length === 0) return;
    const bounds = boundsOf(detections, state.highlightedDetections);
    if (bounds) b.fitBounds(bounds, { padding: 140, duration: 450, maxZoom: 17 });
  }, [state.highlightedDetections, detections]);

  const fill = {
    position: "absolute" as const,
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
  };
  return (
    <div style={{ position: "relative", height: "100%", width: "100%", overflow: "hidden" }}>
      <div ref={beforeRef} style={fill} />
      <div
        ref={afterRef}
        style={{ ...fill, pointerEvents: "none", clipPath: `inset(0 0 0 ${swipe * 100}%)` }}
      />
    </div>
  );
}
