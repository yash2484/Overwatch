import { CornerDownLeft, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

export interface Command {
  id: string;
  label: string;
  group: string;
  hint?: string;
  run: () => void;
}

/**
 * ⌘K / Ctrl-K navigation. Read-only: it jumps between areas and lights up claims — it never
 * triggers pipeline work. Native focus handling, arrow-key nav, Enter to run, Esc to close.
 */
export function CommandPalette({
  open,
  onClose,
  commands,
}: {
  open: boolean;
  onClose: () => void;
  commands: Command[];
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // focus after paint so the dialog is mounted
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  if (!open) return null;

  const run = (c: Command | undefined) => {
    if (!c) return;
    c.run();
    onClose();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(filtered[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  // Preserve group order as first-seen in the filtered list.
  const groups: string[] = [];
  for (const c of filtered) if (!groups.includes(c.group)) groups.push(c.group);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[14vh]"
      style={{ background: "color-mix(in oklch, var(--color-surround) 55%, transparent)" }}
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-label="Command palette"
        className="w-[560px] max-w-[92vw] overflow-hidden rounded-xl border shadow-2xl"
        style={{ background: "var(--color-panel)", borderColor: "var(--color-line)" }}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div
          className="flex items-center gap-2.5 border-b px-3.5 py-3"
          style={{ borderColor: "var(--color-line)" }}
        >
          <Search size={15} style={{ color: "var(--color-ink-faint)" }} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Jump to an area or a claim…"
            className="flex-1 bg-transparent text-sm outline-none"
            style={{ color: "var(--color-ink)" }}
          />
          <kbd
            className="rounded px-1.5 py-0.5 font-[var(--font-mono)] text-[10px]"
            style={{ background: "var(--color-raised)", color: "var(--color-ink-faint)" }}
          >
            ESC
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[52vh] overflow-y-auto py-1.5">
          {filtered.length === 0 && (
            <div className="px-4 py-6 text-center text-sm" style={{ color: "var(--color-ink-faint)" }}>
              No matches
            </div>
          )}
          {groups.map((group) => (
            <div key={group} className="mb-1">
              <div
                className="px-3.5 pt-1.5 pb-1 font-[var(--font-mono)] text-[10px] tracking-[0.12em]"
                style={{ color: "var(--color-ink-faint)" }}
              >
                {group.toUpperCase()}
              </div>
              {filtered
                .filter((c) => c.group === group)
                .map((c) => {
                  const idx = filtered.indexOf(c);
                  const on = idx === active;
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onMouseEnter={() => setActive(idx)}
                      onClick={() => run(c)}
                      className="flex w-full items-center gap-2 px-3.5 py-2 text-left text-[13px]"
                      style={{
                        background: on ? "var(--color-raised)" : "transparent",
                        color: on ? "var(--color-ink)" : "var(--color-ink-dim)",
                      }}
                    >
                      <span className="flex-1 truncate">{c.label}</span>
                      {c.hint && (
                        <span
                          className="font-[var(--font-mono)] text-[10px]"
                          style={{ color: "var(--color-ink-faint)" }}
                        >
                          {c.hint}
                        </span>
                      )}
                      {on && <CornerDownLeft size={12} style={{ color: "var(--color-ink-faint)" }} />}
                    </button>
                  );
                })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
