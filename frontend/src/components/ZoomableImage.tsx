import { useCallback, useRef, useState, type PointerEvent, type WheelEvent } from "react";

export const MIN_SCALE = 1;
export const MAX_SCALE = 8;

export function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

// A pan/zoom image surface (P13.3) shared by the result lightbox and the History
// detail modal: wheel (or pinch via ctrl+wheel) zooms toward centre, drag pans
// once zoomed in, and double-click resets. Pure scale clamping is unit-tested.
export function ZoomableImage({ src, alt = "", className = "" }: { src: string; alt?: string; className?: string }) {
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);

  const reset = useCallback(() => {
    setScale(1);
    setTx(0);
    setTy(0);
  }, []);

  const zoomBy = useCallback((factor: number) => {
    setScale((s) => {
      const next = clampScale(s * factor);
      if (next === 1) {
        setTx(0);
        setTy(0);
      }
      return next;
    });
  }, []);

  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15);
  };

  const onPointerDown = (e: PointerEvent) => {
    if (scale <= 1) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, tx, ty };
  };

  const onPointerMove = (e: PointerEvent) => {
    if (!drag.current) return;
    setTx(drag.current.tx + (e.clientX - drag.current.x));
    setTy(drag.current.ty + (e.clientY - drag.current.y));
  };

  const endDrag = () => {
    drag.current = null;
  };

  return (
    <div
      className={`relative flex items-center justify-center overflow-hidden ${className}`}
      onWheel={onWheel}
      onDoubleClick={reset}
      onClick={(e) => e.stopPropagation()}
    >
      <img
        src={src}
        alt={alt}
        draggable={false}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        style={{ transform: `translate(${tx}px, ${ty}px) scale(${scale})` }}
        className={`max-h-full max-w-full select-none object-contain transition-[transform] duration-75 ${
          scale > 1 ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in"
        }`}
      />
      <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-md border border-white/15 bg-black/70 px-1.5 py-1 text-xs text-white/80 backdrop-blur">
        <button onClick={() => zoomBy(1 / 1.4)} className="rounded px-2 py-0.5 hover:bg-white/15" aria-label="Zoom out">−</button>
        <span className="w-12 text-center font-mono text-[11px] text-white/55">{Math.round(scale * 100)}%</span>
        <button onClick={() => zoomBy(1.4)} className="rounded px-2 py-0.5 hover:bg-white/15" aria-label="Zoom in">+</button>
        <button onClick={reset} className="ml-1 rounded px-2 py-0.5 text-[11px] hover:bg-white/15">Reset</button>
      </div>
    </div>
  );
}
