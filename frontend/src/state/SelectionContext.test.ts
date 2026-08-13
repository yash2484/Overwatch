import { describe, expect, it } from "vitest";
import { initialSelection, selectionReducer } from "./SelectionContext";

describe("selectionReducer", () => {
  it("selecting a claim highlights exactly its detections", () => {
    const s = selectionReducer(initialSelection, {
      type: "selectClaim",
      seq: 0,
      detectionIds: [10, 11],
    });
    expect(s.selectedClaim).toBe(0);
    expect(s.highlightedDetections).toEqual([10, 11]);
  });

  it("re-selecting the same claim is a toggle, not a trap", () => {
    const selected = selectionReducer(initialSelection, {
      type: "selectClaim",
      seq: 0,
      detectionIds: [10, 11],
    });
    const toggled = selectionReducer(selected, {
      type: "selectClaim",
      seq: 0,
      detectionIds: [10, 11],
    });
    expect(toggled.selectedClaim).toBeNull();
    expect(toggled.highlightedDetections).toEqual([]);
  });

  it("selecting a detection highlights it and adopts the first citing claim", () => {
    const s = selectionReducer(initialSelection, {
      type: "selectDetection",
      claimSeqs: [3, 5],
      detectionId: 10,
    });
    expect(s.highlightedDetections).toEqual([10]);
    expect(s.selectedClaim).toBe(3);
  });

  it("selecting an uncited detection highlights it with no claim", () => {
    const s = selectionReducer(initialSelection, {
      type: "selectDetection",
      claimSeqs: [],
      detectionId: 10,
    });
    expect(s.highlightedDetections).toEqual([10]);
    expect(s.selectedClaim).toBeNull();
  });

  it("clear resets selection but leaves the swipe alone", () => {
    const dragged = selectionReducer(initialSelection, {
      type: "setSwipe",
      value: 0.3,
    });
    const selected = selectionReducer(dragged, {
      type: "selectClaim",
      seq: 1,
      detectionIds: [7],
    });
    const cleared = selectionReducer(selected, { type: "clear" });
    expect(cleared.selectedClaim).toBeNull();
    expect(cleared.highlightedDetections).toEqual([]);
    expect(cleared.swipe).toBe(0.3);
  });

  it("setSwipe clamps into [0, 1] so the split never leaves the map", () => {
    expect(selectionReducer(initialSelection, { type: "setSwipe", value: 1.5 }).swipe).toBe(1);
    expect(selectionReducer(initialSelection, { type: "setSwipe", value: -0.2 }).swipe).toBe(0);
    expect(selectionReducer(initialSelection, { type: "setSwipe", value: 0.42 }).swipe).toBe(0.42);
  });
});
