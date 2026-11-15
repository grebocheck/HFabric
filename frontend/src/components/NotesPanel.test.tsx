import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Note } from "../types";
import { NotesPanel } from "./NotesPanel";
import { NoteDrafts, noteDrafts } from "./noteDrafts";

const mocks = vi.hoisted(() => ({ api: {
  listNotes: vi.fn(), updateNote: vi.fn(), createNote: vi.fn(), deleteNote: vi.fn(),
} }));
vi.mock("../api/client", () => ({ api: mocks.api }));
const note: Note = { id: "note-1", title: "Note one", content: "saved", created_at: "2026-11-15T12:00:00Z", updated_at: "2026-11-15T12:00:00Z" };
const second: Note = { ...note, id: "note-2", title: "Note two", content: "second note" };

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  for (const mock of Object.values(mocks.api)) mock.mockReset();
  mocks.api.listNotes.mockResolvedValue([note, second]);
  mocks.api.updateNote.mockImplementation((id, draft) => Promise.resolve({ ...note, id, ...draft, updated_at: "2026-11-15T12:01:00Z" }));
});
afterEach(async () => {
  cleanup();
  await act(async () => { await Promise.resolve(); });
  noteDrafts.discard(note.id);
  noteDrafts.discard(second.id);
  vi.useRealTimers();
});
async function mountNotes() {
  const view = render(<NotesPanel />);
  await act(async () => { await vi.advanceTimersByTimeAsync(200); });
  return view;
}

it("restores only editable draft fields from browser storage", () => {
  localStorage.setItem("hfabric.notes.drafts.v1", JSON.stringify({
    [note.id]: { title: "Recovered title", content: "Recovered draft", id: second.id },
  }));
  const restored = new NoteDrafts(vi.fn());
  expect(restored.read(note)).toEqual({ ...note, title: "Recovered title", content: "Recovered draft" });
});

it("flushes the latest draft when leaving before the autosave delay", async () => {
  const view = await mountNotes();
  fireEvent.change(screen.getByPlaceholderText("Scratch here..."), { target: { value: "draft before navigation" } });
  view.unmount();
  await act(async () => { await Promise.resolve(); });
  expect(mocks.api.updateNote).toHaveBeenCalledWith(note.id, { title: note.title, content: "draft before navigation" });
});

it("serializes saves and retains input entered while an older save is pending", async () => {
  let resolveFirst!: (note: Note) => void;
  mocks.api.updateNote.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
  await mountNotes();
  const editor = screen.getByPlaceholderText("Scratch here...") as HTMLTextAreaElement;
  fireEvent.change(editor, { target: { value: "first draft" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(650); });
  fireEvent.change(editor, { target: { value: "newer draft" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(650); });
  expect(mocks.api.updateNote).toHaveBeenCalledTimes(1);
  await act(async () => { resolveFirst({ ...note, content: "first draft" }); });
  expect(editor.value).toBe("newer draft");
  expect(mocks.api.updateNote).toHaveBeenLastCalledWith(note.id, { title: note.title, content: "newer draft" });
  expect(screen.getByText("saved", { exact: true })).toBeTruthy();
});

it("retains failed drafts across workspace mounts and offers retry", async () => {
  mocks.api.updateNote.mockRejectedValueOnce(new Error("offline"));
  const view = await mountNotes();
  fireEvent.change(screen.getByPlaceholderText("Scratch here..."), { target: { value: "offline draft" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(650); });
  expect(screen.getByRole("button", { name: "Retry save" })).toBeTruthy();
  // A reload can reconstruct the draft even if the pending HTTP call is lost.
  const restored = new NoteDrafts(vi.fn());
  expect(restored.read(note).content).toBe("offline draft");
  view.unmount();
  await act(async () => { await Promise.resolve(); });
  await mountNotes();
  expect((screen.getByPlaceholderText("Scratch here...") as HTMLTextAreaElement).value).toBe("offline draft");
});

it("keeps a dirty editor through search refresh and note selection", async () => {
  await mountNotes();
  fireEvent.change(screen.getByPlaceholderText("Scratch here..."), { target: { value: "local edit" } });
  fireEvent.change(screen.getByPlaceholderText("search notes"), { target: { value: "Note" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(200); });
  expect((screen.getByPlaceholderText("Scratch here...") as HTMLTextAreaElement).value).toBe("local edit");
  fireEvent.click(screen.getByRole("button", { name: /Note two/ }));
  expect((screen.getByPlaceholderText("Scratch here...") as HTMLTextAreaElement).value).toBe("second note");
  fireEvent.click(screen.getByRole("button", { name: /Note one/ }));
  expect((screen.getByPlaceholderText("Scratch here...") as HTMLTextAreaElement).value).toBe("local edit");
});
