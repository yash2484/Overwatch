import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";

export interface SelectionState {
  selectedClaim: number | null;
  highlightedDetections: number[];
  swipe: number; // 0..1 — before/after split position
}

export type SelectionAction =
  | { type: "selectClaim"; seq: number | null; detectionIds: number[] }
  | { type: "selectDetection"; claimSeqs: number[]; detectionId: number }
  | { type: "clear" }
  | { type: "setSwipe"; value: number };

export const initialSelection: SelectionState = {
  selectedClaim: null,
  highlightedDetections: [],
  swipe: 0.5,
};

export function selectionReducer(
  state: SelectionState,
  action: SelectionAction,
): SelectionState {
  switch (action.type) {
    case "selectClaim":
      // Clicking the selected claim again clears it — a toggle, not a trap.
      if (action.seq !== null && action.seq === state.selectedClaim) {
        return { ...state, selectedClaim: null, highlightedDetections: [] };
      }
      return {
        ...state,
        selectedClaim: action.seq,
        highlightedDetections: action.detectionIds,
      };
    case "selectDetection":
      return {
        ...state,
        selectedClaim: action.claimSeqs[0] ?? null,
        highlightedDetections: [action.detectionId],
      };
    case "clear":
      return { ...state, selectedClaim: null, highlightedDetections: [] };
    case "setSwipe":
      return { ...state, swipe: Math.min(1, Math.max(0, action.value)) };
  }
}

const SelectionContext = createContext<{
  state: SelectionState;
  dispatch: Dispatch<SelectionAction>;
} | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(selectionReducer, initialSelection);
  const value = useMemo(() => ({ state, dispatch }), [state]);
  return (
    <SelectionContext.Provider value={value}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection() {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used inside SelectionProvider");
  return ctx;
}
