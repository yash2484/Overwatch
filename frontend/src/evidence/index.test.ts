import { describe, expect, it } from "vitest";
import { boundsOf, buildEvidenceIndex } from "./index";
import type { Brief, DetectionFeature } from "../api/types";

const detection = (id: number, x = 0, y = 0): DetectionFeature => ({
  type: "Feature",
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [x, y],
        [x + 1, y],
        [x + 1, y + 1],
        [x, y + 1],
        [x, y],
      ],
    ],
  },
  properties: {
    id,
    change_type: "construction",
    area_m2: 1000,
    magnitude: 0.4,
    confidence: 0.8,
    job_id: "j",
    before_scene_id: 1,
    after_scene_id: 2,
    contributing_indices: {},
    src_epsg: 32643,
    created_at: "2024-01-01T00:00:00Z",
  },
});

const brief = (claims: Brief["claims"]): Brief => ({
  id: 1,
  aoi_slug: "vizhinjam",
  status: "validated",
  attempts: 1,
  headline: "h",
  model: "m",
  usage: {},
  violations: null,
  error: null,
  before_scene_id: 1,
  after_scene_id: 2,
  claims,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
});

describe("buildEvidenceIndex", () => {
  it("maps a claim to the detections that back it", () => {
    const idx = buildEvidenceIndex(
      brief([
        { seq: 0, text: "a", claim_type: "observed", detection_ids: [10, 11] },
      ]),
      [detection(10), detection(11)],
    );
    expect(idx.byClaim.get(0)).toEqual([10, 11]);
  });

  it("maps a detection back to every claim citing it — the reverse join", () => {
    const idx = buildEvidenceIndex(
      brief([
        { seq: 0, text: "a", claim_type: "observed", detection_ids: [10] },
        { seq: 1, text: "b", claim_type: "observed", detection_ids: [10, 11] },
      ]),
      [detection(10), detection(11)],
    );
    expect(idx.byDetection.get(10)).toEqual([0, 1]);
    expect(idx.byDetection.get(11)).toEqual([1]);
  });

  it("drops evidence ids with no matching detection rather than inventing one", () => {
    // A stale brief can cite a detection that has since been replaced. The UI must not
    // crash, and must not silently pretend the id exists.
    const idx = buildEvidenceIndex(
      brief([
        { seq: 0, text: "a", claim_type: "observed", detection_ids: [10, 999] },
      ]),
      [detection(10)],
    );
    expect(idx.byClaim.get(0)).toEqual([10]);
    expect(idx.byDetection.has(999)).toBe(false);
  });

  it("gives a context claim an empty list, not undefined", () => {
    const idx = buildEvidenceIndex(
      brief([
        { seq: 0, text: "background", claim_type: "context", detection_ids: [] },
      ]),
      [detection(10)],
    );
    expect(idx.byClaim.get(0)).toEqual([]);
  });

  it("handles an empty brief and empty detections", () => {
    const idx = buildEvidenceIndex(brief([]), []);
    expect(idx.byClaim.size).toBe(0);
    expect(idx.byDetection.size).toBe(0);
  });

  it("preserves claim citation order in the reverse map", () => {
    // seq 2 cites the detection before seq 0 does; byDetection must reflect claim
    // iteration order, not id order, so the panel highlights claims predictably.
    const idx = buildEvidenceIndex(
      brief([
        { seq: 2, text: "c", claim_type: "observed", detection_ids: [10] },
        { seq: 0, text: "a", claim_type: "observed", detection_ids: [10] },
      ]),
      [detection(10)],
    );
    expect(idx.byDetection.get(10)).toEqual([2, 0]);
  });
});

describe("boundsOf", () => {
  it("unions the bounds of the given detections", () => {
    expect(
      boundsOf([detection(10, 0, 0), detection(11, 5, 5)], [10, 11]),
    ).toEqual([0, 0, 6, 6]);
  });

  it("returns null when nothing is selected, so the map does not fly to NaN", () => {
    expect(boundsOf([detection(10)], [])).toBeNull();
    expect(boundsOf([detection(10)], [999])).toBeNull();
  });
});
