// One-time welcome shown on first launch (gated by localStorage in App). It names
// the three core surfaces and sets honest expectations for the beta — deliberately
// small, not a multi-step tour.
import { Dialog } from "./Dialog";

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
    <Dialog
      open
      title="Welcome to HFabric"
      onClose={onClose}
      closeOnBackdrop={false}
      closeOnEscape={false}
      panelClassName="flex w-full max-w-lg flex-col"
      titleClassName="shrink-0 px-4 pt-4 text-lg font-semibold text-ui-strong sm:px-5 sm:pt-5"
    >
      <div className="min-h-0 overflow-y-auto px-4 pb-4 sm:px-5 sm:pb-5">
        <p className="mt-1 text-sm leading-5 text-ui-muted">
          A local AI workspace — chat and image generation on one GPU, with nothing sent to a cloud.
          This is a <span className="text-ui-strong">public beta</span>: solid for daily use, but expect rough edges.
        </p>

        <ul className="mt-4 space-y-2">
          {SURFACES.map((s) => (
            <li key={s.name} className="flex min-w-0 gap-3 rounded-md border border-line bg-control px-3 py-2 max-[480px]:flex-col max-[480px]:gap-1">
              <span className="shrink-0 text-sm font-semibold text-accent-fg">{s.name}</span>
              <span className="min-w-0 text-xs leading-5 text-ui-muted">{s.blurb}</span>
            </li>
          ))}
        </ul>

        {stubMode ? (
          <p className="mt-4 rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-xs leading-5 text-warn-fg">
            You're in <span className="font-semibold">STUB mode</span>: results are mock placeholders so you can
            explore the UI. Install the GPU dependencies and restart for real generation.
          </p>
        ) : null}

        <div className="mt-5 flex justify-end max-[360px]:block">
          <button
            onClick={onClose}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-ui-inverse hover:bg-accent-hover max-[360px]:w-full"
          >
            Get started
          </button>
        </div>
      </div>
    </Dialog>
  );
}
