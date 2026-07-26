import { useState } from "react";
import { useAois, useDetections, useScenes } from "./api/hooks";
import { MapCanvas } from "./components/MapCanvas";
import { SwipeControl } from "./components/SwipeControl";
import { SelectionProvider, useSelection } from "./state/SelectionContext";

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

  return (
    <div className="flex h-full flex-col">
      <header
        className="flex items-center gap-4 border-b px-4 py-2.5"
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
                {a.name}
              </button>
            );
          })}
        </div>
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
        <SwipeControl />
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
