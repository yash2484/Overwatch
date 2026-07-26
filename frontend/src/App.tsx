import { useState } from "react";
import { useAois, useDetections, useScenes } from "./api/hooks";
import { MapCanvas } from "./components/MapCanvas";
import { SwipeControl } from "./components/SwipeControl";
import {
  CHANGE_COLOR_VAR,
  CHANGE_SHORT,
  MONITOR_LABEL,
  changeTypesPresent,
  findingSummary,
  monthYear,
} from "./lib/format";
import { SelectionProvider, useSelection } from "./state/SelectionContext";
import type { DetectionFeature } from "./api/types";

function Legend({ detections }: { detections: DetectionFeature[] }) {
  const types = changeTypesPresent(detections);
  if (types.length === 0) return null;
  return (
    <div
      className="pointer-events-none absolute bottom-3 left-3 z-10 flex flex-col gap-1 rounded px-3 py-2"
      style={{ background: "color-mix(in oklch, var(--color-surround) 78%, transparent)" }}
    >
      {types.map((t) => (
        <div key={t} className="flex items-center gap-2 text-[11px]" style={{ color: "var(--color-ink-dim)" }}>
          <span
            className="inline-block h-2.5 w-2.5 rounded-[2px]"
            style={{ background: CHANGE_COLOR_VAR[t] ?? "var(--color-ink-dim)" }}
          />
          <span>{CHANGE_SHORT[t] ?? t.replace(/_/g, " ")}</span>
        </div>
      ))}
    </div>
  );
}

function Console() {
  const { data: aois } = useAois();
  const [picked, setPicked] = useState<string | null>(null);
  const slug = picked ?? aois?.[0]?.slug ?? null;
  const aoi = aois?.find((a) => a.slug === slug) ?? null;
  const { data: scenes = [] } = useScenes(slug);
  const { data: detections = [] } = useDetections(slug);
  const { state } = useSelection();

  const before = scenes[0] ?? null;
  const after = scenes.length > 1 ? scenes[scenes.length - 1] : null;
  const finding = findingSummary(detections);
  const monitor = aoi ? (MONITOR_LABEL[aoi.vertical] ?? aoi.vertical) : "";
  const range =
    before && after ? `${monthYear(before.captured_at)} → ${monthYear(after.captured_at)}` : "";

  return (
    <div className="flex h-full flex-col">
      <header
        className="flex items-center gap-5 border-b px-4 py-2.5"
        style={{ background: "var(--color-panel)", borderColor: "var(--color-line)" }}
      >
        <span className="text-sm font-semibold tracking-tight">Overwatch</span>
        <div className="flex gap-1">
          {aois?.map((a) => {
            const active = a.slug === slug;
            return (
              <button
                key={a.slug}
                type="button"
                onClick={() => setPicked(a.slug)}
                className="rounded px-2.5 py-1 text-xs transition-colors"
                style={{
                  background: active ? "var(--color-raised)" : "transparent",
                  color: active ? "var(--color-ink)" : "var(--color-ink-dim)",
                }}
              >
                {a.name.split(/[,(/]/)[0].trim()}
              </button>
            );
          })}
        </div>

        {/* The comprehension line: what is monitored, the finding, the time span. */}
        {aoi && (
          <div className="ml-auto flex items-baseline gap-2 text-xs">
            <span className="font-medium">{monitor}</span>
            <span style={{ color: "var(--color-ink-dim)" }}>·</span>
            <span style={{ color: "var(--color-ink-dim)" }}>{finding}</span>
            {range && (
              <>
                <span style={{ color: "var(--color-ink-dim)" }}>·</span>
                <span className="tnum font-[var(--font-mono)]" style={{ color: "var(--color-ink-dim)" }}>
                  {range}
                </span>
              </>
            )}
          </div>
        )}
      </header>

      <div className="relative flex-1">
        {aoi && (
          <MapCanvas
            aoi={aoi}
            before={before}
            after={after}
            detections={detections}
            index={null}
            swipe={state.swipe}
          />
        )}
        <SwipeControl beforeDate={before?.captured_at} afterDate={after?.captured_at} />
        <Legend detections={detections} />
      </div>
    </div>
  );
}

export function App() {
  return (
    <SelectionProvider>
      <Console />
    </SelectionProvider>
  );
}
