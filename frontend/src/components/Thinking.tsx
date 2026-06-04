import { useState } from "react";
import { Markdown } from "./Markdown";

// Many local reasoning models (DeepSeek-R1, Qwen, …) wrap their chain-of-thought
// in <think>…</think> (or <thinking>). Split it out so we can show the reasoning
// in a collapsible disclosure and render only the answer as the main reply.
export function splitReasoning(content: string): { reasoning: string | null; answer: string; active: boolean } {
  const open = content.match(/<think(?:ing)?>/i);
  if (!open || open.index == null) return { reasoning: null, answer: content, active: false };

  const start = open.index + open[0].length;
  const rest = content.slice(start);
  const close = rest.match(/<\/think(?:ing)?>/i);
  const before = content.slice(0, open.index);

  if (!close || close.index == null) {
    // The closing tag hasn't streamed in yet — still actively reasoning.
    return { reasoning: rest.trim() || null, answer: before.trim(), active: true };
  }

  const reasoning = rest.slice(0, close.index).trim();
  const after = rest.slice(close.index + close[0].length);
  return { reasoning: reasoning || null, answer: (before + after).trim(), active: false };
}

export function AssistantContent({ content }: { content: string }) {
  const { reasoning, answer, active } = splitReasoning(content);
  return (
    <>
      {reasoning ? <Thinking reasoning={reasoning} active={active} /> : null}
      {answer ? <Markdown content={answer} /> : (active ? null : <span className="text-sm text-white/30">…</span>)}
    </>
  );
}

function Thinking({ reasoning, active }: { reasoning: string; active: boolean }) {
  const [open, setOpen] = useState(false);
  // Auto-expand while the model is still thinking; once the answer starts it
  // follows the user's toggle (default collapsed) so reasoning stays out of the way.
  const expanded = open || active;

  return (
    <div className="mb-2 rounded-md border border-white/10 bg-black/20">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-white/50 transition hover:text-white/80"
      >
        {active ? (
          <svg className="h-3 w-3 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
            <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </svg>
        ) : (
          <svg className={`h-3 w-3 transition-transform ${expanded ? "rotate-90" : ""}`} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
            <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
        <span>{active ? "Thinking…" : "Reasoning"}</span>
      </button>
      {expanded ? (
        <div className="whitespace-pre-wrap border-t border-white/10 px-2.5 py-2 text-xs leading-5 text-white/55">
          {reasoning}
        </div>
      ) : null}
    </div>
  );
}
