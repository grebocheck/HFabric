import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { EmptyState, Panel, SectionTitle, StatusPill, WorkspaceHeader } from "./WorkspaceChrome";
import type { Note } from "../types";

const field = "ui-field w-full rounded-md px-2.5 py-1.5 text-sm";

function fmt(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function excerpt(text: string): string {
  return text.replace(/\s+/g, " ").trim().slice(0, 90);
}

export function NotesPanel() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const loadedId = useRef<string | null>(null);

  const active = useMemo(
    () => notes.find((n) => n.id === activeId) ?? null,
    [notes, activeId],
  );

  const refresh = useCallback((q = query) => {
    api.listNotes(q).then((rows) => {
      setNotes(rows);
      if (!activeId && rows[0]) setActiveId(rows[0].id);
    }).catch(() => {});
  }, [activeId, query]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const h = window.setTimeout(() => refresh(query), 180);
    return () => window.clearTimeout(h);
  }, [query, refresh]);

  useEffect(() => {
    if (!active) {
      loadedId.current = null;
      setTitle("");
      setContent("");
      setDirty(false);
      setSaving("idle");
      return;
    }
    loadedId.current = active.id;
    setTitle(active.title);
    setContent(active.content);
    setDirty(false);
    setSaving("idle");
  }, [active]);

  useEffect(() => {
    if (!activeId || !dirty || loadedId.current !== activeId) return;
    setSaving("saving");
    const h = window.setTimeout(() => {
      api.updateNote(activeId, { title, content })
        .then((saved) => {
          setNotes((prev) => [saved, ...prev.filter((n) => n.id !== saved.id)]);
          setSaving("saved");
          setDirty(false);
        })
        .catch(() => setSaving("error"));
    }, 650);
    return () => window.clearTimeout(h);
  }, [activeId, content, dirty, title]);

  const create = useCallback(async () => {
    const note = await api.createNote({ title: "Untitled note", content: "" });
    setNotes((prev) => [note, ...prev]);
    setActiveId(note.id);
  }, []);

  const remove = useCallback(async () => {
    if (!activeId) return;
    await api.deleteNote(activeId).catch(() => {});
    setNotes((prev) => {
      const next = prev.filter((n) => n.id !== activeId);
      setActiveId(next[0]?.id ?? null);
      return next;
    });
  }, [activeId]);

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-hidden">
      <WorkspaceHeader
        title="Notes"
        subtitle="Local scratchpad for drafts, snippets, and things worth keeping close to the workspace."
        actions={(
          <button
            onClick={() => void create()}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium hover:bg-emerald-500"
          >
            New note
          </button>
        )}
      >
        <StatusPill label={`${notes.length} notes`} tone="info" />
        <StatusPill
          label={saving === "saving" ? "saving" : saving === "error" ? "save failed" : dirty ? "unsaved" : "saved"}
          tone={saving === "error" ? "bad" : saving === "saving" || dirty ? "warn" : "good"}
        />
      </WorkspaceHeader>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(260px,340px)_minmax(0,1fr)] gap-3">
        <Panel className="flex min-h-0 flex-col overflow-hidden">
        <div className="border-b border-border p-3">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search notes"
            className={`${field} text-xs`}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {notes.length === 0 && <EmptyState title="No notes" body="Create one from the header and it will autosave here." />}
          {notes.map((note) => (
            <button
              key={note.id}
              onClick={() => setActiveId(note.id)}
              className={`mb-1 block w-full rounded-md px-2 py-2 text-left transition ${
                activeId === note.id ? "bg-white/15" : "hover:bg-white/5"
              }`}
            >
              <div className="truncate text-sm font-medium text-ui">{note.title}</div>
              <div className="mt-0.5 truncate text-xs text-ui-subtle">{excerpt(note.content) || "empty"}</div>
              <div className="mt-1 text-[11px] text-ui-subtle">{fmt(note.updated_at)}</div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <SectionTitle
          title={active ? "Editor" : "Editor"}
          subtitle={active ? fmt(active.updated_at) : "No note selected"}
          actions={(
            <button
              onClick={() => void remove()}
              disabled={!activeId}
              className="rounded-md border border-red-400/25 px-2.5 py-1 text-xs text-red-300 hover:bg-red-400/10 disabled:opacity-30"
            >
              Delete
            </button>
          )}
        />
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <input
            value={title}
            onChange={(e) => { setTitle(e.target.value); setDirty(true); }}
            disabled={!activeId}
            placeholder="Untitled note"
            className="min-w-0 flex-1 bg-transparent text-lg font-semibold text-ui-strong outline-none placeholder:text-ui-subtle"
          />
        </div>

        <textarea
          value={content}
          onChange={(e) => { setContent(e.target.value); setDirty(true); }}
          disabled={!activeId}
          placeholder="Scratch here..."
          spellCheck
          className="min-h-0 flex-1 resize-none bg-transparent p-4 font-mono text-sm leading-6 text-ui outline-none placeholder:text-ui-subtle"
        />
      </Panel>
      </div>
    </div>
  );
}
