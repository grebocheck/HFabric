import { useEffect, useMemo, useState, type ImgHTMLAttributes } from "react";

export function ResilientImage({
  sources,
  alt,
  className = "",
  placeholder = "Image unavailable",
  ...props
}: Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & {
  sources: Array<string | null | undefined>;
  alt: string;
  placeholder?: string;
}) {
  const candidates = useMemo(
    () => Array.from(new Set(sources.filter((source): source is string => Boolean(source)))),
    [sources],
  );
  const signature = candidates.join("\n");
  const [index, setIndex] = useState(0);

  useEffect(() => setIndex(0), [signature]);

  const src = candidates[index];
  if (!src) {
    return (
      <div
        role={alt ? "img" : undefined}
        aria-label={alt || undefined}
        aria-hidden={alt ? undefined : "true"}
        className={`grid place-items-center bg-control px-2 text-center text-[10px] text-ui-subtle ${className}`}
      >
        {placeholder}
      </div>
    );
  }

  return (
    <img
      {...props}
      src={src}
      alt={alt}
      className={className}
      onError={(event) => {
        props.onError?.(event);
        setIndex((current) => current + 1);
      }}
    />
  );
}
