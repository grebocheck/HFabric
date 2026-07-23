import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog } from "./Dialog";

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
    }
  }, [open]);

  useEffect(() => { setActive(0); }, [query]);

  if (!open) return null;

  const run = (i: number) => {
    const cmd = filtered[i];
    if (cmd) { onClose(); cmd.run(); }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); run(active); }
  };

  return (
    <Dialog
      open
      title="Command palette"
      onClose={onClose}
      initialFocusRef={inputRef}
      overlayClassName="items-start pt-[max(1rem,15dvh)]"
      panelClassName="flex w-full max-w-xl flex-col bg-surface-2 text-fg"
      titleClassName="sr-only"
    >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a command…"
          aria-label="Search commands"
          aria-controls="command-palette-options"
          aria-activedescendant={filtered[active] ? `command-${filtered[active].id}` : undefined}
          className="w-full border-b border-line bg-transparent px-4 py-3 text-sm outline-none placeholder:text-ui-subtle"
        />
        <div
          id="command-palette-options"
          role="listbox"
          aria-label="Command results"
          className="min-h-0 max-h-[min(20rem,calc(100dvh-8rem))] overflow-y-auto py-1"
        >
          {filtered.length === 0 && <div className="px-4 py-3 text-sm text-ui-subtle">no matches</div>}
          {filtered.map((c, i) => (
            <button
              id={`command-${c.id}`}
              key={c.id}
              role="option"
              aria-selected={i === active}
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
    </Dialog>
  );
}
