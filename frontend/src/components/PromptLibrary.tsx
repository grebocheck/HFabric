import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { toast } from "./Toast";
import type { PromptSnippet } from "../types";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

// Prompt library (P19.4): browse / save / insert reusable image-prompt snippets.
// Opened from the image composer; applies a snippet's body (+ negative) back into
// the composer fields. Export/import as JSON for sharing between machines.
export function PromptLibrary({
  open,
  onClose,
  currentPrompt,
  currentNegative,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  currentPrompt: string;
  currentNegative: string;
  onApply: (body: string, negative: string | null) => void;
}) {
  const [items, setItems] = useState<PromptSnippet[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await api.listPrompts());
    } catch {
      /* keep last known list if the backend blips */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const q = query.trim().toLowerCase();
  const visible = q
    ? items.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.body.toLowerCase().includes(q) ||
          s.tags.some((t) => t.toLowerCase().includes(q)),
      )
    : items;

  const saveCurrent = async () => {
    if (!currentPrompt.trim()) return;
    setBusy(true);
    try {
      await api.createPrompt({ body: currentPrompt, negative: currentNegative || null });
      toast.success("Saved to prompt library");
      setQuery("");
      await refresh();
    } catch (err) {
      toast.error(errMsg(err, "Could not save prompt"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await api.deletePrompt(id);
      setItems((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      toast.error(errMsg(err, "Could not delete"));
    }
  };

  const apply = (s: PromptSnippet) => {
    onApply(s.body, s.negative);
    onClose();
  };

  const exportAll = () => {
    const payload = {
      prompts: items.map((s) => ({ name: s.name, body: s.body, negative: s.negative, tags: s.tags })),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "hfabric-prompts.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const importFile = async (file: File) => {
    setBusy(true);
    try {
      const data = JSON.parse(await file.text());
      const prompts = Array.isArray(data) ? data : data?.prompts;
      if (!Array.isArray(prompts)) throw new Error("expected a prompts array");
      const res = await api.importPrompts(prompts);
      toast.success(`Imported ${res.imported} prompt(s)`);
      await refresh();
    } catch (err) {
      toast.error(errMsg(err, "Import failed — not a valid prompt export"));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const toolbarButton =
    "ui-button rounded-md px-2.5 py-1 text-xs disabled:opacity-30";

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label="Prompt library"
        className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-line bg-surface-2 shadow-popover"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ui-strong">Prompt library</h2>
          <button onClick={onClose} className={toolbarButton} aria-label="Close prompt library">
            Close
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name, text, or tag…"
            className="ui-field min-w-40 flex-1 rounded-md px-2.5 py-1 text-sm"
          />
          <button onClick={() => void saveCurrent()} className={toolbarButton} disabled={busy || !currentPrompt.trim()}>
            Save current
          </button>
          <button onClick={exportAll} className={toolbarButton} disabled={items.length === 0}>
            Export
          </button>
          <button onClick={() => fileRef.current?.click()} className={toolbarButton} disabled={busy}>
            Import
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void importFile(file);
            }}
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {loading && items.length === 0 ? (
            <div className="px-2 py-6 text-center text-sm text-ui-subtle">Loading...</div>
          ) : visible.length === 0 ? (
            <div className="px-2 py-6 text-center text-sm text-ui-subtle">
              {items.length === 0
                ? "No saved prompts yet. Write a prompt in the composer, then “Save current”."
                : "No prompts match your search."}
            </div>
          ) : (
            <ul className="space-y-1.5">
              {visible.map((s) => (
                <li key={s.id} className="rounded-md border border-line bg-control px-3 py-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-sm text-ui-strong">{s.name}</span>
                        {s.tags.map((t) => (
                          <span key={t} className="rounded border border-line bg-raised px-1.5 py-0.5 text-[10px] text-ui-subtle">
                            {t}
                          </span>
                        ))}
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-[12px] text-ui-subtle">{s.body}</p>
                      {s.negative ? (
                        <p className="mt-0.5 text-[11px] text-ui-subtle">negative: {s.negative}</p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <button
                        onClick={() => apply(s)}
                        className="rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-ui-inverse transition hover:bg-accent-hover"
                      >
                        Insert
                      </button>
                      <button
                        onClick={() => void remove(s.id)}
                        className="rounded-md border border-error-border px-2 py-1 text-xs text-error-fg transition hover:bg-error-bg"
                        aria-label={`Delete ${s.name}`}
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
