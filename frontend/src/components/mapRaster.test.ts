import { describe, expect, it } from "vitest";
import type { SceneSummary } from "../api/types";
import { type RasterMap, applyRaster } from "./mapRaster";

const SCENE: SceneSummary = {
  id: 18,
  stac_id: "S2A_22JDM_20240521_0_L2A",
  captured_at: "2024-05-21T13:40:46.708000+00:00",
  cloud_pct: 4.09,
  usable_fraction: 0.99,
  bounds: [-51.3, -30.08, -51.18, -29.98],
};

/** A map that records what was done to it and lets a test drive style readiness by hand. */
function fakeMap(styleLoaded = true) {
  const added: string[] = [];
  const layers: string[] = [];
  const idle: (() => void)[] = [];
  let loaded = styleLoaded;
  const map: RasterMap = {
    isStyleLoaded: () => loaded,
    getLayer: () => undefined,
    removeLayer: () => {},
    getSource: () => undefined,
    removeSource: () => {},
    addSource: (id) => void added.push(id),
    addLayer: (layer) => void layers.push(layer.id),
    getStyle: () => ({ layers: [{ id: "place_label", type: "symbol" }] }),
    once: (_type, listener) => void idle.push(listener),
  };
  return {
    map,
    added,
    layers,
    pendingRetries: () => idle.length,
    setStyleLoaded: (v: boolean) => {
      loaded = v;
    },
    goIdle: () => {
      const due = idle.splice(0, idle.length);
      for (const fn of due) fn();
    },
  };
}

describe("applyRaster", () => {
  it("attaches the raster when the style is ready", () => {
    const m = fakeMap(true);
    applyRaster(m.map, "after", SCENE);
    expect(m.added).toEqual(["scene-after"]);
    expect(m.layers).toEqual(["scene-after"]);
  });

  it("attaches the raster once the style becomes ready", () => {
    // THE BUG. Both maps flip their ready flag on maplibre's `load` event, but the after map
    // is also jump-synced to the before map's camera in that same tick. The jump starts new
    // basemap tile loads, so isStyleLoaded() is transiently FALSE exactly when the effect
    // runs. The raster is dropped, and nothing re-fires: the ready flag only flips once and
    // the scene id never changes. Result — the after pane shows bare basemap under the
    // detection polygons until a reload happens to win the race.
    const m = fakeMap(false);
    applyRaster(m.map, "after", SCENE);
    expect(m.added).toEqual([]); // correctly deferred, not thrown

    m.setStyleLoaded(true);
    m.goIdle();
    expect(m.added).toEqual(["scene-after"]);
    expect(m.layers).toEqual(["scene-after"]);
  });

  it("collapses repeated deferred calls into one retry, honouring the latest scene", () => {
    // Scene switches (timeline rail) while the style is busy must not stack listeners, and
    // the retry must attach the scene the user last asked for, not the first one queued.
    const m = fakeMap(false);
    applyRaster(m.map, "after", { ...SCENE, id: 12 });
    applyRaster(m.map, "after", SCENE);
    expect(m.pendingRetries()).toBe(1);

    m.setStyleLoaded(true);
    m.goIdle();
    expect(m.added).toEqual(["scene-after"]);
    expect(m.layers).toEqual(["scene-after"]);
  });

  it("does not leave a stale raster attached when the scene goes null", () => {
    const m = fakeMap(true);
    applyRaster(m.map, "after", null);
    expect(m.added).toEqual([]);
    expect(m.layers).toEqual([]);
  });
});
