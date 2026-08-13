import { ChevronsLeftRight } from "lucide-react";
import type { KeyboardEvent, PointerEvent } from "react";
import { useRef } from "react";
import { monthYear } from "../lib/format";
import { useSelection } from "../state/SelectionContext";

const STEP = 0.02;

/**
 * Draggable before/after split. Keyboard-operable (Arrow keys nudge, Home/End jump), a
 * real slider role, and a 44x44 hit target. The track is pointer-transparent so the map
 * still pans underneath; only the handle captures the pointer.
 */
export function SwipeControl({
  beforeDate,
  afterDate,
}: {
  beforeDate?: string | null;
  afterDate?: string | null;
}) {
  const { state, dispatch } = useSelection();
  const trackRef = useRef<HTMLDivElement>(null);
  const swipe = state.swipe;

  const setFromClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    dispatch({ type: "setSwipe", value: (clientX - r.left) / r.width });
  };

  const onPointerDown = (e: PointerEvent<HTMLButtonElement>) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    setFromClientX(e.clientX);
  };
  const onPointerMove = (e: PointerEvent<HTMLButtonElement>) => {
    if (e.buttons === 1) setFromClientX(e.clientX);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const jump: Record<string, number> = {
      ArrowLeft: swipe - STEP,
      ArrowRight: swipe + STEP,
      Home: 0,
      End: 1,
    };
    if (e.key in jump) {
      dispatch({ type: "setSwipe", value: jump[e.key] });
      e.preventDefault();
    }
  };

  const chip =
    "pointer-events-none absolute top-3 rounded px-2 py-0.5 text-[11px] font-[var(--font-mono)] tracking-wide";
  const chipStyle = {
    background: "color-mix(in oklch, var(--color-surround) 68%, transparent)",
    color: "var(--color-ink-dim)",
  };

  return (
    <div ref={trackRef} className="pointer-events-none absolute inset-0 z-10">
      <span className={`${chip} left-3`} style={chipStyle}>
        BEFORE{beforeDate ? ` · ${monthYear(beforeDate)}` : ""}
      </span>
      <span className={`${chip} right-3`} style={chipStyle}>
        {afterDate ? `${monthYear(afterDate)} · ` : ""}AFTER
      </span>

      <div
        className="absolute inset-y-0"
        style={{ left: `${swipe * 100}%`, transform: "translateX(-50%)" }}
      >
        <div
          className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2"
          style={{ background: "var(--color-ink)", opacity: 0.65 }}
        />
        <button
          type="button"
          role="slider"
          aria-label="Before / after split"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(swipe * 100)}
          aria-valuetext={`${Math.round(swipe * 100)}% after`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onKeyDown={onKeyDown}
          className="pointer-events-auto absolute top-1/2 left-1/2 flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize touch-none items-center justify-center rounded-full shadow-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ink)]"
          style={{
            background: "var(--color-raised)",
            border: "1px solid var(--color-line)",
          }}
        >
          <ChevronsLeftRight size={18} style={{ color: "var(--color-ink-dim)" }} />
        </button>
      </div>
    </div>
  );
}
