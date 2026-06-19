import { useEffect, useMemo, useRef, useState } from "react";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

export function CommandPalette({
  open,
  commands,
  onClose,
}: {
  open: boolean;
  commands: Command[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q) || c.hint?.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // focus after paint
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => { setActive(0); }, [query]);

  if (!open) return null;

  const run = (i: number) => {
    const cmd = filtered[i];
    if (cmd) { onClose(); cmd.run(); }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); run(active); }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/50 pt-[15vh] backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[36rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-line bg-surface-2 text-fg shadow-popover"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a command…"
          className="w-full border-b border-line bg-transparent px-4 py-3 text-sm outline-none placeholder:text-ui-subtle"
        />
        <div className="max-h-80 overflow-y-auto py-1">
          {filtered.length === 0 && <div className="px-4 py-3 text-sm text-ui-subtle">no matches</div>}
          {filtered.map((c, i) => (
            <button
              key={c.id}
              onMouseEnter={() => setActive(i)}
              onClick={() => run(i)}
              className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm ${
                i === active ? "bg-control-hover text-ui-strong" : "text-ui"
              }`}
            >
              <span>{c.label}</span>
              {c.hint && <span className="text-xs text-ui-subtle">{c.hint}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
