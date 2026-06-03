import { useEffect, useState } from "react";
import type { Model } from "../types";

const field = "w-full rounded-md bg-black/30 border border-white/10 px-2.5 py-1.5 text-sm outline-none focus:border-emerald-500";
const label = "text-xs uppercase tracking-wide text-white/40";

export function LlmPanel({
  models,
  promptDraft,
  setPromptDraft,
  expanding,
  onExpand,
  onUseInImages,
}: {
  models: Model[];
  promptDraft: string;
  setPromptDraft: (v: string) => void;
  expanding: boolean;
  onExpand: (idea: string, llmModelId: string, style?: string) => void;
  onUseInImages: () => void;
}) {
  const llmModels = models.filter((m) => m.job_type === "llm");
  const [idea, setIdea] = useState("");
  const [style, setStyle] = useState("");
  const [llmModel, setLlmModel] = useState("");

  useEffect(() => {
    if (!llmModel && llmModels[0]) setLlmModel(llmModels[0].id);
  }, [llmModels, llmModel]);

  const expand = () => {
    if (idea.trim() && llmModel) onExpand(idea.trim(), llmModel, style.trim() || undefined);
  };

  return (
    <div className="mx-auto flex h-full w-full max-w-5xl flex-col gap-4">
      <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-2">
        {/* --- idea input --- */}
        <section className="flex flex-col rounded-lg border border-white/10 p-4">
          <h2 className="text-sm font-semibold text-white/75">Idea → image prompt</h2>
          <p className="mt-1 text-xs text-white/40">
            Describe a concept; the LLM expands it into a detailed prompt you can send to image generation.
          </p>

          <div className={`${label} mt-4`}>Idea</div>
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            rows={5}
            placeholder="a lone astronaut cat on a neon rooftop…"
            className={`${field} mt-1 resize-none`}
          />

          <div className={`${label} mt-3`}>Style / direction (optional)</div>
          <input
            value={style}
            onChange={(e) => setStyle(e.target.value)}
            placeholder="cinematic, 85mm, moody lighting…"
            className={`${field} mt-1`}
          />

          <div className={`${label} mt-3`}>LLM model</div>
          <select value={llmModel} onChange={(e) => setLlmModel(e.target.value)} className={`${field} mt-1`}>
            {llmModels.length === 0 && <option value="">no LLM models found</option>}
            {llmModels.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>

          <button
            onClick={expand}
            disabled={expanding || !idea.trim() || !llmModel}
            className="mt-4 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium hover:bg-emerald-500 disabled:opacity-40"
          >
            {expanding ? "Expanding…" : "Expand"}
          </button>
        </section>

        {/* --- output --- */}
        <section className="flex flex-col rounded-lg border border-white/10 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white/75">Generated prompt</h2>
            {expanding && <span className="text-xs text-emerald-300/80">streaming…</span>}
          </div>
          <textarea
            value={promptDraft}
            onChange={(e) => setPromptDraft(e.target.value)}
            placeholder="the LLM output streams here, fully editable…"
            className={`${field} mt-3 flex-1 resize-none font-mono text-[13px] leading-relaxed`}
          />
          <div className="mt-3 flex items-center justify-between">
            <button
              onClick={() => setPromptDraft("")}
              disabled={!promptDraft}
              className="rounded-md border border-white/15 px-2.5 py-1.5 text-xs hover:bg-white/10 disabled:opacity-30"
            >
              Clear
            </button>
            <button
              onClick={onUseInImages}
              disabled={!promptDraft.trim()}
              className="rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium hover:bg-violet-500 disabled:opacity-40"
            >
              Use in image generation →
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
