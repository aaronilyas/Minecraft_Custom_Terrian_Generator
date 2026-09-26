from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

FORMAT_VERSION = 1
MINECRAFT_VERSION = "1.21.4"
DATA_VERSION = 4189
MIN_SIZE = 32
MAX_SIZE = 4096
MIN_REGION = 4
MAX_SEED = 9007199254740991
MIN_Y = -64
MAX_Y = 320
MAX_BASE_HEIGHT = 256
MAX_AMPLITUDE = 96
MAX_CEILING = 320
COMPACT_CELL_LIMIT = 512 * 512

VANILLA_BIOMES = (
    "minecraft:plains",
    "minecraft:desert",
    "minecraft:forest",
    "minecraft:birch_forest",
    "minecraft:old_growth_birch_forest",
    "minecraft:dark_forest",
    "minecraft:taiga",
    "minecraft:snowy_taiga",
    "minecraft:old_growth_spruce_taiga",
    "minecraft:savanna",
    "minecraft:jungle",
    "minecraft:sparse_jungle",
    "minecraft:bamboo_jungle",
    "minecraft:badlands",
    "minecraft:wooded_badlands",
    "minecraft:eroded_badlands",
    "minecraft:ocean",
    "minecraft:cold_ocean",
    "minecraft:frozen_ocean",
    "minecraft:lukewarm_ocean",
    "minecraft:warm_ocean",
    "minecraft:beach",
    "minecraft:stony_shore",
    "minecraft:snowy_plains",
    "minecraft:snowy_slopes",
    "minecraft:grove",
    "minecraft:jagged_peaks",
    "minecraft:frozen_peaks",
    "minecraft:stony_peaks",
    "minecraft:windswept_hills",
    "minecraft:windswept_forest",
    "minecraft:meadow",
)
TREE_KINDS = ("none", "oak", "birch", "spruce", "acacia", "jungle", "cactus")
TREE_FORMS = ("classic", "varied", "clustered", "emergent")
VEGETATION = ("none", "temperate", "dry", "lush", "cold")
TERRAIN_STYLES = ("classic", "rolling", "dunes", "mesa", "plateau", "alpine", "cliff")
FOOD_KINDS = ("none", "berries", "melon", "mixed")
MASK_KINDS = ("rect", "ellipse", "polygon", "blob")
CRYSTAL_BLOCKS = (
    "minecraft:packed_ice",
    "minecraft:blue_ice",
    "minecraft:ice",
    "minecraft:calcite",
    "minecraft:snow_block",
)
FOOD_BLOCKS = {
    "none": (),
    "berries": ("minecraft:sweet_berry_bush",),
    "melon": ("minecraft:melon",),
    "mixed": (
        "minecraft:sweet_berry_bush",
        "minecraft:melon",
        "minecraft:pumpkin",
        "minecraft:sugar_cane",
    ),
}
TREE_BLOCKS = {
    "none": (),
    "oak": ("minecraft:oak_log", "minecraft:oak_leaves"),
    "birch": ("minecraft:birch_log", "minecraft:birch_leaves"),
    "spruce": ("minecraft:spruce_log", "minecraft:spruce_leaves"),
    "acacia": ("minecraft:acacia_log", "minecraft:acacia_leaves"),
    "jungle": ("minecraft:jungle_log", "minecraft:jungle_leaves"),
    "cactus": ("minecraft:cactus",),
}
VEGETATION_BLOCKS = {
    "none": (),
    "temperate": ("minecraft:short_grass",),
    "dry": ("minecraft:dead_bush",),
    "lush": ("minecraft:short_grass",),
    "cold": ("minecraft:short_grass",),
}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def is_uuid(value: str) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value))


def err(code: str, message: str, path: str = "", index: int | None = None) -> dict:
    row = {"code": code, "message": message, "path": path}
    if index is not None:
        row["index"] = index
    return row


def default_terrain() -> dict:
    return {
        "vanillaBiome": "minecraft:plains",
        "palette": {
            "surface": "minecraft:grass_block",
            "subsurface": "minecraft:dirt",
            "stone": "minecraft:stone",
            "water": "minecraft:water",
            "allowed": [
                "minecraft:grass_block",
                "minecraft:dirt",
                "minecraft:stone",
                "minecraft:water",
                "minecraft:sand",
                "minecraft:oak_log",
                "minecraft:oak_leaves",
                "minecraft:short_grass",
                "minecraft:dandelion",
                "minecraft:poppy",
            ],
        },
        "terrain": {
            "baseHeight": 68,
            "amplitude": 4,
            "roughness": 0.35,
            "water": False,
        },
        "features": {
            "trees": {"kind": "oak", "density": 0.03},
            "vegetation": "temperate",
            "ores": True,
            "caves": True,
        },
    }


def make_border(width: int, depth: int, previous: dict | None = None) -> dict:
    border = {
        "centerX": 0,
        "centerZ": 0,
        "size": max(width, depth),
        "warningBlocks": 5,
        "warningTime": 15,
        "damagePerBlock": 0.2,
        "safeZone": 5,
    }
    if previous:
        for key in ("warningBlocks", "warningTime", "damagePerBlock", "safeZone"):
            if key in previous:
                border[key] = previous[key]
    return border


def new_project(
    name: str,
    width: int,
    depth: int,
    seed: int,
    spawn_x: int = 0,
    spawn_z: int = 0,
    project_id: str | None = None,
) -> dict:
    stamp = now_iso()
    return {
        "formatVersion": FORMAT_VERSION,
        "id": project_id or new_id(),
        "name": name.strip(),
        "createdAt": stamp,
        "updatedAt": stamp,
        "minecraft": {
            "edition": "java",
            "version": MINECRAFT_VERSION,
            "dataVersion": DATA_VERSION,
        },
        "world": {
            "width": width,
            "depth": depth,
            "minY": MIN_Y,
            "maxY": MAX_Y,
            "seaLevel": 63,
            "seed": seed,
            "spawn": {"x": spawn_x, "y": 64, "z": spawn_z},
            "border": make_border(width, depth),
        },
        "blendRadius": 8,
        "defaultTerrain": default_terrain(),
        "regions": [],
        "assets": [],
    }


def _axis_span(size: int) -> tuple[int, int]:
    """Inclusive-exclusive span of `size` blocks centered on 0.

    Even sizes match the historical `[-size/2, size/2)` square. Odd sizes keep
    the extra block on the positive side so the count stays exact.
    """
    origin = -(int(size) // 2)
    return origin, origin + int(size)


def user_rectangle(project: dict) -> tuple[int, int, int, int]:
    """Inclusive-exclusive bounds where regions may be painted: min_x, min_z, max_x, max_z."""
    width = int(project["world"]["width"])
    depth = int(project["world"]["depth"])
    min_x, max_x = _axis_span(width)
    min_z, max_z = _axis_span(depth)
    return (min_x, min_z, max_x, max_z)


def border_square(project: dict) -> tuple[int, int, int, int]:
    """Playable world-border square. This is the generation domain, not chunk storage."""
    size = int(project["world"]["border"]["size"])
    min_block, max_block = _axis_span(size)
    return (min_block, min_block, max_block, max_block)


def storage_span(min_block: int, max_exclusive: int) -> dict:
    """Chunk-aligned cover of a playable interval.

    Minecraft chunks are 16 blocks. The chunk index uses floor division, so
    negative coordinates stay correct: block -1500 is chunk -94, and that chunk
    starts at -1504. Columns between the chunk edge and the playable edge are
    outside the world border. They are generated only so the chunk is complete.
    """
    if max_exclusive <= min_block:
        raise ValueError("playable interval is empty")
    chunk_min = int(min_block) // 16
    chunk_max = (int(max_exclusive) - 1) // 16
    store_min = chunk_min * 16
    store_max = (chunk_max + 1) * 16
    return {
        "min": store_min,
        "max": store_max,
        "chunkMin": chunk_min,
        "chunkMax": chunk_max,
        "chunks": chunk_max - chunk_min + 1,
        "edgeLow": int(min_block) - store_min,
        "edgeHigh": store_max - int(max_exclusive),
    }


def world_coverage(project: dict) -> dict:
    """Playable border square versus the chunk rectangle that export must write.

    Edge policy is continuation: padding columns use the same height blend and
    surface rules as the rest of the map, but they do not receive caves, ores,
    trees, vegetation, crystals, food, or the spawn camp. The world border size
    stays max(width, depth). It is not expanded to the chunk span.
    """
    min_x, min_z, max_x, max_z = border_square(project)
    span_x = storage_span(min_x, max_x)
    span_z = storage_span(min_z, max_z)
    painted_x0, painted_z0, painted_x1, painted_z1 = user_rectangle(project)
    return {
        "painted": {
            "minX": painted_x0,
            "minZ": painted_z0,
            "maxX": painted_x1,
            "maxZ": painted_z1,
            "width": painted_x1 - painted_x0,
            "depth": painted_z1 - painted_z0,
        },
        "playable": {
            "minX": min_x,
            "minZ": min_z,
            "maxX": max_x,
            "maxZ": max_z,
            "width": max_x - min_x,
            "depth": max_z - min_z,
        },
        "storage": {
            "minX": span_x["min"],
            "minZ": span_z["min"],
            "maxX": span_x["max"],
            "maxZ": span_z["max"],
            "chunkMinX": span_x["chunkMin"],
            "chunkMaxX": span_x["chunkMax"],
            "chunkMinZ": span_z["chunkMin"],
            "chunkMaxZ": span_z["chunkMax"],
            "chunksX": span_x["chunks"],
            "chunksZ": span_z["chunks"],
            "edgeColumns": {
                "west": span_x["edgeLow"],
                "east": span_x["edgeHigh"],
                "north": span_z["edgeLow"],
                "south": span_z["edgeHigh"],
            },
        },
        "edgePolicy": "continuation",
    }


def uses_compact_storage(project: dict) -> bool:
    """Worlds above 512×512 are generated from height fields, not a full block volume."""
    mode = (project.get("world") or {}).get("storageMode")
    if mode == "compact":
        return True
    if mode == "voxel":
        return False
    min_x, min_z, max_x, max_z = border_square(project)
    return (max_x - min_x) * (max_z - min_z) > COMPACT_CELL_LIMIT


def dimension_message() -> str:
    return f"Width and depth must be integers from {MIN_SIZE} to {MAX_SIZE}."


def dimension_ok(width: Any, depth: Any) -> bool:
    return (
        _is_int(width)
        and _is_int(depth)
        and MIN_SIZE <= int(width) <= MAX_SIZE
        and MIN_SIZE <= int(depth) <= MAX_SIZE
    )


def generation_inputs(project: dict) -> dict:
    regions = []
    for region in project.get("regions", []):
        row = {
            "id": region["id"],
            "shape": region["shape"],
            "vanillaBiome": region["vanillaBiome"],
            "palette": region["palette"],
            "terrain": region["terrain"],
            "features": region["features"],
        }
        if "mask" in region:
            row["mask"] = region["mask"]
        regions.append(row)
    world = project["world"]
    return {
        "width": world["width"],
        "depth": world["depth"],
        "seaLevel": world["seaLevel"],
        "seed": world["seed"],
        "borderSize": world["border"]["size"],
        "blendRadius": project["blendRadius"],
        "defaultTerrain": project["defaultTerrain"],
        "regions": regions,
    }


def generation_fingerprint(project: dict) -> str:
    raw = json.dumps(generation_inputs(project), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("-"):
            digits = text[1:]
            sign = -1
        else:
            digits = text
            sign = 1
        if digits.isdigit():
            return sign * int(digits)
    return None


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def coerce_shape(shape: Any) -> Any:
    if not isinstance(shape, dict):
        return shape
    updated = dict(shape)
    for key in ("x", "z", "width", "depth"):
        if key in updated:
            coerced = coerce_int(updated[key])
            if coerced is not None:
                updated[key] = coerced
    return updated


def _rect_inside(shape: dict, bounds: tuple[int, int, int, int]) -> bool:
    min_x, min_z, max_x, max_z = bounds
    x = shape["x"]
    z = shape["z"]
    return (
        x >= min_x
        and z >= min_z
        and x + shape["width"] <= max_x
        and z + shape["depth"] <= max_z
    )


def validate_shape(shape: Any, path: str) -> list[dict]:
    errors = []
    if not isinstance(shape, dict):
        return [err("schema", "Shape must be an object.", path)]
    for key in ("x", "z", "width", "depth"):
        if key not in shape or not _is_int(shape[key]):
            errors.append(err("schema", f"{key} must be an integer.", f"{path}.{key}"))
    if errors:
        return errors
    if shape["width"] < MIN_REGION or shape["depth"] < MIN_REGION:
        errors.append(err("out_of_bounds", f"Regions must be at least {MIN_REGION} blocks on each side.", path))
    return errors


def _validate_palette(palette: Any, registry, path: str) -> list[dict]:
    errors = []
    if not isinstance(palette, dict):
        return [err("schema", "Palette must be an object.", path)]
    for key in ("surface", "subsurface", "stone", "water", "allowed"):
        if key not in palette:
            errors.append(err("schema", f"Missing palette.{key}.", f"{path}.{key}"))
    if errors:
        return errors
    allowed = palette["allowed"]
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        return [err("schema", "palette.allowed must be a list of block ids.", f"{path}.allowed")]
    for block_id in allowed:
        if not registry.known(block_id) or block_id not in registry.placeable_ids():
            errors.append(err("invalid_block", f"Unknown or non-placeable block {block_id}.", f"{path}.allowed"))
    allowed_keys = {"surface", "subsurface", "stone", "water", "allowed", "strata"}
    unknown = [key for key in palette.keys() if key not in allowed_keys]
    if unknown:
        errors.append(err("schema", f"Unknown palette field {unknown[0]}.", path))
    strata = palette.get("strata", [])
    if strata is None:
        strata = []
    if "strata" in palette and not isinstance(strata, list):
        errors.append(err("schema", "palette.strata must be a list of block ids.", f"{path}.strata"))
    elif isinstance(strata, list):
        for block_id in strata:
            if not isinstance(block_id, str) or not registry.known(block_id) or not registry.is_solid(block_id):
                errors.append(err("invalid_block", f"Strata block {block_id} must be a known solid block.", f"{path}.strata"))
            elif isinstance(allowed, list) and block_id not in allowed:
                errors.append(err("invalid_block", f"Strata block {block_id} must be included in allowed.", f"{path}.strata"))
    for key in ("surface", "subsurface", "stone"):
        block_id = palette[key]
        if not isinstance(block_id, str) or not registry.known(block_id):
            errors.append(err("invalid_block", f"Unknown block {block_id}.", f"{path}.{key}"))
        elif not registry.is_solid(block_id):
            errors.append(err("invalid_block", f"{key} must be a solid block.", f"{path}.{key}"))
        elif block_id not in allowed:
            errors.append(err("invalid_block", f"{key} must be included in allowed.", f"{path}.{key}"))
    water = palette["water"]
    if not isinstance(water, str) or not registry.known(water) or water not in registry.placeable_ids():
        errors.append(err("invalid_block", f"Unknown water block {water}.", f"{path}.water"))
    elif water not in allowed:
        errors.append(err("invalid_block", "water must be included in allowed.", f"{path}.water"))
    return errors


def _validate_terrain(terrain: Any, path: str) -> list[dict]:
    if not isinstance(terrain, dict):
        return [err("schema", "Terrain must be an object.", path)]
    errors = []
    base = terrain.get("baseHeight")
    amplitude = terrain.get("amplitude")
    roughness = terrain.get("roughness")
    water = terrain.get("water")
    allowed_keys = {"baseHeight", "amplitude", "roughness", "water", "style", "ceiling", "snowLine", "terrace", "shore", "cliff"}
    unknown = [key for key in terrain.keys() if key not in allowed_keys]
    if unknown:
        errors.append(err("schema", f"Unknown terrain field {unknown[0]}.", path))
    if not _is_int(base) or not 8 <= base <= MAX_BASE_HEIGHT:
        errors.append(err("schema", f"baseHeight must be an integer from 8 to {MAX_BASE_HEIGHT}.", f"{path}.baseHeight"))
    if not _is_int(amplitude) or not 0 <= amplitude <= MAX_AMPLITUDE:
        errors.append(err("schema", f"amplitude must be an integer from 0 to {MAX_AMPLITUDE}.", f"{path}.amplitude"))
    if isinstance(roughness, bool) or not isinstance(roughness, (int, float)) or not 0 <= float(roughness) <= 1:
        errors.append(err("schema", "roughness must be a number from 0 to 1.", f"{path}.roughness"))
    if not isinstance(water, bool):
        errors.append(err("schema", "water must be true or false.", f"{path}.water"))
    style = terrain.get("style", "classic")
    if style not in TERRAIN_STYLES:
        errors.append(err("schema", f"Unknown terrain style {style}.", f"{path}.style"))
    if "ceiling" in terrain and terrain.get("ceiling") is not None and (
        not _is_int(terrain.get("ceiling")) or not 8 <= terrain["ceiling"] <= MAX_CEILING
    ):
        errors.append(err("schema", f"ceiling must be an integer from 8 to {MAX_CEILING}.", f"{path}.ceiling"))
    if "snowLine" in terrain and terrain.get("snowLine") is not None:
        snow_line = terrain.get("snowLine")
        if not _is_int(snow_line) or not MIN_Y <= snow_line <= MAX_CEILING:
            errors.append(err("schema", "snowLine must be an integer height or null.", f"{path}.snowLine"))
    for key, limit in (("terrace", 16), ("shore", 48), ("cliff", 48)):
        if key in terrain and (not _is_int(terrain.get(key)) or not 0 <= terrain[key] <= limit):
            errors.append(err("schema", f"{key} must be an integer from 0 to {limit}.", f"{path}.{key}"))
    return errors


def _validate_features(features: Any, palette: dict | None, path: str) -> list[dict]:
    if not isinstance(features, dict):
        return [err("schema", "Features must be an object.", path)]
    errors = []
    allowed_keys = {"trees", "vegetation", "ores", "caves", "crystals", "food"}
    unknown = [key for key in features.keys() if key not in allowed_keys]
    if unknown:
        errors.append(err("schema", f"Unknown feature field {unknown[0]}.", path))
    trees = features.get("trees")
    if not isinstance(trees, dict):
        errors.append(err("schema", "features.trees must be an object.", f"{path}.trees"))
    else:
        tree_keys = {"kind", "density", "form"}
        unknown_tree = [key for key in trees.keys() if key not in tree_keys]
        if unknown_tree:
            errors.append(err("schema", f"Unknown tree field {unknown_tree[0]}.", f"{path}.trees"))
        kind = trees.get("kind")
        density = trees.get("density")
        form = trees.get("form", "classic")
        if kind not in TREE_KINDS:
            errors.append(err("schema", f"Unknown tree kind {kind}.", f"{path}.trees.kind"))
        if form not in TREE_FORMS:
            errors.append(err("schema", f"Unknown tree form {form}.", f"{path}.trees.form"))
        if isinstance(density, bool) or not isinstance(density, (int, float)) or not 0 <= float(density) <= 1:
            errors.append(err("schema", "tree density must be a number from 0 to 1.", f"{path}.trees.density"))
        if kind in TREE_BLOCKS and palette and isinstance(palette.get("allowed"), list):
            missing = [block_id for block_id in TREE_BLOCKS[kind] if block_id not in palette["allowed"]]
            if missing:
                errors.append(
                    err(
                        "invalid_block",
                        f"Tree kind {kind} requires {', '.join(missing)} in the allowed palette.",
                        f"{path}.trees.kind",
                    )
                )
    vegetation = features.get("vegetation")
    if vegetation not in VEGETATION:
        errors.append(err("schema", f"Unknown vegetation {vegetation}.", f"{path}.vegetation"))
    elif palette and isinstance(palette.get("allowed"), list):
        missing = [block_id for block_id in VEGETATION_BLOCKS[vegetation] if block_id not in palette["allowed"]]
        if missing:
            errors.append(
                err(
                    "invalid_block",
                    f"Vegetation {vegetation} requires {', '.join(missing)} in the allowed palette.",
                    f"{path}.vegetation",
                )
            )
    for key in ("ores", "caves"):
        if not isinstance(features.get(key), bool):
            errors.append(err("schema", f"{key} must be true or false.", f"{path}.{key}"))
    food = features.get("food", "none")
    if "food" in features and food not in FOOD_KINDS:
        errors.append(err("schema", f"Unknown food setting {food}.", f"{path}.food"))
    elif food in FOOD_BLOCKS and palette and isinstance(palette.get("allowed"), list):
        required = FOOD_BLOCKS[food]
        if required and not any(block_id in palette["allowed"] for block_id in required):
            errors.append(
                err(
                    "invalid_block",
                    f"Food setting {food} requires one of {', '.join(required)} in the allowed palette.",
                    f"{path}.food",
                )
            )
    if "crystals" in features:
        errors.extend(_validate_crystals(features.get("crystals"), palette, f"{path}.crystals"))
    return errors


def _validate_crystals(crystals: Any, palette: dict | None, path: str) -> list[dict]:
    if not isinstance(crystals, dict):
        return [err("schema", "crystals must be an object.", path)]
    errors = []
    allowed_keys = {"enabled", "density", "radius", "height"}
    unknown = [key for key in crystals.keys() if key not in allowed_keys]
    if unknown:
        errors.append(err("schema", f"Unknown crystal field {unknown[0]}.", path))
    if not isinstance(crystals.get("enabled"), bool):
        errors.append(err("schema", "crystals.enabled must be true or false.", f"{path}.enabled"))
    density = crystals.get("density", 0.2)
    if isinstance(density, bool) or not isinstance(density, (int, float)) or not 0 <= float(density) <= 1:
        errors.append(err("schema", "crystal density must be a number from 0 to 1.", f"{path}.density"))
    radius = crystals.get("radius", 4)
    height = crystals.get("height", 10)
    if not _is_int(radius) or not 1 <= radius <= 8:
        errors.append(err("schema", "crystal radius must be an integer from 1 to 8.", f"{path}.radius"))
    if not _is_int(height) or not 2 <= height <= 24:
        errors.append(err("schema", "crystal height must be an integer from 2 to 24.", f"{path}.height"))
    if crystals.get("enabled") and palette and isinstance(palette.get("allowed"), list):
        if not any(block_id in palette["allowed"] for block_id in CRYSTAL_BLOCKS):
            errors.append(
                err(
                    "invalid_block",
                    "Ice crystals require packed ice, blue ice, ice, calcite, or snow block in the allowed palette.",
                    path,
                )
            )
    return errors


def _validate_mask(mask: Any, shape: dict | None, path: str) -> list[dict]:
    if mask is None:
        return []
    if not isinstance(mask, dict):
        return [err("schema", "Mask must be an object.", path)]
    errors = []
    allowed_keys = {"kind", "warp", "scale", "falloff", "points"}
    unknown = [key for key in mask.keys() if key not in allowed_keys]
    if unknown:
        errors.append(err("schema", f"Unknown mask field {unknown[0]}.", path))
    kind = mask.get("kind", "rect")
    if kind not in MASK_KINDS:
        errors.append(err("schema", f"Unknown mask kind {kind}.", f"{path}.kind"))
    warp = mask.get("warp", 0)
    scale = mask.get("scale", 64)
    if not _is_int(warp) or not 0 <= warp <= 320:
        errors.append(err("schema", "mask.warp must be an integer from 0 to 320.", f"{path}.warp"))
    if not _is_int(scale) or not 8 <= scale <= 256:
        errors.append(err("schema", "mask.scale must be an integer from 8 to 256.", f"{path}.scale"))
    if "falloff" in mask and mask.get("falloff") is not None:
        falloff = mask.get("falloff")
        if not _is_int(falloff) or not 0 <= falloff <= 32:
            errors.append(err("schema", "mask.falloff must be an integer from 0 to 32.", f"{path}.falloff"))
    if kind == "polygon":
        points = mask.get("points")
        if not isinstance(points, list) or len(points) < 3:
            errors.append(err("schema", "A polygon mask needs at least 3 points.", f"{path}.points"))
        elif isinstance(shape, dict) and all(key in shape for key in ("x", "z", "width", "depth")):
            for index, point in enumerate(points):
                px, pz = _point_xz(point)
                if px is None or pz is None:
                    errors.append(err("schema", "Polygon points must be {x, z} or [x, z].", f"{path}.points[{index}]"))
                    continue
                if not (shape["x"] <= px < shape["x"] + shape["width"] and shape["z"] <= pz < shape["z"] + shape["depth"]):
                    errors.append(err("out_of_bounds", "Polygon points must lie inside the region rectangle.", f"{path}.points[{index}]"))
    return errors


def _point_xz(point: Any) -> tuple[int | None, int | None]:
    if isinstance(point, dict):
        return coerce_int(point.get("x")), coerce_int(point.get("z"))
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return coerce_int(point[0]), coerce_int(point[1])
    return None, None


def _validate_profile(profile: Any, registry, path: str) -> list[dict]:
    if not isinstance(profile, dict):
        return [err("schema", "Terrain profile must be an object.", path)]
    errors = []
    biome = profile.get("vanillaBiome")
    if biome not in VANILLA_BIOMES:
        errors.append(err("schema", f"Unsupported vanilla biome {biome}.", f"{path}.vanillaBiome"))
    errors.extend(_validate_palette(profile.get("palette"), registry, f"{path}.palette"))
    errors.extend(_validate_terrain(profile.get("terrain"), f"{path}.terrain"))
    errors.extend(_validate_features(profile.get("features"), profile.get("palette"), f"{path}.features"))
    return errors


def _validate_brief(brief: Any, asset_ids: set[str], path: str) -> list[dict]:
    if not isinstance(brief, dict):
        return [err("schema", "Brief must be an object.", path)]
    errors = []
    text = brief.get("text", "")
    if not isinstance(text, str) or len(text) > 4000:
        errors.append(err("schema", "Brief text must be a string of at most 4000 characters.", f"{path}.text"))
    asset_list = brief.get("assetIds", [])
    if not isinstance(asset_list, list):
        errors.append(err("schema", "assetIds must be a list.", f"{path}.assetIds"))
    else:
        for asset_id in asset_list:
            if not is_uuid(asset_id) or asset_id not in asset_ids:
                errors.append(err("unknown_asset", f"Unknown reference image {asset_id}.", f"{path}.assetIds"))
    return errors


def validate_project(project: dict, registry) -> list[dict]:
    errors: list[dict] = []
    if not isinstance(project, dict):
        return [err("schema", "Project must be an object.")]
    if project.get("formatVersion") != FORMAT_VERSION:
        errors.append(err("schema", "Unsupported formatVersion.", "formatVersion"))
    if not is_uuid(str(project.get("id", ""))):
        errors.append(err("schema", "Project id must be a UUID.", "id"))
    name = project.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        errors.append(err("schema", "Name must be 1 to 60 characters.", "name"))
    minecraft = project.get("minecraft") or {}
    if minecraft.get("version") != MINECRAFT_VERSION or minecraft.get("dataVersion") != DATA_VERSION:
        errors.append(err("schema", f"This app only writes Minecraft Java {MINECRAFT_VERSION}.", "minecraft"))
    world = project.get("world")
    if not isinstance(world, dict):
        return errors + [err("schema", "Missing world.", "world")]
    width = world.get("width")
    depth = world.get("depth")
    if not dimension_ok(width, depth):
        errors.append(err("invalid_dimension", dimension_message(), "world"))
    storage_mode = world.get("storageMode", "auto")
    if storage_mode not in {"auto", "voxel", "compact"}:
        errors.append(err("schema", "storageMode must be auto, voxel, or compact.", "world.storageMode"))
    seed = world.get("seed")
    if not _is_int(seed) or not 0 <= seed <= MAX_SEED:
        errors.append(err("schema", "Seed must be an integer from 0 to 2^53-1.", "world.seed"))
    sea = world.get("seaLevel")
    if not _is_int(sea) or not 32 <= sea <= 120:
        errors.append(err("schema", "seaLevel must be an integer from 32 to 120.", "world.seaLevel"))
    if world.get("minY") != MIN_Y or world.get("maxY") != MAX_Y:
        errors.append(err("schema", "Vertical bounds are fixed at -64 to 320.", "world.minY"))
    spawn = world.get("spawn")
    if not isinstance(spawn, dict) or not all(_is_int(spawn.get(key)) for key in ("x", "y", "z")):
        errors.append(err("schema", "Spawn must have integer x, y, and z.", "world.spawn"))
    border = world.get("border")
    if not isinstance(border, dict):
        errors.append(err("schema", "Missing border.", "world.border"))
    elif _is_int(width) and _is_int(depth):
        if border.get("size") != max(width, depth) or border.get("centerX") != 0 or border.get("centerZ") != 0:
            errors.append(err("border_locked", "Border center stays at 0 and its size matches the larger dimension.", "world.border"))
        for key, low, high in (
            ("warningBlocks", 0, 64),
            ("warningTime", 0, 120),
            ("safeZone", 0, 64),
        ):
            if not _is_int(border.get(key)) or not low <= border[key] <= high:
                errors.append(err("schema", f"border.{key} is out of range.", f"world.border.{key}"))
        damage = border.get("damagePerBlock")
        if isinstance(damage, bool) or not isinstance(damage, (int, float)) or not 0 <= float(damage) <= 5:
            errors.append(err("schema", "border.damagePerBlock must be from 0 to 5.", "world.border.damagePerBlock"))
    blend = project.get("blendRadius")
    if not _is_int(blend) or not 0 <= blend <= 32:
        errors.append(err("schema", "blendRadius must be an integer from 0 to 32.", "blendRadius"))
    errors.extend(_validate_profile(project.get("defaultTerrain"), registry, "defaultTerrain"))
    assets = project.get("assets")
    if not isinstance(assets, list):
        errors.append(err("schema", "assets must be a list.", "assets"))
        asset_ids: set[str] = set()
    else:
        asset_ids = set()
        for asset_index, asset in enumerate(assets):
            if not isinstance(asset, dict) or not is_uuid(str(asset.get("id", ""))):
                errors.append(err("schema", "Each asset needs a UUID id.", f"assets[{asset_index}]"))
                continue
            if asset["id"] in asset_ids:
                errors.append(err("schema", "Duplicate asset id.", f"assets[{asset_index}].id"))
            asset_ids.add(asset["id"])
    if _is_int(width) and _is_int(depth) and isinstance(spawn, dict) and all(_is_int(spawn.get(key)) for key in ("x", "z")):
        min_x, min_z, max_x, max_z = user_rectangle(project)
        if not (min_x <= spawn["x"] < max_x and min_z <= spawn["z"] < max_z):
            errors.append(err("out_of_bounds", "Spawn must lie inside the world rectangle.", "world.spawn"))
        if _is_int(spawn.get("y")) and not MIN_Y <= spawn["y"] <= MAX_Y:
            errors.append(err("out_of_bounds", "Spawn y is outside the world height.", "world.spawn.y"))
    regions = project.get("regions")
    if not isinstance(regions, list):
        errors.append(err("schema", "regions must be a list.", "regions"))
        return errors
    seen_ids = set()
    seen_names = set()
    for region_index, region in enumerate(regions):
        path = f"regions[{region_index}]"
        if not isinstance(region, dict):
            errors.append(err("schema", "Region must be an object.", path))
            continue
        if not is_uuid(str(region.get("id", ""))):
            errors.append(err("schema", "Region id must be a UUID.", f"{path}.id"))
        elif region["id"] in seen_ids:
            errors.append(err("schema", "Duplicate region id.", f"{path}.id"))
        else:
            seen_ids.add(region["id"])
        region_name = region.get("name")
        if not isinstance(region_name, str) or not 1 <= len(region_name.strip()) <= 48:
            errors.append(err("schema", "Region name must be 1 to 48 characters.", f"{path}.name"))
        elif region_name.strip().casefold() in seen_names:
            errors.append(err("duplicate_name", f"Region name {region_name} is already used.", f"{path}.name"))
        else:
            seen_names.add(region_name.strip().casefold())
        if not isinstance(region.get("color"), str) or not COLOR_RE.match(region["color"]):
            errors.append(err("schema", "Region color must be #RRGGBB.", f"{path}.color"))
        shape_errors = validate_shape(region.get("shape"), f"{path}.shape")
        errors.extend(shape_errors)
        if not shape_errors and _is_int(width) and _is_int(depth):
            if not _rect_inside(region["shape"], user_rectangle(project)):
                errors.append(err("out_of_bounds", "Region extends outside the world rectangle.", f"{path}.shape"))
        errors.extend(_validate_brief(region.get("brief"), asset_ids, f"{path}.brief"))
        if "mask" in region:
            errors.extend(_validate_mask(region.get("mask"), region.get("shape") if isinstance(region.get("shape"), dict) else None, f"{path}.mask"))
        errors.extend(_validate_profile(region, registry, path))
        mask = region.get("mask") if isinstance(region.get("mask"), dict) else None
        blend = project.get("blendRadius")
        if mask and "falloff" in mask and mask.get("falloff") is not None and _is_int(blend) and _is_int(mask.get("falloff")):
            if mask["falloff"] > blend:
                errors.append(err("schema", "mask.falloff cannot exceed the project blendRadius.", f"{path}.mask.falloff"))
    return errors
