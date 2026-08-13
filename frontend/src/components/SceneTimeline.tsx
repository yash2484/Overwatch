import type { SceneSummary } from "../api/types";

const MS_DAY = 86_400_000;

/**
 * Horizontal scene chronology. Shows every ingested scene positioned by capture date, with
 * the compared before/after pair filled and connected. Clicking a scene swaps the after
 * imagery so a viewer can explore the series — detections stay pinned to the analysed pair.
 */
export function SceneTimeline({
  scenes,
  beforeId,
  afterId,
  onPickAfter,
}: {
  scenes: SceneSummary[];
  beforeId: number | null;
  afterId: number | null;
  onPickAfter: (id: number) => void;
}) {
  if (scenes.length === 0) return null;
  const times = scenes.map((s) => new Date(s.captured_at).getTime());
  const min = Math.min(...times);
  const max = Math.max(...times);
  const span = Math.max(max - min, MS_DAY);
  const spanDays = Math.round((max - min) / MS_DAY);
  const pos = (t: number) => (span === 0 ? 50 : ((t - min) / span) * 100);

  const bT = beforeId != null ? times[scenes.findIndex((s) => s.id === beforeId)] : null;
  const aT = afterId != null ? times[scenes.findIndex((s) => s.id === afterId)] : null;

  return (
    <div
      className="flex h-[76px] shrink-0 items-stretch gap-3 border-t px-4"
      style={{ background: "var(--color-panel)", borderColor: "var(--color-line)" }}
    >
      <div className="flex w-24 shrink-0 flex-col justify-center">
        <span
          className="font-[var(--font-mono)] text-[10px] tracking-[0.14em]"
          style={{ color: "var(--color-ink-faint)" }}
        >
          SCENES
        </span>
        <span className="text-[11px]" style={{ color: "var(--color-ink-dim)" }}>
          {scenes.length} over {spanDays >= 365 ? `${(spanDays / 365).toFixed(1)} yr` : `${spanDays} d`}
        </span>
      </div>

      <div className="relative flex-1">
        {/* baseline */}
        <div
          className="absolute top-1/2 right-0 left-0 h-px"
          style={{ background: "var(--color-line)" }}
        />
        {/* the compared span */}
        {bT != null && aT != null && (
          <div
            className="absolute top-1/2 h-px"
            style={{
              left: `${Math.min(pos(bT), pos(aT))}%`,
              width: `${Math.abs(pos(aT) - pos(bT))}%`,
              background: "var(--color-ink-dim)",
            }}
          />
        )}
        {scenes.map((s) => {
          const t = new Date(s.captured_at).getTime();
          const inPair = s.id === beforeId || s.id === afterId;
          const isAfter = s.id === afterId;
          const label = new Date(s.captured_at).toLocaleDateString("en-US", {
            month: "short",
            year: "2-digit",
          });
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => onPickAfter(s.id)}
              title={`${s.stac_id} · ${s.cloud_pct.toFixed(0)}% cloud`}
              className="group absolute top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
              style={{ left: `${pos(t)}%` }}
            >
              <span
                className="rounded-full transition-all"
                style={{
                  width: inPair ? 11 : 8,
                  height: inPair ? 11 : 8,
                  background: inPair ? "var(--color-ink)" : "var(--color-surround)",
                  border: `1.5px solid ${inPair ? "var(--color-ink)" : "var(--color-line)"}`,
                  boxShadow: isAfter ? "0 0 0 3px color-mix(in oklch, var(--color-ink) 22%, transparent)" : "none",
                }}
              />
              <span
                className="absolute top-4 font-[var(--font-mono)] text-[10px] whitespace-nowrap"
                style={{ color: inPair ? "var(--color-ink-dim)" : "var(--color-ink-faint)" }}
              >
                {label}
                {inPair && (
                  <span className="ml-1" style={{ color: "var(--color-ink-faint)" }}>
                    {s.id === beforeId ? "before" : "after"}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
