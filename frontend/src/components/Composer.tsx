import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Model } from "../types";

const field = "w-full rounded-md bg-black/30 border border-white/10 px-2.5 py-1.5 text-sm outline-none focus:border-violet-500";
const label = "text-xs uppercase tracking-wide text-white/40";

export function Composer({
  models,
  promptDraft,
  setPromptDraft,
  expanding,
  onExpand,
}: {
  models: Model[];
  promptDraft: string;
  setPromptDraft: (v: string) => void;
  expanding: boolean;
  onExpand: (idea: string, llmModelId: string, style?: string) => void;
}) {
  const llmModels = models.filter((m) => m.job_type === "llm");
  const imgModels = models.filter((m) => m.job_type === "image");

  const [idea, setIdea] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [imgModel, setImgModel] = useState("");

  const [negative, setNegative] = useState("");
  const [steps, setSteps] = useState(28);
  const [guidance, setGuidance] = useState(3.5);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [seed, setSeed] = useState(-1);
  const [batch, setBatch] = useState(1);
  const [count, setCount] = useState(1);

  // sensible defaults once models load
  useEffect(() => {
    if (!llmModel && llmModels[0]) setLlmModel(llmModels[0].id);
    if (!imgModel && imgModels[0]) setImgModel(imgModels[0].id);
  }, [llmModels, imgModels, llmModel, imgModel]);

  const generate = async () => {
    if (!imgModel || !promptDraft.trim()) return;
    const params = {
      prompt: promptDraft.trim(),
      negative: negative.trim() || undefined,
      steps,
      guidance,
      width,
      height,
      seed,
      batch_size: batch,
    };
    const jobs = Array.from({ length: count }, () => ({
      type: "image" as const,
      model_id: imgModel,
      params,
    }));
    await api.createJobs(jobs);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* --- LLM idea -> prompt --- */}
      <section className="rounded-lg border border-white/10 p-3">
        <div className={label}>Idea → prompt (LLM)</div>
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={2}
          placeholder="a lone astronaut cat on a neon rooftop…"
          className={`${field} mt-1 resize-none`}
        />
        <div className="mt-2 flex gap-2">
          <select value={llmModel} onChange={(e) => setLlmModel(e.target.value)} className={`${field} flex-1`}>
            {llmModels.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
          <button
            onClick={() => idea.trim() && onExpand(idea.trim(), llmModel)}
            disabled={expanding || !idea.trim() || !llmModel}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-40"
          >
            {expanding ? "Expanding…" : "Expand"}
          </button>
        </div>
      </section>

      {/* --- prompt + image params --- */}
      <section className="rounded-lg border border-white/10 p-3">
        <div className={label}>Prompt</div>
        <textarea
          value={promptDraft}
          onChange={(e) => setPromptDraft(e.target.value)}
          rows={4}
          placeholder="final image prompt (LLM output streams here, editable)…"
          className={`${field} mt-1 resize-none`}
        />
        <div className={`${label} mt-3`}>Negative</div>
        <input value={negative} onChange={(e) => setNegative(e.target.value)} className={`${field} mt-1`} />

        <div className="mt-3 grid grid-cols-3 gap-2">
          <Num label="Steps" v={steps} set={setSteps} />
          <Num label="Guidance" v={guidance} set={setGuidance} step={0.1} />
          <Num label="Seed" v={seed} set={setSeed} />
          <Num label="Width" v={width} set={setWidth} step={64} />
          <Num label="Height" v={height} set={setHeight} step={64} />
          <Num label="Batch" v={batch} set={setBatch} />
        </div>

        <div className="mt-3 flex items-end gap-2">
          <label className="flex-1">
            <div className={label}>Model</div>
            <select value={imgModel} onChange={(e) => setImgModel(e.target.value)} className={`${field} mt-1`}>
              {imgModels.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </label>
          <Num label="× jobs" v={count} set={setCount} />
          <button
            onClick={generate}
            disabled={!imgModel || !promptDraft.trim()}
            className="rounded-md bg-violet-600 px-4 py-1.5 text-sm font-medium hover:bg-violet-500 disabled:opacity-40"
          >
            Queue
          </button>
        </div>
      </section>
    </div>
  );
}

function Num({ label: l, v, set, step = 1 }: { label: string; v: number; set: (n: number) => void; step?: number }) {
  return (
    <label className="block">
      <div className="text-xs uppercase tracking-wide text-white/40">{l}</div>
      <input
        type="number"
        value={v}
        step={step}
        onChange={(e) => set(Number(e.target.value))}
        className="mt-1 w-full rounded-md border border-white/10 bg-black/30 px-2 py-1 text-sm outline-none focus:border-violet-500"
      />
    </label>
  );
}
