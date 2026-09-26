import {
  BufferAttribute,
  BufferGeometry,
  Color,
  Mesh,
  MeshBasicMaterial,
  PlaneGeometry,
  Raycaster,
  Vector3,
} from "three";
import type { MeshData } from "./types";

export interface Heightfield {
  geometry: BufferGeometry;
  offset: Vector3;
  xSamples: number;
  zSamples: number;
}

function sampleCounts(mesh: MeshData): { xSamples: number; zSamples: number } {
  return {
    xSamples: Math.round(mesh.width / mesh.step),
    zSamples: Math.round(mesh.depth / mesh.step),
  };
}

export function nearestSample(mesh: MeshData, x: number, z: number): { x: number; z: number } {
  const { xSamples, zSamples } = sampleCounts(mesh);
  const maxX = mesh.minX + (xSamples - 1) * mesh.step;
  const maxZ = mesh.minZ + (zSamples - 1) * mesh.step;
  return {
    x: Math.min(maxX, Math.max(mesh.minX, Math.round(x))),
    z: Math.min(maxZ, Math.max(mesh.minZ, Math.round(z))),
  };
}

/**
 * World x → Three x, height → Three y, world z → Three z.
 * PlaneGeometry.rotateX(-π/2) sends local +Y to world −Z and the +Z normal to +Y,
 * so row iz = 0 (mesh minZ, north) stays on the −Z edge and the ground faces up.
 */
export function buildHeightfield(mesh: MeshData, colorOf: (blockId: string) => [number, number, number]): Heightfield {
  const { xSamples, zSamples } = sampleCounts(mesh);
  const expected = xSamples * zSamples;
  if (xSamples < 2 || zSamples < 2 || mesh.heights.length < expected || mesh.surface.length < expected) {
    throw new Error("Mesh grid does not match width, depth, and step.");
  }
  const spanX = (xSamples - 1) * mesh.step;
  const spanZ = (zSamples - 1) * mesh.step;
  const geometry = new PlaneGeometry(spanX, spanZ, xSamples - 1, zSamples - 1);
  geometry.rotateX(-Math.PI / 2);
  const position = geometry.getAttribute("position");
  const colors = new Float32Array(position.count * 3);
  const color = new Color();
  for (let iz = 0; iz < zSamples; iz += 1) {
    for (let ix = 0; ix < xSamples; ix += 1) {
      const vertex = iz * xSamples + ix;
      const sample = iz * xSamples + ix;
      position.setY(vertex, mesh.heights[sample] ?? 0);
      const rgb = colorOf(mesh.surface[sample] ?? "");
      color.setStyle(`rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`);
      colors[vertex * 3] = color.r;
      colors[vertex * 3 + 1] = color.g;
      colors[vertex * 3 + 2] = color.b;
    }
  }
  position.needsUpdate = true;
  geometry.setAttribute("color", new BufferAttribute(colors, 3));
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return {
    geometry,
    offset: new Vector3(mesh.minX + spanX / 2, 0, mesh.minZ + spanZ / 2),
    xSamples,
    zSamples,
  };
}

function closeTo(actual: number, expected: number, label: string): void {
  if (Math.abs(actual - expected) > 1e-3) {
    throw new Error(`${label}: expected ${expected}, got ${actual}`);
  }
}

/** Concrete north-west / south-east check. North is the smaller z. */
export function assertHeightfieldFrame(): void {
  const mesh: MeshData = {
    minX: -64,
    minZ: -64,
    width: 4,
    depth: 4,
    step: 1,
    seaLevel: 63,
    heights: [10, 11, 12, 13, 20, 21, 22, 23, 30, 31, 32, 33, 40, 41, 42, 43],
    surface: Array.from({ length: 16 }, () => "minecraft:grass_block"),
  };
  const built = buildHeightfield(mesh, () => [121, 178, 68]);
  const position = built.geometry.getAttribute("position");
  const at = (ix: number, iz: number) => {
    const index = iz * 4 + ix;
    return new Vector3(
      position.getX(index) + built.offset.x,
      position.getY(index) + built.offset.y,
      position.getZ(index) + built.offset.z,
    );
  };
  const northWest = at(0, 0);
  const northEast = at(3, 0);
  const southWest = at(0, 3);
  closeTo(northWest.x, -64, "nw x");
  closeTo(northWest.y, 10, "nw y");
  closeTo(northWest.z, -64, "nw z");
  closeTo(northEast.x, -61, "ne x");
  closeTo(northEast.z, -64, "ne z");
  closeTo(southWest.x, -64, "sw x");
  closeTo(southWest.z, -61, "sw z");
  if (!(northWest.z < southWest.z)) throw new Error("north is not -Z");
  const normal = built.geometry.getAttribute("normal");
  for (let index = 0; index < normal.count; index += 1) {
    if (normal.getY(index) <= 0) throw new Error(`ground normal faces down at ${index}`);
  }

  const terrain = new Mesh(built.geometry, new MeshBasicMaterial());
  terrain.position.copy(built.offset);
  terrain.updateMatrixWorld(true);
  const raycaster = new Raycaster();
  raycaster.set(new Vector3(-63.2, 80, -63.8), new Vector3(0, -1, 0));
  const hits = raycaster.intersectObject(terrain, false);
  if (!hits.length) throw new Error("downward ray missed the heightfield");
  const nearest = nearestSample(mesh, hits[0].point.x, hits[0].point.z);
  closeTo(nearest.x, -63, "nearest x");
  closeTo(nearest.z, -64, "nearest z");
  terrain.geometry.dispose();
  const material = terrain.material;
  if (!Array.isArray(material)) material.dispose();
}

// Pin the frame when this module loads. A sign error here would disagree with the top-down map.
assertHeightfieldFrame();
