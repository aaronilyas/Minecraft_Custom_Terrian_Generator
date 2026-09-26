import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  borderSquare,
  clampOrigin,
  clampShape,
  hitRegion,
  inclusiveShape,
  paintedBounds,
} from "./plan";
import type { Project, Shape, Tool } from "./types";

interface DragDraw {
  kind: "draw";
  shape: Shape;
}

interface DragMove {
  kind: "move";
  id: string;
  originX: number;
  originZ: number;
  shape: Shape;
}

type Drag = DragDraw | DragMove;

interface MapCanvasProps {
  project: Project;
  selectedId: string | null;
  tool: Tool;
  onSelect: (regionId: string) => void;
  onCreate: (shape: Shape) => void;
  onMove: (regionId: string, x: number, z: number) => void;
  onReject: (message: string) => void;
}

function paint(canvas: HTMLCanvasElement, project: Project, selectedId: string | null, drag: Drag | null): void {
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;
  if (cssWidth < 2 || cssHeight < 2) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const pixelWidth = Math.round(cssWidth * dpr);
  const pixelHeight = Math.round(cssHeight * dpr);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const border = borderSquare(project);
  const painted = paintedBounds(project);
  const scaleX = cssWidth / border.size;
  const scaleY = cssHeight / border.size;
  const toX = (x: number) => (x - border.minX) * scaleX;
  const toY = (z: number) => (z - border.minZ) * scaleY;

  ctx.fillStyle = "#b7a47e";
  ctx.fillRect(0, 0, cssWidth, cssHeight);
  ctx.fillStyle = "#cbb892";
  ctx.fillRect(toX(painted.minX), toY(painted.minZ), (painted.maxX - painted.minX) * scaleX, (painted.maxZ - painted.minZ) * scaleY);

  ctx.strokeStyle = "rgba(70, 52, 28, 0.28)";
  ctx.lineWidth = 1;
  const gridStartX = Math.ceil(border.minX / 16) * 16;
  const gridStartZ = Math.ceil(border.minZ / 16) * 16;
  for (let x = gridStartX; x < border.minX + border.size; x += 16) {
    ctx.beginPath();
    ctx.moveTo(toX(x), 0);
    ctx.lineTo(toX(x), cssHeight);
    ctx.stroke();
  }
  for (let z = gridStartZ; z < border.minZ + border.size; z += 16) {
    ctx.beginPath();
    ctx.moveTo(0, toY(z));
    ctx.lineTo(cssWidth, toY(z));
    ctx.stroke();
  }

  const regions = project.regions.map((region) => {
    if (drag?.kind === "move" && drag.id === region.id) return { ...region, shape: drag.shape };
    return region;
  });
  for (const region of regions) {
    const shape = region.shape;
    const x = toX(shape.x);
    const y = toY(shape.z);
    const w = shape.width * scaleX;
    const h = shape.depth * scaleY;
    ctx.fillStyle = region.color;
    ctx.globalAlpha = region.id === selectedId ? 0.72 : 0.5;
    ctx.beginPath();
    const maskKind = region.mask?.kind;
    if ((maskKind === "ellipse" || maskKind === "blob") && w > 0 && h > 0) {
      ctx.ellipse(x + w / 2, y + h / 2, Math.abs(w) / 2, Math.abs(h) / 2, 0, 0, Math.PI * 2);
    } else if (maskKind === "polygon" && region.mask?.points && region.mask.points.length >= 3) {
      region.mask.points.forEach((point, index) => {
        const px = toX(point.x);
        const py = toY(point.z);
        if (index === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
    } else {
      ctx.rect(x, y, w, h);
    }
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.lineWidth = region.id === selectedId ? 3 : 1.5;
    ctx.strokeStyle = region.id === selectedId ? "#d4a017" : region.color;
    ctx.stroke();
    ctx.save();
    ctx.globalAlpha = 0.35;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(x, y, w, h);
    ctx.restore();
    if (w > 28 && h > 16) {
      ctx.font = "14px Palatino, Georgia, serif";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(243, 234, 215, 0.85)";
      ctx.strokeText(region.name, x + 6, y + 16);
      ctx.fillStyle = "#1c1915";
      ctx.fillText(region.name, x + 6, y + 16);
    }
  }

  if (drag?.kind === "draw") {
    const shape = drag.shape;
    ctx.save();
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = "#d4a017";
    ctx.lineWidth = 2;
    ctx.strokeRect(toX(shape.x), toY(shape.z), shape.width * scaleX, shape.depth * scaleY);
    ctx.restore();
  }

  const spawn = project.world.spawn;
  const sx = toX(spawn.x + 0.5);
  const sy = toY(spawn.z + 0.5);
  ctx.beginPath();
  ctx.moveTo(sx, sy - 7);
  ctx.lineTo(sx + 5, sy);
  ctx.lineTo(sx, sy + 7);
  ctx.lineTo(sx - 5, sy);
  ctx.closePath();
  ctx.fillStyle = "#1c1915";
  ctx.fill();
  ctx.strokeStyle = "#d4a017";
  ctx.lineWidth = 1.5;
  ctx.stroke();

  ctx.fillStyle = "#6a4a12";
  ctx.font = "600 13px Palatino, Georgia, serif";
  ctx.textAlign = "center";
  ctx.fillText("N", cssWidth / 2, 16);
  ctx.textAlign = "start";

  ctx.strokeStyle = "#d4a017";
  ctx.lineWidth = 3;
  ctx.strokeRect(1.5, 1.5, cssWidth - 3, cssHeight - 3);
}

export function MapCanvas({ project, selectedId, tool, onSelect, onCreate, onMove, onReject }: MapCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<Drag | null>(null);
  const anchorRef = useRef<{ x: number; z: number } | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [coord, setCoord] = useState("");
  const border = borderSquare(project);

  function setDragBoth(next: Drag | null) {
    dragRef.current = next;
    setDrag(next);
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => paint(canvas, project, selectedId, drag);
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [project, selectedId, drag]);

  function blockAt(event: ReactPointerEvent<HTMLCanvasElement>): { x: number; z: number } {
    const rect = event.currentTarget.getBoundingClientRect();
    const u = rect.width ? (event.clientX - rect.left) / rect.width : 0;
    const v = rect.height ? (event.clientY - rect.top) / rect.height : 0;
    const x = Math.min(border.minX + border.size - 1, Math.max(border.minX, Math.floor(border.minX + u * border.size)));
    const z = Math.min(border.minZ + border.size - 1, Math.max(border.minZ, Math.floor(border.minZ + v * border.size)));
    return { x, z };
  }

  function onPointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (event.button !== 0) return;
    const block = blockAt(event);
    setCoord(`${block.x}, ${block.z}`);
    event.currentTarget.setPointerCapture(event.pointerId);
    if (tool === "select") {
      const hit = hitRegion(project.regions, block.x, block.z);
      if (hit) onSelect(hit.id);
      return;
    }
    if (tool === "draw") {
      anchorRef.current = block;
      const shape = clampShape(inclusiveShape(block, block), paintedBounds(project));
      setDragBoth({ kind: "draw", shape });
      return;
    }
    const region = project.regions.find((item) => item.id === selectedId);
    if (!region) {
      onReject("Select a region to move.");
      return;
    }
    anchorRef.current = block;
    setDragBoth({
      kind: "move",
      id: region.id,
      originX: region.shape.x,
      originZ: region.shape.z,
      shape: { ...region.shape },
    });
  }

  function onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    const block = blockAt(event);
    setCoord(`${block.x}, ${block.z}`);
    const current = dragRef.current;
    const anchor = anchorRef.current;
    if (!current || !anchor) return;
    if (current.kind === "draw") {
      const raw = inclusiveShape(anchor, block);
      setDragBoth({ kind: "draw", shape: clampShape(raw, paintedBounds(project)) });
      return;
    }
    const next = clampOrigin(
      current.originX + (block.x - anchor.x),
      current.originZ + (block.z - anchor.z),
      current.shape,
      paintedBounds(project),
    );
    setDragBoth({ ...current, shape: { ...current.shape, x: next.x, z: next.z } });
  }

  function onPointerUp(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const current = dragRef.current;
    anchorRef.current = null;
    setDragBoth(null);
    if (!current) return;
    if (current.kind === "draw") {
      if (current.shape.width < 4 || current.shape.depth < 4) {
        onReject("Regions must be at least 4 blocks on each side.");
        return;
      }
      onCreate(current.shape);
      return;
    }
    if (current.shape.x !== current.originX || current.shape.z !== current.originZ) {
      onMove(current.id, current.shape.x, current.shape.z);
    }
  }

  return (
    <div>
      <div className="map-frame">
        <canvas
          ref={canvasRef}
          className="map-canvas"
          data-testid="map-canvas"
          data-min-x={border.minX}
          data-min-z={border.minZ}
          data-size={border.size}
          aria-label="World map. North is up."
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => {
            if (!dragRef.current) setCoord("");
          }}
        />
      </div>
      <div className="readout-line">
        <span className="readout-label">Pointer</span>
        <span data-testid="coord-readout">{coord}</span>
      </div>
      <p className="note">North is up (−Z). The pale sheet is the paintable world. The brass frame is the border square.</p>
    </div>
  );
}
