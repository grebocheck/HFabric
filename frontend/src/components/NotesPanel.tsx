import { EmptyState, Panel, SectionTitle, StatusPill, WorkspaceHeader } from "./WorkspaceChrome";
import { useNotesController } from "./useNotesController";

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
  const { notes, active, query, setQuery, saving, loadError, refresh, select, create, remove, edit, retrySave } = useNotesController();
  const activeId = active?.id ?? null;

  return (
    <div className="flex h-full w-full flex-col gap-4 overflow-hidden">
      <WorkspaceHeader
        title="Notes"
        subtitle="Local scratchpad for drafts, snippets, and things worth keeping close to the workspace."
        actions={(
          <button
            onClick={() => void create()}
            className="rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium text-ui-inverse hover:bg-emerald-800"
          >
            New note
          </button>
        )}
      >
        <StatusPill label={`${notes.length} notes`} tone="info" />
        <StatusPill
          label={saving === "error" ? "save failed" : saving}
          tone={saving === "error" ? "bad" : saving === "saving" || saving === "unsaved" ? "warn" : "good"}
        />
        {saving === "error" ? <button onClick={retrySave} className="ui-button rounded-md px-3 py-1 text-xs">Retry save</button> : null}
      </WorkspaceHeader>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(260px,340px)_minmax(0,1fr)] gap-3 max-[760px]:block max-[760px]:overflow-x-hidden max-[760px]:overflow-y-auto">
        <Panel className="flex min-h-0 flex-col overflow-hidden max-[760px]:mb-3 max-[760px]:h-[320px]">
        <div className="border-b border-border p-3">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search notes"
            className={`${field} text-xs`}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {loadError ? (
            <div className="flex min-h-32 flex-col items-center justify-center gap-2 px-3 text-center">
              <p className="text-sm text-error-fg">{loadError}</p>
              <button onClick={() => refresh()} className="ui-button rounded-md px-3 py-1 text-xs">Retry</button>
            </div>
          ) : notes.length === 0 ? (
            <EmptyState title="No notes" body="Create one from the header and it will autosave here." />
          ) : null}
          {notes.map((note) => (
            <button
              key={note.id}
              onClick={() => select(note)}
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

      <Panel className="flex min-w-0 flex-1 flex-col overflow-hidden max-[760px]:h-[520px]">
        <SectionTitle
          title="Editor"
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
            value={active?.title ?? ""}
            onChange={(e) => edit({ title: e.target.value })}
            disabled={!activeId}
            placeholder="Untitled note"
            className="min-w-0 flex-1 bg-transparent text-lg font-semibold text-ui-strong outline-none placeholder:text-ui-subtle"
          />
        </div>

        <textarea
          value={active?.content ?? ""}
          onChange={(e) => edit({ content: e.target.value })}
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
