import { AlertTriangle, FileText, Link2, Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";
import type { Brief } from "../api/types";
import type { EvidenceIndex } from "../evidence";
import { useSelection } from "../state/SelectionContext";

const CITE_TYPES = new Set(["observed", "reported", "mixed"]);

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <aside
      className="flex h-full w-[380px] shrink-0 flex-col overflow-hidden border-l"
      style={{ background: "var(--color-panel)", borderColor: "var(--color-line)" }}
    >
      {children}
    </aside>
  );
}

function PanelHeader({ label, demo }: { label: string; demo?: boolean }) {
  return (
    <div className="flex items-center gap-2 px-4 pt-3.5 pb-2">
      <FileText size={13} style={{ color: "var(--color-ink-faint)" }} />
      <span
        className="font-[var(--font-mono)] text-[11px] tracking-[0.14em]"
        style={{ color: "var(--color-ink-faint)" }}
      >
        {label}
      </span>
      {demo && (
        <span
          className="ml-auto rounded px-1.5 py-0.5 font-[var(--font-mono)] text-[10px] tracking-wide"
          style={{ background: "var(--color-raised)", color: "var(--color-ink-dim)" }}
          title="Hand-authored, data-grounded brief. Real LLM briefs require the Anthropic key."
        >
          DEMO
        </span>
      )}
    </div>
  );
}

function Empty({ message, sub }: { message: string; sub: string }) {
  return (
    <Shell>
      <PanelHeader label="INTELLIGENCE BRIEF" />
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-8 text-center">
        <FileText size={22} style={{ color: "var(--color-ink-faint)" }} />
        <p className="text-sm" style={{ color: "var(--color-ink-dim)" }}>
          {message}
        </p>
        <p className="text-xs" style={{ color: "var(--color-ink-faint)" }}>
          {sub}
        </p>
      </div>
    </Shell>
  );
}

export function BriefPanel({
  brief,
  index,
  isLoading,
  scenesReady,
}: {
  brief: Brief | undefined;
  index: EvidenceIndex | null;
  isLoading: boolean;
  scenesReady: boolean;
}) {
  const { state, dispatch } = useSelection();
  const listRef = useRef<HTMLDivElement>(null);

  // When a detection click selects a claim, scroll that claim into view.
  useEffect(() => {
    if (state.selectedClaim === null || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-claim-seq="${state.selectedClaim}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [state.selectedClaim]);

  if (isLoading || !scenesReady) {
    return (
      <Shell>
        <PanelHeader label="INTELLIGENCE BRIEF" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 size={18} className="animate-spin" style={{ color: "var(--color-ink-faint)" }} />
        </div>
      </Shell>
    );
  }

  if (!brief) {
    return (
      <Empty
        message="No brief for this area yet"
        sub="Run change detection, then generate a brief to see the narrative and evidence here."
      />
    );
  }

  if (brief.status === "generating") {
    return (
      <Shell>
        <PanelHeader label="INTELLIGENCE BRIEF" />
        <div className="flex flex-1 flex-col items-center justify-center gap-2">
          <Loader2 size={18} className="animate-spin" style={{ color: "var(--color-ink-dim)" }} />
          <p className="text-xs" style={{ color: "var(--color-ink-dim)" }}>
            Generating brief…
          </p>
        </div>
      </Shell>
    );
  }

  if (brief.status === "rejected" || brief.status === "failed") {
    const violations = (brief.violations ?? []) as Array<Record<string, unknown>>;
    return (
      <Shell>
        <PanelHeader label="INTELLIGENCE BRIEF" />
        <div className="flex items-start gap-2 px-4 py-3">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" style={{ color: "var(--color-change-clearing)" }} />
          <div>
            <p className="text-sm font-medium">Brief withheld</p>
            <p className="mt-0.5 text-xs" style={{ color: "var(--color-ink-dim)" }}>
              The draft failed validation and was not published — the evidence gate rejected it.
            </p>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-4 pb-4">
          {violations.map((v, i) => (
            <div
              key={i}
              className="mt-2 rounded p-2.5 text-xs"
              style={{ background: "var(--color-raised)", color: "var(--color-ink-dim)" }}
            >
              <span className="font-[var(--font-mono)]" style={{ color: "var(--color-ink)" }}>
                {String(v.code ?? v.rule ?? "violation")}
              </span>
              {v.detail ? ` — ${String(v.detail)}` : ""}
            </div>
          ))}
        </div>
      </Shell>
    );
  }

  // validated | stale
  const stale = brief.status === "stale";
  return (
    <Shell>
      <PanelHeader label="INTELLIGENCE BRIEF" demo={brief.model === "demo-seed"} />

      {stale && (
        <div
          className="mx-4 mb-2 flex items-center gap-2 rounded px-2.5 py-1.5 text-xs"
          style={{ background: "var(--color-raised)", color: "var(--color-ink-dim)" }}
        >
          <AlertTriangle size={13} style={{ color: "var(--color-change-construction)" }} />
          Superseded — the imagery was re-analysed after this brief.
        </div>
      )}

      <div className="px-4 pb-3">
        <h1
          className="text-[15px] leading-snug font-semibold text-balance"
          style={{ color: stale ? "var(--color-ink-dim)" : "var(--color-ink)" }}
        >
          {brief.headline}
        </h1>
      </div>

      <div
        className="mx-4 mb-1 border-t pt-2 font-[var(--font-mono)] text-[11px]"
        style={{ borderColor: "var(--color-line)", color: "var(--color-ink-faint)" }}
      >
        {brief.claims.length} claims · click a claim to see its evidence on the map
      </div>

      <div ref={listRef} className="flex-1 overflow-y-auto px-2 py-2">
        {brief.claims.map((claim) => {
          const ids = index?.byClaim.get(claim.seq) ?? [];
          const citable = CITE_TYPES.has(claim.claim_type) && ids.length > 0;
          const selected = state.selectedClaim === claim.seq;
          return (
            <button
              key={claim.seq}
              type="button"
              data-claim-seq={claim.seq}
              disabled={!citable}
              onClick={() => dispatch({ type: "selectClaim", seq: claim.seq, detectionIds: ids })}
              className="mb-1 flex w-full gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors"
              style={{
                background: selected
                  ? "color-mix(in oklch, var(--color-evidence) 15%, var(--color-panel))"
                  : "transparent",
                cursor: citable ? "pointer" : "default",
              }}
            >
              <span
                className="mt-0.5 font-[var(--font-mono)] text-[11px] tabular-nums"
                style={{ color: selected ? "var(--color-evidence)" : "var(--color-ink-faint)" }}
              >
                {String(claim.seq + 1).padStart(2, "0")}
              </span>
              <span className="flex-1">
                <span
                  className="text-[13px] leading-relaxed"
                  style={{ color: citable ? "var(--color-ink)" : "var(--color-ink-dim)" }}
                >
                  {claim.text}
                </span>
                {citable && (
                  <span
                    className="mt-1 flex items-center gap-1 font-[var(--font-mono)] text-[10.5px]"
                    style={{
                      color: selected ? "var(--color-evidence)" : "var(--color-ink-faint)",
                    }}
                  >
                    <Link2 size={11} />
                    {ids.length} detection{ids.length === 1 ? "" : "s"}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <div
        className="border-t px-4 py-2 font-[var(--font-mono)] text-[10.5px]"
        style={{ borderColor: "var(--color-line)", color: "var(--color-ink-faint)" }}
      >
        Evidence: every observed claim links to detections stored in PostGIS.
      </div>
    </Shell>
  );
}
