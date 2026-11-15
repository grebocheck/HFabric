import { api } from "../api/client";
import { storage } from "../lib/storage";
import type { Note } from "../types";

type Draft = Pick<Note, "title" | "content">;
type PendingNote = {
  draft: Draft;
  revision: number;
  savedRevision: number;
  saved?: Note;
  error: boolean;
  timer?: ReturnType<typeof setTimeout>;
  promise?: Promise<void>;
};
const DRAFTS_KEY = "hfabric.notes.drafts.v1";

/** Own drafts and one ordered save per note, independently of workspace mounts. */
export class NoteDrafts {
  private entries = new Map<string, PendingNote>();
  private listeners = new Set<() => void>();
  private version = 0;

  constructor(private write: (id: string, draft: Draft) => Promise<Note>) {
    try {
      const value: unknown = JSON.parse(storage.get(DRAFTS_KEY) ?? "{}");
      if (!value || typeof value !== "object" || Array.isArray(value)) return;
      for (const [id, draft] of Object.entries(value)) {
        if (!draft || typeof draft.title !== "string" || typeof draft.content !== "string") continue;
        this.entries.set(id, { draft: { title: draft.title, content: draft.content }, revision: 1, savedRevision: 0, error: false });
      }
    } catch {
      // Invalid browser state must not prevent loading server notes.
    }
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  snapshot = () => this.version;

  read(note: Note): Note {
    const entry = this.entries.get(note.id);
    if (!entry) return note;
    const latest = entry.saved && entry.saved.updated_at >= note.updated_at ? entry.saved : note;
    return entry.revision > entry.savedRevision ? { ...latest, ...entry.draft } : latest;
  }

  status(id: string | null): "saved" | "unsaved" | "saving" | "error" {
    const entry = id ? this.entries.get(id) : undefined;
    if (!entry) return "saved";
    if (entry.error) return "error";
    if (entry.promise) return "saving";
    return entry.revision > entry.savedRevision ? "unsaved" : "saved";
  }

  edit(note: Note, patch: Partial<Draft>) {
    const current = this.read(note);
    const entry: PendingNote = this.entries.get(note.id) ?? {
      draft: { title: current.title, content: current.content },
      revision: 0, savedRevision: 0, error: false,
    };
    entry.draft = { title: current.title, content: current.content, ...patch };
    entry.revision += 1;
    entry.error = false;
    if (entry.timer) clearTimeout(entry.timer);
    this.entries.set(note.id, entry);
    entry.timer = setTimeout(() => { void this.flush(note.id); }, 650);
    this.changed();
  }

  flush(id: string): Promise<void> {
    const entry = this.entries.get(id);
    if (!entry) return Promise.resolve();
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = undefined;
    if (entry.promise) return entry.promise;
    if (entry.revision === entry.savedRevision) return Promise.resolve();
    entry.error = false;
    // Defer execution until promise ownership is installed, including on sync errors.
    entry.promise = Promise.resolve().then(async () => {
      while (this.entries.get(id) === entry && entry.revision > entry.savedRevision) {
        const revision = entry.revision;
        try {
          const saved = await this.write(id, { ...entry.draft });
          if (this.entries.get(id) !== entry) return;
          entry.saved = saved;
          entry.savedRevision = revision;
        } catch {
          entry.error = true;
          break;
        }
      }
    }).finally(() => {
      entry.promise = undefined;
      this.changed();
    });
    this.changed();
    return entry.promise;
  }

  flushAll = () => {
    for (const id of this.entries.keys()) void this.flush(id);
  };

  discard(id: string) {
    const entry = this.entries.get(id);
    if (entry?.timer) clearTimeout(entry.timer);
    this.entries.delete(id);
    this.changed();
  }

  private changed() {
    const pending = Object.fromEntries([...this.entries]
      .filter(([, entry]) => entry.revision > entry.savedRevision)
      .map(([id, entry]) => [id, entry.draft]));
    if (Object.keys(pending).length) storage.set(DRAFTS_KEY, JSON.stringify(pending));
    else storage.remove(DRAFTS_KEY);
    this.version += 1;
    for (const listener of this.listeners) listener();
  }
}

export const noteDrafts = new NoteDrafts((id, draft) => api.updateNote(id, draft));
