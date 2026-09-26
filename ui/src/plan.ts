import { ApiError } from "./api";
import type { AgentInfo, Project, Region, RegionDraft, Shape } from "./types";

export const MAX_SEED = 9007199254740991;

export const BIOMES: { id: string; label: string }[] = [
  { id: "minecraft:plains", label: "Plains" },
  { id: "minecraft:desert", label: "Desert" },
  { id: "minecraft:forest", label: "Forest" },
  { id: "minecraft:taiga", label: "Taiga" },
  { id: "minecraft:savanna", label: "Savanna" },
  { id: "minecraft:jungle", label: "Jungle" },
  { id: "minecraft:ocean", label: "Ocean" },
  { id: "minecraft:beach", label: "Beach" },
  { id: "minecraft:stony_shore", label: "Stony Shore" },
  { id: "minecraft:snowy_plains", label: "Snowy Plains" },
];

export const TREE_KINDS = ["none", "oak", "birch", "spruce", "acacia", "jungle", "cactus"] as const;

export const VEGETATION = ["none", "temperate", "dry", "lush", "cold"] as const;

export const TREE_BLOCKS: Record<string, string[]> = {
  none: [],
  oak: ["minecraft:oak_log", "minecraft:oak_leaves"],
  birch: ["minecraft:birch_log", "minecraft:birch_leaves"],
  spruce: ["minecraft:spruce_log", "minecraft:spruce_leaves"],
  acacia: ["minecraft:acacia_log", "minecraft:acacia_leaves"],
  jungle: ["minecraft:jungle_log", "minecraft:jungle_leaves"],
  cactus: ["minecraft:cactus"],
};

export const VEGETATION_BLOCKS: Record<string, string[]> = {
  none: [],
  temperate: ["minecraft:short_grass"],
  dry: ["minecraft:dead_bush"],
  lush: ["minecraft:short_grass"],
  cold: ["minecraft:short_grass"],
};

const REGION_COLORS = [
  "#7CB342",
  "#E6C36A",
  "#C4523A",
  "#4F7CAC",
  "#8D6E63",
  "#D4A017",
  "#6B8F71",
  "#A67C52",
  "#3E6B58",
  "#B56576",
];

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Request failed.";
}

export function parseInteger(value: string): number | null {
  const trimmed = value.trim();
  if (!/^-?\d+$/.test(trimmed)) return null;
  const number = Number(trimmed);
  if (!Number.isSafeInteger(number)) return null;
  return number;
}

export function parseNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const number = Number(trimmed);
  if (!Number.isFinite(number)) return null;
  return number;
}

export function borderSquare(project: Project): { minX: number; minZ: number; size: number } {
  const size = project.world.border.size;
  const half = size / 2;
  return { minX: -half, minZ: -half, size };
}

export function paintedBounds(project: Project): { minX: number; minZ: number; maxX: number; maxZ: number } {
  const { width, depth } = project.world;
  return { minX: -width / 2, minZ: -depth / 2, maxX: width / 2, maxZ: depth / 2 };
}

export function inclusiveShape(a: { x: number; z: number }, b: { x: number; z: number }): Shape {
  const x = Math.min(a.x, b.x);
  const z = Math.min(a.z, b.z);
  return { x, z, width: Math.abs(a.x - b.x) + 1, depth: Math.abs(a.z - b.z) + 1 };
}

export function clampShape(
  shape: Shape,
  bounds: { minX: number; minZ: number; maxX: number; maxZ: number },
): Shape {
  const x0 = Math.max(shape.x, bounds.minX);
  const z0 = Math.max(shape.z, bounds.minZ);
  const x1 = Math.min(shape.x + shape.width, bounds.maxX);
  const z1 = Math.min(shape.z + shape.depth, bounds.maxZ);
  return { x: x0, z: z0, width: x1 - x0, depth: z1 - z0 };
}

export function clampOrigin(
  x: number,
  z: number,
  shape: Shape,
  bounds: { minX: number; minZ: number; maxX: number; maxZ: number },
): { x: number; z: number } {
  return {
    x: Math.min(Math.max(x, bounds.minX), bounds.maxX - shape.width),
    z: Math.min(Math.max(z, bounds.minZ), bounds.maxZ - shape.depth),
  };
}

export function hitRegion(regions: Region[], x: number, z: number): Region | null {
  for (let index = regions.length - 1; index >= 0; index -= 1) {
    const region = regions[index];
    const shape = region.shape;
    if (x >= shape.x && z >= shape.z && x < shape.x + shape.width && z < shape.z + shape.depth) {
      return region;
    }
  }
  return null;
}

export function nextRegionName(regions: Region[]): string {
  const used = new Set(regions.map((region) => region.name.trim().toLowerCase()));
  let number = regions.length + 1;
  let name = `Region ${number}`;
  while (used.has(name.toLowerCase())) {
    number += 1;
    name = `Region ${number}`;
  }
  return name;
}

export function nextRegionColor(regions: Region[]): string {
  const used = new Set(regions.map((region) => region.color.toLowerCase()));
  return REGION_COLORS.find((color) => !used.has(color.toLowerCase())) ?? REGION_COLORS[regions.length % REGION_COLORS.length];
}

export function normalizeColor(value: string): string {
  return /^#[0-9A-Fa-f]{6}$/.test(value) ? value.toLowerCase() : "#7cb342";
}

export function emptyDraft(): RegionDraft {
  return {
    name: "",
    color: "#7cb342",
    text: "",
    assetIds: [],
    surface: "minecraft:grass_block",
    subsurface: "minecraft:dirt",
    stone: "minecraft:stone",
    baseHeight: "68",
    amplitude: "4",
    roughness: "0.35",
    water: false,
    trees: "oak",
    density: "0.03",
    vegetation: "temperate",
    ores: true,
    caves: true,
    biome: "minecraft:plains",
  };
}

export function draftFromRegion(region: Region): RegionDraft {
  return {
    name: region.name,
    color: normalizeColor(region.color),
    text: region.brief?.text ?? "",
    assetIds: [...(region.brief?.assetIds ?? [])],
    surface: region.palette.surface,
    subsurface: region.palette.subsurface,
    stone: region.palette.stone,
    baseHeight: String(region.terrain.baseHeight),
    amplitude: String(region.terrain.amplitude),
    roughness: String(region.terrain.roughness),
    water: Boolean(region.terrain.water),
    trees: region.features.trees.kind,
    density: String(region.features.trees.density),
    vegetation: region.features.vegetation,
    ores: Boolean(region.features.ores),
    caves: Boolean(region.features.caves),
    biome: region.vanillaBiome,
  };
}

export function allowedForDraft(region: Region, draft: RegionDraft): string[] {
  const extra = [
    draft.surface,
    draft.subsurface,
    draft.stone,
    region.palette.water,
    ...(TREE_BLOCKS[draft.trees] ?? []),
    ...(VEGETATION_BLOCKS[draft.vegetation] ?? []),
  ];
  return [...new Set([...region.palette.allowed, ...extra])];
}

export function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === "string") return item;
    if (item && typeof item === "object" && "message" in item) {
      return String((item as { message: unknown }).message);
    }
    return JSON.stringify(item);
  });
}

export function validationSummary(validation: unknown): string {
  if (!validation || typeof validation !== "object") return "No validation report.";
  const report = validation as {
    ok?: boolean;
    dataVersion?: number;
    levelName?: string;
    spawn?: { x?: number; y?: number; z?: number };
    borderSize?: number;
    chunkCount?: number;
    errors?: unknown[];
  };
  const errors = textList(report.errors);
  const spawn = report.spawn;
  const parts = [
    report.ok === false || errors.length > 0 ? "Invalid" : "Valid",
    report.dataVersion != null ? `dataVersion ${report.dataVersion}` : null,
    report.levelName ? String(report.levelName) : null,
    report.chunkCount != null ? `${report.chunkCount} chunks` : null,
    spawn ? `spawn ${spawn.x ?? "?"}, ${spawn.y ?? "?"}, ${spawn.z ?? "?"}` : null,
    report.borderSize != null ? `border ${report.borderSize}` : null,
    errors.length ? errors.join("; ") : null,
  ];
  return parts.filter((part): part is string => Boolean(part)).join(" · ");
}

export function isAgentAvailable(agent: AgentInfo): boolean {
  if (typeof agent.available === "boolean") return agent.available;
  if (typeof agent.enabled === "boolean") return agent.enabled;
  return true;
}

export function agentLabel(agent: AgentInfo): string {
  return agent.label || agent.name || agent.title || agent.id;
}

export function defaultAgentId(agents: AgentInfo[]): string {
  const available = agents.filter(isAgentAvailable);
  return (
    available.find((agent) => agent.id === "grok")?.id ||
    available.find((agent) => agent.id === "test")?.id ||
    available[0]?.id ||
    agents[0]?.id ||
    ""
  );
}

export function createProjectError(input: {
  name: string;
  width: string;
  depth: string;
  seed: string;
  spawnX: string;
  spawnZ: string;
}): string | null {
  const name = input.name.trim();
  if (name.length < 1 || name.length > 60) return "Name must be 1 to 60 characters.";
  const width = parseInteger(input.width);
  const depth = parseInteger(input.depth);
  const seed = parseInteger(input.seed);
  const spawnX = parseInteger(input.spawnX);
  const spawnZ = parseInteger(input.spawnZ);
  const dimensionOk = (value: number | null) =>
    value !== null && value % 16 === 0 && value >= 32 && value <= 512;
  if (!dimensionOk(width) || !dimensionOk(depth)) {
    return "Width and depth must be multiples of 16 from 32 to 512.";
  }
  if (seed === null || seed < 0 || seed > MAX_SEED) return "Seed must be an integer from 0 to 2^53-1.";
  if (spawnX === null || spawnZ === null) return "Spawn must be an integer x and z.";
  const minX = -(width as number) / 2;
  const maxX = (width as number) / 2;
  const minZ = -(depth as number) / 2;
  const maxZ = (depth as number) / 2;
  if (spawnX < minX || spawnX >= maxX || spawnZ < minZ || spawnZ >= maxZ) {
    return "Spawn must lie inside the world rectangle.";
  }
  return null;
}
