import { ApiError } from "./api";
import type { AgentInfo, Project, Region, RegionDraft, Shape } from "./types";

export const MAX_SEED = 9007199254740991;
export const MIN_WORLD = 32;
export const MAX_WORLD = 4096;

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
  { id: "minecraft:birch_forest", label: "Birch Forest" },
  { id: "minecraft:dark_forest", label: "Dark Forest" },
  { id: "minecraft:snowy_taiga", label: "Snowy Taiga" },
  { id: "minecraft:old_growth_spruce_taiga", label: "Old Growth Spruce Taiga" },
  { id: "minecraft:sparse_jungle", label: "Sparse Jungle" },
  { id: "minecraft:bamboo_jungle", label: "Bamboo Jungle" },
  { id: "minecraft:badlands", label: "Badlands" },
  { id: "minecraft:wooded_badlands", label: "Wooded Badlands" },
  { id: "minecraft:eroded_badlands", label: "Eroded Badlands" },
  { id: "minecraft:cold_ocean", label: "Cold Ocean" },
  { id: "minecraft:frozen_ocean", label: "Frozen Ocean" },
  { id: "minecraft:lukewarm_ocean", label: "Lukewarm Ocean" },
  { id: "minecraft:warm_ocean", label: "Warm Ocean" },
  { id: "minecraft:snowy_slopes", label: "Snowy Slopes" },
  { id: "minecraft:grove", label: "Grove" },
  { id: "minecraft:jagged_peaks", label: "Jagged Peaks" },
  { id: "minecraft:frozen_peaks", label: "Frozen Peaks" },
  { id: "minecraft:stony_peaks", label: "Stony Peaks" },
  { id: "minecraft:windswept_hills", label: "Windswept Hills" },
  { id: "minecraft:windswept_forest", label: "Windswept Forest" },
  { id: "minecraft:meadow", label: "Meadow" },
];

export const TERRAIN_STYLES = ["classic", "rolling", "dunes", "mesa", "plateau", "alpine", "cliff"] as const;
export const TREE_FORMS = ["classic", "varied", "clustered", "emergent"] as const;
export const FOOD_KINDS = ["none", "berries", "melon", "mixed"] as const;
export const MASK_KINDS = ["rect", "ellipse", "blob", "polygon"] as const;

export const CRYSTAL_BLOCKS = [
  "minecraft:packed_ice",
  "minecraft:blue_ice",
  "minecraft:ice",
  "minecraft:calcite",
  "minecraft:snow_block",
];

export const FOOD_BLOCK_IDS: Record<string, string[]> = {
  none: [],
  berries: ["minecraft:sweet_berry_bush"],
  melon: ["minecraft:melon"],
  mixed: ["minecraft:sweet_berry_bush", "minecraft:melon", "minecraft:pumpkin", "minecraft:sugar_cane"],
};

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

export function storageFor(width: number, depth: number): {
  playableMin: number;
  playableMax: number;
  playableSize: number;
  storageMin: number;
  storageMax: number;
  chunks: number;
  edge: number;
} | null {
  if (width < MIN_WORLD || depth < MIN_WORLD || width > MAX_WORLD || depth > MAX_WORLD) return null;
  const size = Math.max(width, depth);
  const playableMin = -Math.floor(size / 2);
  const playableMax = playableMin + size;
  const chunkMin = Math.floor(playableMin / 16);
  const chunkMax = Math.floor((playableMax - 1) / 16);
  const storageMin = chunkMin * 16;
  const storageMax = (chunkMax + 1) * 16;
  return {
    playableMin,
    playableMax,
    playableSize: size,
    storageMin,
    storageMax,
    chunks: chunkMax - chunkMin + 1,
    edge: playableMin - storageMin,
  };
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
    maskKind: "rect",
    warp: "0",
    scale: "64",
    falloff: "",
    points: "",
    style: "classic",
    ceiling: "",
    snowLine: "",
    terrace: "4",
    shore: "0",
    cliff: "0",
    strata: "",
    treeForm: "classic",
    food: "none",
    crystals: false,
    crystalDensity: "0.25",
    crystalRadius: "4",
    crystalHeight: "10",
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
    maskKind: region.mask?.kind || "rect",
    warp: String(region.mask?.warp ?? 0),
    scale: String(region.mask?.scale ?? 64),
    falloff: region.mask?.falloff == null ? "" : String(region.mask.falloff),
    points: (region.mask?.points ?? []).map((point) => `${point.x} ${point.z}`).join("\n"),
    style: region.terrain.style || "classic",
    ceiling: region.terrain.ceiling == null ? "" : String(region.terrain.ceiling),
    snowLine: region.terrain.snowLine == null ? "" : String(region.terrain.snowLine),
    terrace: String(region.terrain.terrace ?? 4),
    shore: String(region.terrain.shore ?? 0),
    cliff: String(region.terrain.cliff ?? 0),
    strata: (region.palette.strata ?? []).join(", "),
    treeForm: region.features.trees.form || "classic",
    food: region.features.food || "none",
    crystals: Boolean(region.features.crystals?.enabled),
    crystalDensity: String(region.features.crystals?.density ?? 0.25),
    crystalRadius: String(region.features.crystals?.radius ?? 4),
    crystalHeight: String(region.features.crystals?.height ?? 10),
  };
}

export function parsePoints(value: string): { x: number; z: number }[] | null {
  const points = [];
  for (const line of value.split(/\n+/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/[\s,]+/);
    if (parts.length < 2) return null;
    const x = parseInteger(parts[0]);
    const z = parseInteger(parts[1]);
    if (x === null || z === null) return null;
    points.push({ x, z });
  }
  return points;
}

export function allowedForDraft(region: Region, draft: RegionDraft): string[] {
  const extra = [
    draft.surface,
    draft.subsurface,
    draft.stone,
    region.palette.water,
    ...(TREE_BLOCKS[draft.trees] ?? []),
    ...(VEGETATION_BLOCKS[draft.vegetation] ?? []),
    ...(FOOD_BLOCK_IDS[draft.food] ?? []),
    ...(draft.crystals ? CRYSTAL_BLOCKS : []),
    ...draft.strata
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
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
    value !== null && value >= MIN_WORLD && value <= MAX_WORLD;
  if (!dimensionOk(width) || !dimensionOk(depth)) {
    return "Width and depth must be integers from 32 to 4096.";
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
