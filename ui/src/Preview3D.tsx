import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  AmbientLight,
  BufferGeometry,
  DirectionalLight,
  Line,
  LineBasicMaterial,
  Mesh,
  MeshLambertMaterial,
  PerspectiveCamera,
  Raycaster,
  Scene,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { errorMessage } from "./plan";
import { buildHeightfield, nearestSample } from "./terrainMesh";
import type { BlockInfo, MeshData } from "./types";

const EXTRA_RGB: Record<string, [number, number, number]> = {
  "minecraft:air": [0, 0, 0],
  "minecraft:cave_air": [20, 20, 24],
  "minecraft:bedrock": [84, 84, 84],
};

interface View {
  camera: PerspectiveCamera;
  terrain: Mesh | null;
  mesh: MeshData | null;
  raycaster: Raycaster;
  pointer: Vector2;
}

interface Preview3DProps {
  mesh: MeshData | null;
  blocks: BlockInfo[];
  note: string;
}

export function Preview3D({ mesh, blocks, note }: Preview3DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewRef = useRef<View | null>(null);
  const [readout, setReadout] = useState("");
  const [frameNote, setFrameNote] = useState("");

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false, preserveDrawingBuffer: true });
    } catch (error) {
      setFrameNote(errorMessage(error));
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x14110e, 1);

    const scene = new Scene();
    const camera = new PerspectiveCamera(45, 1, 0.1, 8000);
    camera.up.set(0, 1, 0);
    scene.add(new AmbientLight(0xffffff, 0.38));
    const sun = new DirectionalLight(0xfff4dd, 0.62);
    sun.position.set(80, 140, 50);
    scene.add(sun);

    const disposables: Array<() => void> = [];
    let terrain: Mesh | null = null;
    const target = new Vector3(0, 64, 0);

    if (mesh) {
      try {
        const colors = new Map(blocks.map((block) => [block.id, block.rgb]));
        const built = buildHeightfield(mesh, (blockId) => colors.get(blockId) ?? EXTRA_RGB[blockId] ?? [186, 164, 120]);
        const material = new MeshLambertMaterial({ vertexColors: true });
        terrain = new Mesh(built.geometry, material);
        terrain.position.copy(built.offset);
        scene.add(terrain);

        const northHeights = mesh.heights.slice(0, built.xSamples);
        const northY = (northHeights.length ? Math.max(...northHeights) : mesh.seaLevel) + 0.45;
        const spanX = (built.xSamples - 1) * mesh.step;
        const spanZ = (built.zSamples - 1) * mesh.step;
        const lineGeometry = new BufferGeometry().setFromPoints([
          new Vector3(-spanX / 2, northY, -spanZ / 2),
          new Vector3(spanX / 2, northY, -spanZ / 2),
        ]);
        const lineMaterial = new LineBasicMaterial({ color: 0xd4a017 });
        terrain.add(new Line(lineGeometry, lineMaterial));

        const midY = mesh.heights.reduce((sum, height) => sum + height, 0) / mesh.heights.length;
        const span = Math.max(mesh.width, mesh.depth, 32);
        target.set(built.offset.x, midY, built.offset.z);
        camera.near = 0.1;
        camera.far = span * 20;
        camera.position.set(target.x + span * 0.15, midY + span * 0.7, target.z + span * 0.9);
        camera.updateProjectionMatrix();
        disposables.push(() => {
          built.geometry.dispose();
          material.dispose();
          lineGeometry.dispose();
          lineMaterial.dispose();
        });
        setFrameNote("");
      } catch (error) {
        setFrameNote(errorMessage(error));
      }
    } else {
      camera.position.set(48, 96, 72);
    }

    const framed = camera.position.clone();
    const controls = new OrbitControls(camera, canvas);
    controls.target.copy(target);
    controls.enableDamping = false;
    controls.minPolarAngle = 0.12;
    controls.maxPolarAngle = Math.PI / 2 - 0.04;
    camera.position.copy(framed);
    controls.update();

    const render = () => {
      renderer.render(scene, camera);
    };
    controls.addEventListener("change", render);

    viewRef.current = {
      camera,
      terrain,
      mesh: terrain ? mesh : null,
      raycaster: new Raycaster(),
      pointer: new Vector2(),
    };

    const resize = () => {
      const parent = canvas.parentElement;
      const width = parent?.clientWidth ?? 0;
      const height = parent?.clientHeight ?? 0;
      if (width < 2 || height < 2) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      render();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas.parentElement ?? canvas);
    resize();

    return () => {
      observer.disconnect();
      controls.removeEventListener("change", render);
      controls.dispose();
      for (const dispose of disposables) dispose();
      renderer.dispose();
      viewRef.current = null;
    };
  }, [mesh, blocks]);

  function onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    const view = viewRef.current;
    if (!view?.terrain || !view.mesh) {
      setReadout("");
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    view.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    view.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    view.raycaster.setFromCamera(view.pointer, view.camera);
    const hits = view.raycaster.intersectObject(view.terrain, false);
    if (!hits.length) {
      setReadout("");
      return;
    }
    const nearest = nearestSample(view.mesh, hits[0].point.x, hits[0].point.z);
    setReadout(`${nearest.x}, ${nearest.z}`);
  }

  const message = frameNote || (!mesh ? note : "");

  return (
    <div>
      <div className="relief">
        <canvas
          ref={canvasRef}
          data-testid="preview-3d"
          aria-label="Three.js terrain preview. North is negative Z."
          onPointerMove={onPointerMove}
          onPointerLeave={() => setReadout("")}
        />
        {message ? <p className="relief-note">{message}</p> : null}
      </div>
      <div className="readout-line">
        <span className="readout-label">Mesh</span>
        <span data-testid="mesh-readout">{readout}</span>
      </div>
    </div>
  );
}
