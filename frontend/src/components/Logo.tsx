// HFabric brand mark: an accent tile with a woven "H". Kept in sync with
// public/favicon.svg. Scales via the `className` (set height/width there).
export function Logo({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="hfabric-logo" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#8b5cf6" />
          <stop offset="1" stopColor="#6d28d9" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#hfabric-logo)" />
      <g stroke="#fff" strokeWidth="3" strokeLinecap="round">
        <path d="M11 9.5V22.5" />
        <path d="M21 9.5V22.5" />
        <path d="M11 16h10" />
      </g>
    </svg>
  );
}
