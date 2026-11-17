import { usePreference } from "../lib/preferences";
import { preferences } from "../settings/workspacePreferences";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { Note } from "../types";
import { noteDrafts } from "./noteDrafts";
import { toast } from "./Toast";

export function useNotesController() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [selected, setSelected] = useState<Note | null>(null);
  const [query, setQuery] = usePreference(preferences.notes, "query");
  const [loadError, setLoadError] = useState("");
  const requestRevision = useRef(0);
  useSyncExternalStore(noteDrafts.subscribe, noteDrafts.snapshot);

  const refresh = useCallback(async (q: string) => {
    const revision = ++requestRevision.current;
    try {
      const rows = await api.listNotes(q);
      if (revision !== requestRevision.current) return;
      setNotes(rows);
      const savedId = preferences.notes.get().selectedId;
      setSelected((current) => current ? rows.find((note) => note.id === current.id) ?? current
        : rows.find((note) => note.id === savedId) ?? rows[0] ?? null);
      setLoadError("");
      for (const note of rows) {
        if (noteDrafts.status(note.id) === "unsaved") void noteDrafts.flush(note.id);
      }
    } catch (error) {
      if (revision === requestRevision.current) {
        setLoadError(error instanceof Error ? error.message : "Could not load notes");
      }
    }
  }, []);

  useEffect(() => {
    // Invalidate immediately, before debounce, so an older search cannot win.
    requestRevision.current += 1;
    const timer = window.setTimeout(() => { void refresh(query); }, 180);
    return () => window.clearTimeout(timer);
  }, [query, refresh]);

  useEffect(() => {
    window.addEventListener("pagehide", noteDrafts.flushAll);
    return () => {
      requestRevision.current += 1;
      window.removeEventListener("pagehide", noteDrafts.flushAll);
      noteDrafts.flushAll();
    };
  }, []);

  const select = (note: Note) => {
    preferences.notes.set((current) => ({ ...current, selectedId: note.id }));
    if (selected) void noteDrafts.flush(selected.id);
    setSelected(note);
  };
  const create = async () => {
    try {
      const note = await api.createNote({ title: "Untitled note", content: "" });
      requestRevision.current += 1;
      setNotes((previous) => [note, ...previous]);
      select(note);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not create note");
    }
  };
  const remove = async () => {
    if (!selected) return;
    try {
      await noteDrafts.flush(selected.id);
      await api.deleteNote(selected.id);
      requestRevision.current += 1;
      noteDrafts.discard(selected.id);
      setNotes((previous) => previous.filter((note) => note.id !== selected.id));
      setSelected((current) => current?.id === selected.id ? null : current);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete note");
    }
  };

  const active = selected ? noteDrafts.read(selected) : null;
  return {
    notes: notes.map((note) => noteDrafts.read(note)), active,
    query, setQuery, loadError, refresh: () => refresh(query), select, create, remove,
    saving: noteDrafts.status(selected?.id ?? null),
    edit: (patch: Partial<Pick<Note, "title" | "content">>) => {
      if (selected) noteDrafts.edit(selected, patch);
    },
    retrySave: () => { if (selected) void noteDrafts.flush(selected.id); },
  };
}
