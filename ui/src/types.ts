export interface BlockInfo {
  id: string;
  name: string;
  category: string;
  rgb: [number, number, number];
  solid: boolean;
}

export interface Shape {
  x: number;
  z: number;
  width: number;
  depth: number;
}

export interface RegionMask {
  kind: string;
  warp?: number;
  scale?: number;
  falloff?: number | null;
  points?: { x: number; z: number }[];
}

export interface Asset {
  id: string;
  filename: string;
  caption: string;
  mime: string;
  width: number;
  height: number;
}

export interface Region {
  id: string;
  name: string;
  color: string;
  vanillaBiome: string;
  shape: Shape;
  mask?: RegionMask;
  brief: { text: string; assetIds: string[] };
  palette: {
    surface: string;
    subsurface: string;
    stone: string;
    water: string;
    allowed: string[];
    strata?: string[];
  };
  terrain: {
    baseHeight: number;
    amplitude: number;
    roughness: number;
    water: boolean;
    style?: string;
    ceiling?: number;
    snowLine?: number | null;
    terrace?: number;
    shore?: number;
    cliff?: number;
  };
  features: {
    trees: { kind: string; density: number; form?: string };
    vegetation: string;
    ores: boolean;
    caves: boolean;
    food?: string;
    crystals?: { enabled: boolean; density: number; radius: number; height: number };
  };
}

export interface Project {
  id: string;
  name: string;
  updatedAt?: string;
  generationFingerprint?: string;
  blendRadius: number;
  world: {
    width: number;
    depth: number;
    seed: number;
    seaLevel: number;
    spawn: { x: number; y: number; z: number };
    border: { size: number; centerX: number; centerZ: number };
  };
  regions: Region[];
  assets: Asset[];
  coverage?: {
    playable: { minX: number; minZ: number; maxX: number; maxZ: number; width: number; depth: number };
    storage: {
      minX: number;
      minZ: number;
      maxX: number;
      maxZ: number;
      chunksX: number;
      chunksZ: number;
      edgeColumns: { west: number; east: number; north: number; south: number };
    };
    edgePolicy?: string;
  };
}

export interface ProjectSummary {
  id: string;
  name: string;
  width: number;
  depth: number;
  seed: number;
  updatedAt?: string;
  regionCount: number;
}

export interface Health {
  ok: boolean;
  formatVersion: number;
  minecraftVersion: string;
  dataVersion: number;
}

export interface MeshData {
  minX: number;
  minZ: number;
  width: number;
  depth: number;
  step: number;
  seaLevel: number;
  heights: number[];
  surface: string[];
  previewNote?: string;
}

export interface OperationResult {
  op: string;
  regionId?: string;
}

export interface JobResult {
  warnings?: unknown;
  worldDir?: string;
  zipPath?: string;
  dataVersion?: number;
  spawn?: { x: number; y: number; z: number };
  spawnChecks?: Record<string, boolean>;
  validation?: {
    ok?: boolean;
    dataVersion?: number;
    levelName?: string;
    spawn?: { x: number; y: number; z: number };
    borderSize?: number;
    chunkCount?: number;
    errors?: unknown[];
  };
}

export interface Job {
  id: string;
  projectId: string;
  type: string;
  status: string;
  progress: number;
  message: string;
  error: string | null;
  result: JobResult | null;
}

export interface AgentInfo {
  id: string;
  name?: string;
  label?: string;
  title?: string;
  available?: boolean;
  enabled?: boolean;
  reason?: string | null;
  imageUnderstanding?: boolean;
  imageNote?: string;
}

export interface AgentMessage {
  role: string;
  text?: string;
  content?: string;
  at?: string;
}

export interface PendingPermission {
  requestId?: string;
  id?: string;
  title?: string;
  detail?: string;
  options?: { optionId?: string; name?: string; kind?: string }[];
}

export interface AgentSession {
  id: string;
  agentId?: string;
  projectId?: string;
  status: string;
  messages?: AgentMessage[];
  pendingPermission?: PendingPermission | null;
  error?: string | null;
  imageUnderstanding?: boolean;
  imageNote?: string;
}

export interface ApiErrorItem {
  code?: string;
  message: string;
  path?: string;
}

export type Tool = "draw" | "move" | "select";

export interface RegionDraft {
  name: string;
  color: string;
  text: string;
  assetIds: string[];
  surface: string;
  subsurface: string;
  stone: string;
  baseHeight: string;
  amplitude: string;
  roughness: string;
  water: boolean;
  trees: string;
  density: string;
  vegetation: string;
  ores: boolean;
  caves: boolean;
  biome: string;
  maskKind: string;
  warp: string;
  scale: string;
  falloff: string;
  points: string;
  style: string;
  ceiling: string;
  snowLine: string;
  terrace: string;
  shore: string;
  cliff: string;
  strata: string;
  treeForm: string;
  food: string;
  crystals: boolean;
  crystalDensity: string;
  crystalRadius: string;
  crystalHeight: string;
}
