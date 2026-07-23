import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export type SelectOption = { value: string; label: string; hint?: string; disabled?: boolean };

export function Select({
  value,
  options,
  onChange,
  placeholder = "select...",
  className = "",
  optionsClassName = "max-h-56",
  renderOption,
  id,
  ariaLabel,
  ariaLabelledBy,
  disabled = false,
}: {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  optionsClassName?: string;
  // Optional rich renderer for the option body (the row keeps its selection
  // highlight, keyboard nav and click handling). Falls back to label + hint.
  renderOption?: (option: SelectOption) => ReactNode;
  id?: string;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const generatedId = useId();
  const triggerId = id ?? `select-${generatedId}`;
  const listboxId = `${triggerId}-listbox`;
  const optionId = (index: number) => `${triggerId}-option-${index}`;
  const selected = options.find((o) => o.value === value);
  const searchable = options.length > 6;
  const filteredOptions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(q));
  }, [options, query]);

  useEffect(() => {
    if (!open) return;
    const selectedIndex = filteredOptions.findIndex((o) => o.value === value && !o.disabled);
    const firstEnabled = filteredOptions.findIndex((o) => !o.disabled);
    setActive(selectedIndex >= 0 ? selectedIndex : firstEnabled);
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [filteredOptions, open, value]);

  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }
    if (searchable) requestAnimationFrame(() => searchRef.current?.focus());
  }, [open, searchable]);

  const choose = (i: number) => {
    const opt = filteredOptions[i];
    if (!opt || opt.disabled) return;
    onChange(opt.value);
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const step = (dir: 1 | -1) => {
    setActive((cur) => {
      let i = cur;
      for (let n = 0; n < filteredOptions.length; n++) {
        i = (i + dir + filteredOptions.length) % filteredOptions.length;
        if (!filteredOptions[i]?.disabled) return i;
      }
      return cur;
    });
  };

  const jump = (edge: "first" | "last") => {
    const sequence = edge === "first"
      ? filteredOptions.keys()
      : Array.from(filteredOptions.keys()).reverse();
    for (const index of sequence) {
      if (!filteredOptions[index]?.disabled) {
        setActive(index);
        break;
      }
    }
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        jump("first");
      }
      else step(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (open) step(-1);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (open) choose(active);
      else setOpen(true);
    } else if (e.key === "Escape") {
      setOpen(false);
    } else if (e.key === "Home" && open) {
      e.preventDefault();
      jump("first");
    } else if (e.key === "End" && open) {
      e.preventDefault();
      jump("last");
    }
  };

  const onSearchKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      step(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      step(-1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(active);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      requestAnimationFrame(() => triggerRef.current?.focus());
    } else if (e.key === "Home") {
      e.preventDefault();
      jump("first");
    } else if (e.key === "End") {
      e.preventDefault();
      jump("last");
    }
  };

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        role="combobox"
        aria-label={ariaLabel ?? (ariaLabelledBy ? undefined : placeholder)}
        aria-labelledby={ariaLabelledBy}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onKeyDown}
        className="ui-field flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-sm"
      >
        <span className={`min-w-0 truncate ${selected ? "text-fg" : "text-ui-subtle"}`}>
          {selected ? selected.label : placeholder}
        </span>
        <svg
          className={`h-3.5 w-3.5 shrink-0 text-ui-subtle transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-md border border-line bg-surface-2 shadow-popover">
          {searchable ? (
            <div className="border-b border-line p-1.5">
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                onKeyDown={onSearchKeyDown}
                placeholder="search..."
                aria-label={`Filter ${ariaLabel ?? placeholder} options`}
                aria-controls={listboxId}
                aria-activedescendant={active >= 0 ? optionId(active) : undefined}
                className="ui-field w-full rounded px-2 py-1 text-xs"
              />
            </div>
          ) : null}
          <div
            id={listboxId}
            role="listbox"
            aria-label={`${ariaLabel ?? placeholder} options`}
            data-testid="select-options"
            className={`${optionsClassName} overflow-y-auto py-1`}
          >
            {filteredOptions.length === 0 ? <div className="px-2.5 py-1.5 text-sm text-ui-subtle">no options</div> : null}
            {filteredOptions.map((o, i) => (
              <button
                id={optionId(i)}
                key={o.value || `opt-${i}`}
                type="button"
                role="option"
                aria-selected={o.value === value}
                disabled={o.disabled}
                onClick={() => choose(i)}
                onMouseEnter={() => setActive(i)}
                className={`flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-sm disabled:cursor-not-allowed disabled:opacity-30 ${
                  o.value === value
                    ? "bg-accent/15 text-accent-fg"
                    : i === active
                      ? "bg-control-hover text-ui-strong"
                      : "text-ui"
                }`}
              >
                {renderOption ? (
                  renderOption(o)
                ) : (
                  <>
                    <span className="min-w-0 truncate">{o.label}</span>
                    {o.hint ? <span className="shrink-0 text-[11px] text-ui-subtle">{o.hint}</span> : null}
                  </>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
