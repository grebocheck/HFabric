import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";

import { Slider } from "./Slider";

type Tool = "brush" | "lasso" | "erase";
type Point = { x: number; y: number };

const label = "text-[10px] font-medium uppercase tracking-wide text-ui-subtle";
const toolButton = "h-7 rounded-md border px-2.5 text-xs transition disabled:opacity-30";
const MAX_UNDO = 16;

export function MaskEditor({
  src,
  onMaskChange,
  large = false,
  onFeatherChange,
}: {
  src: string;
  onMaskChange: (file: File | null) => void;
  large?: boolean;
  onFeatherChange?: (value: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const undoRef = useRef<ImageData[]>([]);
  const activeRef = useRef<{ tool: Tool; last: Point; points: Point[] } | null>(null);
  const [size, setSize] = useState<Point>({ x: 1, y: 1 });
  const [tool, setTool] = useState<Tool>("brush");
  const [brush, setBrush] = useState(36);
  const [feather, setFeather] = useState(6);
  const [lassoPoints, setLassoPoints] = useState<Point[]>([]);
  const [canUndo, setCanUndo] = useState(false);
  const [hasMask, setHasMask] = useState(false);

  const resetCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { willReadFrequently: true });
    if (!canvas || !ctx) return;
    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.restore();
    undoRef.current = [];
    setCanUndo(false);
    setHasMask(false);
    setLassoPoints([]);
    onMaskChange(null);
  }, [onMaskChange]);

  useEffect(() => {
    resetCanvas();
  }, [resetCanvas, src, size.x, size.y]);

  const exportMask = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (!canvasHasPaint(canvas)) {
      setHasMask(false);
      onMaskChange(null);
      return;
    }

    const out = document.createElement("canvas");
    out.width = canvas.width;
    out.height = canvas.height;
    const ctx = out.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, out.width, out.height);
    if (feather > 0 && !onFeatherChange) {
      ctx.filter = `blur(${feather}px)`;
    }
    ctx.drawImage(canvas, 0, 0);
    ctx.filter = "none";
    out.toBlob((blob) => {
      if (!blob) {
        onMaskChange(null);
        return;
      }
      setHasMask(true);
      onMaskChange(new File([blob], "mask.png", { type: "image/png" }));
    }, "image/png");
  }, [feather, onFeatherChange, onMaskChange]);

  useEffect(() => {
    onFeatherChange?.(feather);
  }, [feather, onFeatherChange]);

  useEffect(() => {
    if (hasMask) exportMask();
  }, [exportMask, feather, hasMask]);

  const pushUndo = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { willReadFrequently: true });
    if (!canvas || !ctx) return;
    undoRef.current = [...undoRef.current.slice(-(MAX_UNDO - 1)), ctx.getImageData(0, 0, canvas.width, canvas.height)];
    setCanUndo(true);
  };

  const pointerPoint = (e: PointerEvent<HTMLCanvasElement>): Point | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return {
      x: ((e.clientX - rect.left) / rect.width) * canvas.width,
      y: ((e.clientY - rect.top) / rect.height) * canvas.height,
    };
  };

  const onPointerDown = (e: PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { willReadFrequently: true });
    const point = pointerPoint(e);
    if (!canvas || !ctx || !point) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    pushUndo();
    if (tool === "lasso") {
      activeRef.current = { tool, last: point, points: [point] };
      setLassoPoints([point]);
      return;
    }
    drawStroke(ctx, point, point, brush, tool);
    activeRef.current = { tool, last: point, points: [] };
  };

  const onPointerMove = (e: PointerEvent<HTMLCanvasElement>) => {
    const active = activeRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { willReadFrequently: true });
    const point = pointerPoint(e);
    if (!active || !canvas || !ctx || !point) return;
    e.preventDefault();
    if (active.tool === "lasso") {
      active.points = [...active.points, point];
      active.last = point;
      setLassoPoints(active.points);
      return;
    }
    drawStroke(ctx, active.last, point, brush, active.tool);
    active.last = point;
  };

  const onPointerUp = (e: PointerEvent<HTMLCanvasElement>) => {
    const active = activeRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { willReadFrequently: true });
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    activeRef.current = null;
    if (active?.tool === "lasso" && ctx && active.points.length > 2) {
      fillLasso(ctx, active.points);
    }
    setLassoPoints([]);
    exportMask();
  };

  const undo = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { willReadFrequently: true });
    const image = undoRef.current.pop();
    if (!canvas || !ctx || !image) return;
    ctx.putImageData(image, 0, 0);
    setCanUndo(undoRef.current.length > 0);
    exportMask();
  };

  const clear = () => {
    resetCanvas();
  };

  const imageHeight = large ? "max-h-[62vh]" : "max-h-52";

  return (
    <div className="ui-card rounded-md p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className={label}>Mask</div>
        <span className="ui-chip rounded px-1.5 py-0.5 text-[10px] uppercase">
          {hasMask ? "ready" : "empty"}
        </span>
      </div>
      <div className="ui-stage mt-2 flex justify-center overflow-hidden rounded-md border border-border">
        <div className={`relative grid max-w-full touch-none select-none ${imageHeight}`}>
          <img
            src={src}
            alt="source"
            draggable={false}
            onLoad={(e) => setSize({ x: e.currentTarget.naturalWidth || 1, y: e.currentTarget.naturalHeight || 1 })}
            className={`col-start-1 row-start-1 max-w-full object-contain ${imageHeight}`}
          />
          <canvas
            ref={canvasRef}
            width={size.x}
            height={size.y}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            className={`col-start-1 row-start-1 max-w-full cursor-crosshair opacity-55 mix-blend-screen ${imageHeight}`}
          />
          {lassoPoints.length > 1 ? (
            <svg
              viewBox={`0 0 ${size.x} ${size.y}`}
              className={`pointer-events-none col-start-1 row-start-1 max-w-full ${imageHeight}`}
            >
              <polyline
                points={lassoPoints.map((p) => `${p.x},${p.y}`).join(" ")}
                fill="none"
                stroke="rgb(167 139 250)"
                strokeWidth={Math.max(2, brush / 7)}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          ) : null}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {(["brush", "lasso", "erase"] as Tool[]).map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setTool(item)}
            className={`${toolButton} ${
              tool === item ? "border-accent/70 bg-accent/20 text-accent-fg" : "border-border-strong text-ui-muted hover:bg-control-hover"
            }`}
          >
            {item}
          </button>
        ))}
        <button type="button" onClick={undo} disabled={!canUndo} className={`${toolButton} border-border-strong text-ui-muted hover:bg-control-hover`}>
          Undo
        </button>
        <button type="button" onClick={clear} disabled={!hasMask} className={`${toolButton} border-border-strong text-ui-muted hover:bg-control-hover`}>
          Clear
        </button>
      </div>
      <div className="mt-2 grid gap-2">
        <div>
          <div className="flex items-center justify-between text-[11px] text-ui-subtle">
            <span>Brush</span>
            <span className="font-mono text-ui-muted">{Math.round(brush)}px</span>
          </div>
          <Slider value={brush} min={4} max={96} step={1} onChange={setBrush} />
        </div>
        <div>
          <div className="flex items-center justify-between text-[11px] text-ui-subtle">
            <span>Feather</span>
            <span className="font-mono text-ui-muted">{Math.round(feather)}px</span>
          </div>
          <Slider value={feather} min={0} max={32} step={1} onChange={setFeather} />
        </div>
      </div>
    </div>
  );
}

function drawStroke(ctx: CanvasRenderingContext2D, from: Point, to: Point, size: number, tool: Tool) {
  ctx.save();
  ctx.globalCompositeOperation = "source-over";
  ctx.strokeStyle = tool === "erase" ? "black" : "white";
  ctx.fillStyle = tool === "erase" ? "black" : "white";
  ctx.lineWidth = size;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(from.x, from.y);
  ctx.lineTo(to.x, to.y);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(to.x, to.y, size / 2, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function fillLasso(ctx: CanvasRenderingContext2D, points: Point[]) {
  ctx.save();
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = "white";
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) {
    ctx.lineTo(point.x, point.y);
  }
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function canvasHasPaint(canvas: HTMLCanvasElement): boolean {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return false;
  const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] > 4 || data[i + 1] > 4 || data[i + 2] > 4) return true;
  }
  return false;
}
