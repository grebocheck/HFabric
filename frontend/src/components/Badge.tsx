import type { ReactNode } from "react";

// Shared pill badge. Pass `color` for type/family accents.
export function Badge({
  children,
  color,
  className = "",
}: {
  children: ReactNode;
  color?: string;
  className?: string;
}) {
  return (
    <span
      className={`rounded border border-line bg-control px-1.5 py-0.5 text-[10px] font-medium text-ui-muted ${color ?? ""} ${className}`}
    >
      {children}
    </span>
  );
}
