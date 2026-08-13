import type * as maplibregl from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAois, useBrief, useDetections, useScenes } from "./api/hooks";
import type { DetectionFeature } from "./api/types";
import { BriefPanel } from "./components/BriefPanel";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { LeaderLine } from "./components/LeaderLine";
import { MapCanvas } from "./components/MapCanvas";
import { SceneTimeline } from "./components/SceneTimeline";
import { SwipeControl } from "./components/SwipeControl";
import { buildEvidenceIndex } from "./evidence";
import {
  CHANGE_COLOR_VAR,
  CHANGE_SHORT,
  MONITOR_LABEL,
  changeTypesPresent,
  findingSummary,
  monthYear,
} from "./lib/format";
import { SelectionProvider, useSelection } from "./state/SelectionContext";

const shortName = (name: string) => name.split(/[,(/]/)[0].trim();

const IS_MAC =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
const KBD_HINT = IS_MAC ? "⌘K" : "Ctrl K";

function Legend({ detections }: { detections: DetectionFeature[] }) {
  const types = changeTypesPresent(detections);
  if (types.length === 0) return null;
  return (
    <div
      className="pointer-events-none absolute bottom-3 left-3 z-10 flex flex-col gap-1 rounded px-3 py-2"
      style={{ background: "color-mix(in oklch, var(--color-surround) 78%, transparent)" }}
    >
      {types.map((t) => (
        <div
          key={t}
          className="flex items-center gap-2 text-[11px]"
          style={{ color: "var(--color-ink-dim)" }}
        >
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
  const [pickedAfterId, setPickedAfterId] = useState<number | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const slug = picked ?? aois?.[0]?.slug ?? null;
  const aoi = aois?.find((a) => a.slug === slug) ?? null;
  const { data: scenes = [] } = useScenes(slug);
  const { data: detections = [] } = useDetections(slug);
  const { data: brief, isLoading: briefLoading } = useBrief(slug);
  const { state, dispatch } = useSelection();
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onMapReady = useCallback((m: maplibregl.Map | null) => {
    mapRef.current = m;
  }, []);

  const before = scenes[0] ?? null;
  const after =
    scenes.find((s) => s.id === pickedAfterId) ??
    (scenes.length > 1 ? scenes[scenes.length - 1] : null);
  const index = useMemo(
    () => (brief ? buildEvidenceIndex(brief, detections) : null),
    [brief, detections],
  );

  // ⌘K / Ctrl-K toggles the palette.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const commands = useMemo<Command[]>(() => {
    const cmds: Command[] = [];
    for (const a of aois ?? [])
      cmds.push({
        id: `aoi-${a.slug}`,
        group: "Areas",
        label: shortName(a.name),
        hint: MONITOR_LABEL[a.vertical] ?? a.vertical,
        run: () => {
          setPicked(a.slug);
          setPickedAfterId(null);
          dispatch({ type: "clear" });
        },
      });
    if (brief)
      for (const c of brief.claims) {
        const ids = index?.byClaim.get(c.seq) ?? [];
        if (ids.length === 0) continue;
        cmds.push({
          id: `claim-${c.seq}`,
          group: "Claims (this area)",
          label: c.text,
          hint: `${ids.length} det`,
          run: () => dispatch({ type: "selectClaim", seq: c.seq, detectionIds: ids }),
        });
      }
    return cmds;
  }, [aois, brief, index, dispatch]);

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
                onClick={() => {
                  setPicked(a.slug);
                  setPickedAfterId(null);
                  dispatch({ type: "clear" });
                }}
                className="rounded px-2.5 py-1 text-xs transition-colors"
                style={{
                  background: active ? "var(--color-raised)" : "transparent",
                  color: active ? "var(--color-ink)" : "var(--color-ink-dim)",
                }}
              >
                {shortName(a.name)}
              </button>
            );
          })}
        </div>

        {aoi && (
          <div className="ml-auto flex items-baseline gap-2 text-xs">
            <span className="font-medium">{monitor}</span>
            <span style={{ color: "var(--color-ink-faint)" }}>·</span>
            <span style={{ color: "var(--color-ink-dim)" }}>{finding}</span>
            {range && (
              <>
                <span style={{ color: "var(--color-ink-faint)" }}>·</span>
                <span
                  className="tnum font-[var(--font-mono)]"
                  style={{ color: "var(--color-ink-dim)" }}
                >
                  {range}
                </span>
              </>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className={aoi ? "" : "ml-auto"}
          style={{ color: "var(--color-ink-faint)" }}
        >
          <kbd
            className="rounded border px-1.5 py-0.5 font-[var(--font-mono)] text-[10px]"
            style={{ borderColor: "var(--color-line)" }}
          >
            {KBD_HINT}
          </kbd>
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1">
            {aoi && (
              <MapCanvas
                aoi={aoi}
                before={before}
                after={after}
                detections={detections}
                index={index}
                swipe={state.swipe}
                onMapReady={onMapReady}
              />
            )}
            <SwipeControl beforeDate={before?.captured_at} afterDate={after?.captured_at} />
            <Legend detections={detections} />
          </div>
          <SceneTimeline
            scenes={scenes}
            beforeId={before?.id ?? null}
            afterId={after?.id ?? null}
            onPickAfter={setPickedAfterId}
          />
        </div>

        <BriefPanel
          brief={brief}
          index={index}
          isLoading={briefLoading}
          scenesReady={scenes.length > 0}
        />
      </div>

      <LeaderLine mapRef={mapRef} detections={detections} />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={commands}
      />
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
