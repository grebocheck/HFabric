// One-time welcome shown on first launch (gated by localStorage in App). It names
// the three core surfaces and sets honest expectations for the beta — deliberately
// small, not a multi-step tour.

type WelcomeProps = {
  stubMode: boolean;
  onClose: () => void;
};

const SURFACES: { name: string; blurb: string }[] = [
  { name: "Images", blurb: "Generate with SDXL / FLUX and friends — one heavy model resident at a time." },
  { name: "LLM", blurb: "Chat with a local model; attach images/docs, or type /image to generate." },
  { name: "Models", blurb: "Download models for every workspace and manage installed ones to free disk." },
  { name: "System", blurb: "Live RAM/VRAM, Setup Doctor, and runtime telemetry." },
];

export function Welcome({ stubMode, onClose }: WelcomeProps) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-lg border border-line bg-surface p-5 shadow-popover">
        <h2 className="text-lg font-semibold text-ui-strong">Welcome to HFabric</h2>
        <p className="mt-1 text-sm leading-5 text-ui-muted">
          A local AI workspace — chat and image generation on one GPU, with nothing sent to a cloud.
          This is a <span className="text-ui-strong">public beta</span>: solid for daily use, but expect rough edges.
        </p>

        <ul className="mt-4 space-y-2">
          {SURFACES.map((s) => (
            <li key={s.name} className="flex gap-3 rounded-md border border-line bg-control px-3 py-2">
              <span className="shrink-0 text-sm font-semibold text-accent-fg">{s.name}</span>
              <span className="text-xs leading-5 text-ui-muted">{s.blurb}</span>
            </li>
          ))}
        </ul>

        {stubMode ? (
          <p className="mt-4 rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-xs leading-5 text-warn-fg">
            You're in <span className="font-semibold">STUB mode</span>: results are mock placeholders so you can
            explore the UI. Install the GPU dependencies and restart for real generation.
          </p>
        ) : null}

        <div className="mt-5 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-ui-inverse hover:bg-accent-hover"
          >
            Get started
          </button>
        </div>
      </div>
    </div>
  );
}
