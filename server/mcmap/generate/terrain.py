"""Column terrain, features, and spawn. Heights blend; materials and features use the hard owner."""

from __future__ import annotations

from collections import deque

import numpy as np

from mcmap.blocks import load_registry
from mcmap.generate.masks import contains_grid, mask_falloff, mask_kind, mask_signed_distance, organic_influence, plain_rect, signed_distance_grid
from mcmap.generate.noise import cave_density_volume, hash32, hash32_array, height_noise_grid
from mcmap.model import CRYSTAL_BLOCKS, TREE_BLOCKS, border_square

Y_MIN = -64
Y_MAX = 192
AIR = "minecraft:air"
CAVE_AIR = "minecraft:cave_air"
BEDROCK = "minecraft:bedrock"
STONE = "minecraft:stone"
DEEPSLATE = "minecraft:deepslate"
SAND = "minecraft:sand"
WATER = "minecraft:water"
LAVA = "minecraft:lava"
PLANT_SOIL = {
    "minecraft:grass_block",
    "minecraft:podzol",
    "minecraft:mycelium",
    "minecraft:moss_block",
}
LOGS = {
    "oak": "minecraft:oak_log",
    "birch": "minecraft:birch_log",
    "spruce": "minecraft:spruce_log",
    "acacia": "minecraft:acacia_log",
    "jungle": "minecraft:jungle_log",
}
LEAVES = {
    "oak": "minecraft:oak_leaves",
    "birch": "minecraft:birch_leaves",
    "spruce": "minecraft:spruce_leaves",
    "acacia": "minecraft:acacia_leaves",
    "jungle": "minecraft:jungle_leaves",
}
ORES = (
    ("minecraft:coal_ore", "minecraft:deepslate_coal_ore", 0, 96, 1, 7),
    ("minecraft:iron_ore", "minecraft:deepslate_iron_ore", -24, 64, 2, 8),
    ("minecraft:copper_ore", "minecraft:deepslate_copper_ore", -16, 48, 3, 9),
    ("minecraft:gold_ore", "minecraft:deepslate_gold_ore", -48, 0, 4, 11),
    ("minecraft:redstone_ore", "minecraft:deepslate_redstone_ore", -64, -8, 5, 11),
    ("minecraft:lapis_ore", "minecraft:deepslate_lapis_ore", -32, 16, 6, 13),
    ("minecraft:diamond_ore", "minecraft:deepslate_diamond_ore", -64, 12, 7, 13),
)
PLUS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
FEATURE_MARGIN = 12


def influence_grid(rect: dict, blend: int, x_coords: np.ndarray, z_coords: np.ndarray) -> np.ndarray:
    shape = (x_coords.size, z_coords.size)
    if blend <= 0:
        weights = np.zeros(shape, dtype=np.float64)
        x0 = int(rect["x"])
        z0 = int(rect["z"])
        x1 = x0 + int(rect["width"])
        z1 = z0 + int(rect["depth"])
        sel_x = np.nonzero((x_coords >= x0) & (x_coords < x1))[0]
        sel_z = np.nonzero((z_coords >= z0) & (z_coords < z1))[0]
        if sel_x.size and sel_z.size:
            weights[np.ix_(sel_x, sel_z)] = 1.0
        return weights
    px = x_coords.astype(np.float64)[:, None] + 0.5
    pz = z_coords.astype(np.float64)[None, :] + 0.5
    sd = signed_distance_grid(px, pz, rect)
    weights = np.empty(sd.shape, dtype=np.float64)
    full = sd >= float(blend)
    outside = sd <= -float(blend)
    mid = ~full & ~outside
    weights[full] = 1.0
    weights[outside] = 0.0
    if np.any(mid):
        t = (sd[mid] + float(blend)) / (2.0 * float(blend))
        weights[mid] = t * t * (3.0 - 2.0 * t)
    return weights


def columns_near_rect(rect: dict, blend: int, x_coords: np.ndarray, z_coords: np.ndarray) -> np.ndarray:
    if blend <= 0:
        return influence_grid(rect, blend, x_coords, z_coords) >= 1.0
    px = x_coords.astype(np.float64)[:, None] + 0.5
    pz = z_coords.astype(np.float64)[None, :] + 0.5
    return signed_distance_grid(px, pz, rect) >= -float(blend)


def _style_name(profile: dict) -> str:
    return str(profile.get("terrain", {}).get("style") or "classic")


def _height_ceiling(terrain: dict, style: str) -> int:
    if "ceiling" in terrain and terrain.get("ceiling") is not None:
        return int(terrain["ceiling"])
    if style == "alpine":
        return 248
    if style in {"mesa", "plateau", "cliff"}:
        return 220
    return 180


def _shaped_noise(style: str, seed: int, x_coords: np.ndarray, z_coords: np.ndarray, roughness: float) -> np.ndarray:
    if style == "dunes":
        roughness = max(0.0, min(1.0, roughness * 0.45))
    noise = height_noise_grid(seed, x_coords, z_coords, roughness)
    if style != "alpine":
        return noise
    second = height_noise_grid(seed ^ 0x21, x_coords, z_coords, min(1.0, roughness + 0.25))
    ridge = 1.0 - np.abs(noise)
    ridge2 = 1.0 - np.abs(second)
    return (ridge * 0.72 + ridge2 * 0.28) * 2.0 - 1.0


def _round_grid(raw: np.ndarray) -> np.ndarray:
    return np.asarray([round(float(value)) for value in raw.reshape(-1)], dtype=np.int32).reshape(raw.shape)


def _profile_heights(profile: dict, x_coords: np.ndarray, z_coords: np.ndarray, seed: int, sea: int) -> np.ndarray:
    terrain = profile["terrain"]
    base = int(terrain["baseHeight"])
    amplitude = int(terrain["amplitude"])
    style = _style_name(profile)
    ceiling = _height_ceiling(terrain, style)
    if style == "classic" and ceiling == 180:
        if amplitude == 0:
            heights = np.full((x_coords.size, z_coords.size), base, dtype=np.int32)
        else:
            noise = height_noise_grid(seed, x_coords, z_coords, float(terrain["roughness"]))
            raw = base + amplitude * noise
            heights = _round_grid(raw)
        np.clip(heights, 8, 180, out=heights)
        if terrain.get("water"):
            np.minimum(heights, int(sea) - 4, out=heights)
        return heights
    if amplitude == 0:
        heights = np.full((x_coords.size, z_coords.size), base, dtype=np.int32)
    else:
        noise = _shaped_noise(style, seed, x_coords, z_coords, float(terrain["roughness"]))
        if style == "plateau":
            noise = noise * 0.35
        elif style == "cliff":
            noise = noise * 0.45
        heights = _round_grid(base + amplitude * noise)
    np.clip(heights, 8, ceiling, out=heights)
    if style == "mesa":
        step = max(1, int(terrain.get("terrace") or 4))
        heights = _round_grid(heights / float(step)) * step
        np.clip(heights, 8, ceiling, out=heights)
    if terrain.get("water"):
        np.minimum(heights, int(sea) - 4, out=heights)
    return heights


def _region_weights(region: dict, blend: int, x_coords: np.ndarray, z_coords: np.ndarray, seed: int) -> np.ndarray:
    falloff = mask_falloff(region, blend)
    if mask_kind(region) == "rect":
        return influence_grid(region["shape"], falloff, x_coords, z_coords)
    return organic_influence(region, falloff, x_coords, z_coords, seed)


def _apply_coast(region: dict, heights: np.ndarray, x_coords: np.ndarray, z_coords: np.ndarray, seed: int, sea: int) -> np.ndarray:
    terrain = region.get("terrain") or {}
    style = _style_name(region)
    shore = int(terrain.get("shore") or (6 if style == "cliff" else 0))
    cliff = int(terrain.get("cliff") or (8 if style == "cliff" else 0))
    if shore <= 0 and cliff <= 0:
        return heights
    px = x_coords.astype(np.float64)[:, None] + 0.5
    pz = z_coords.astype(np.float64)[None, :] + 0.5
    if mask_kind(region) == "rect":
        sd = signed_distance_grid(px, pz, region["shape"])
    else:
        sd = mask_signed_distance(region, px, pz, seed)
    adjusted = heights
    if shore > 0:
        beach = (sd >= 0.0) & (sd < float(shore))
        if np.any(beach):
            adjusted = np.array(heights, copy=True)
            adjusted[beach] = int(sea) + 2
    if cliff > 0:
        ramp = (sd >= float(shore)) & (sd < float(shore + cliff))
        if np.any(ramp):
            if adjusted is heights:
                adjusted = np.array(heights, copy=True)
            t = (sd[ramp] - float(shore)) / float(max(cliff, 1))
            low = float(int(sea) + 2)
            high = heights[ramp].astype(np.float64)
            adjusted[ramp] = _round_grid(low + t * (high - low)).reshape(-1)
    return adjusted


def _blend_heights(project: dict, x_coords: np.ndarray, z_coords: np.ndarray, seed: int, sea: int) -> np.ndarray:
    blend = int(project["blendRadius"])
    heights = _profile_heights(project["defaultTerrain"], x_coords, z_coords, seed, sea)
    for region in project.get("regions", []):
        weights = _region_weights(region, blend, x_coords, z_coords, seed)
        if not np.any(weights > 0.0):
            continue
        region_heights = _apply_coast(
            region,
            _profile_heights(region, x_coords, z_coords, seed, sea),
            x_coords,
            z_coords,
            seed,
            sea,
        )
        full = weights >= 1.0
        mid = (weights > 0.0) & ~full
        if np.any(full):
            heights[full] = region_heights[full]
        if np.any(mid):
            mixed = (1.0 - weights[mid]) * heights[mid].astype(np.float64) + weights[mid] * region_heights[mid].astype(
                np.float64
            )
            heights[mid] = [round(float(value)) for value in mixed]
    return heights


def _paint_owners(project: dict, x_coords: np.ndarray, z_coords: np.ndarray, idx: dict[str, int], biome_index: dict[str, int]):
    nx = x_coords.size
    nz = z_coords.size
    min_x = int(x_coords[0])
    min_z = int(z_coords[0])
    owner = np.full((nx, nz), -1, dtype=np.int16)
    seed = int(project["world"]["seed"])
    blend = int(project["blendRadius"])
    for region_index, region in enumerate(project.get("regions", [])):
        if plain_rect(region, blend):
            shape = region["shape"]
            x0 = int(shape["x"])
            z0 = int(shape["z"])
            x1 = x0 + int(shape["width"])
            z1 = z0 + int(shape["depth"])
            ix0 = max(0, x0 - min_x)
            ix1 = min(nx, x1 - min_x)
            iz0 = max(0, z0 - min_z)
            iz1 = min(nz, z1 - min_z)
            if ix0 < ix1 and iz0 < iz1:
                owner[ix0:ix1, iz0:iz1] = region_index
        else:
            inside = contains_grid(region, x_coords, z_coords, seed)
            if np.any(inside):
                owner[inside] = region_index
    stone_i = np.empty((nx, nz), dtype=np.uint16)
    sub_i = np.empty((nx, nz), dtype=np.uint16)
    surf_i = np.empty((nx, nz), dtype=np.uint16)
    water_i = np.empty((nx, nz), dtype=np.uint16)
    sand_ok = np.empty((nx, nz), dtype=np.bool_)
    vanilla = np.empty((nx, nz), dtype=np.bool_)
    caves_on = np.empty((nx, nz), dtype=np.bool_)
    ores_on = np.empty((nx, nz), dtype=np.bool_)
    biomes = np.empty((nx, nz), dtype=np.uint8)

    def paint(selection, profile: dict) -> None:
        palette = profile["palette"]
        features = profile["features"]
        stone_i[selection] = idx[palette["stone"]]
        sub_i[selection] = idx[palette["subsurface"]]
        surf_i[selection] = idx[palette["surface"]]
        water_i[selection] = idx[palette["water"]]
        sand_ok[selection] = SAND in palette["allowed"]
        vanilla[selection] = palette["stone"] == STONE
        caves_on[selection] = bool(features["caves"])
        ores_on[selection] = bool(features["ores"])
        biomes[selection] = biome_index[profile["vanillaBiome"]]

    paint(np.ones((nx, nz), dtype=bool), project["defaultTerrain"])
    for region_index, region in enumerate(project.get("regions", [])):
        selection = owner == region_index
        if np.any(selection):
            paint(selection, region)
    return owner, stone_i, sub_i, surf_i, water_i, sand_ok, vanilla, caves_on, ores_on, biomes


def _fill_materials(
    heights: np.ndarray,
    stone_i: np.ndarray,
    sub_i: np.ndarray,
    surf_i: np.ndarray,
    water_i: np.ndarray,
    sand_ok: np.ndarray,
    vanilla: np.ndarray,
    idx: dict[str, int],
    sea: int,
) -> np.ndarray:
    nx, nz = heights.shape
    ny = Y_MAX - Y_MIN + 1
    y = np.arange(Y_MIN, Y_MAX + 1, dtype=np.int32)[None, None, :]
    column_height = heights.astype(np.int32)[:, :, None]
    blocks = np.full((nx, nz, ny), idx[AIR], dtype=np.uint16)
    blocks[:, :, 0] = idx[BEDROCK]
    stone_layer = (y >= -63) & (y <= (column_height - 4))
    blocks[stone_layer] = np.broadcast_to(stone_i[:, :, None], blocks.shape)[stone_layer]
    deep_layer = vanilla[:, :, None] & (y >= -63) & (y <= -1)
    blocks[deep_layer] = idx[DEEPSLATE]
    sub_layer = (y >= (column_height - 3)) & (y <= (column_height - 1))
    blocks[sub_layer] = np.broadcast_to(sub_i[:, :, None], blocks.shape)[sub_layer]
    surf_layer = y == column_height
    blocks[surf_layer] = np.broadcast_to(surf_i[:, :, None], blocks.shape)[surf_layer]
    under = heights < int(sea)
    under3 = under[:, :, None]
    sand_layer = under3 & surf_layer & sand_ok[:, :, None]
    replace_sub = under3 & surf_layer & ~sand_ok[:, :, None]
    if np.any(sand_layer):
        blocks[sand_layer] = idx[SAND]
    if np.any(replace_sub):
        blocks[replace_sub] = np.broadcast_to(sub_i[:, :, None], blocks.shape)[replace_sub]
    water_layer = under3 & (y >= (column_height + 1)) & (y <= (int(sea) - 1))
    if np.any(water_layer):
        blocks[water_layer] = np.broadcast_to(water_i[:, :, None], blocks.shape)[water_layer]
    return blocks


def _can_write(
    x: int,
    z: int,
    owner_rect,
    owner: np.ndarray,
    mask: np.ndarray,
    min_x: int,
    min_z: int,
    clip_owner: bool = False,
    owner_id: int = -1,
) -> bool:
    nx, nz = mask.shape
    if not (min_x <= x < min_x + nx and min_z <= z < min_z + nz):
        return False
    ix = x - min_x
    iz = z - min_z
    if not mask[ix, iz]:
        return False
    if owner_rect is None:
        return int(owner[ix, iz]) < 0
    shape = owner_rect
    inside = int(shape["x"]) <= x < int(shape["x"]) + int(shape["width"]) and int(shape["z"]) <= z < int(shape["z"]) + int(
        shape["depth"]
    )
    if not inside:
        return False
    if clip_owner and int(owner[ix, iz]) != int(owner_id):
        return False
    return True


def _tree_form(trees: dict) -> str:
    form = trees.get("form") or "classic"
    return form if form in {"classic", "varied", "clustered", "emergent"} else "classic"


def _tree_site(form: str, seed: int, x: int, z: int) -> bool:
    classic = x % 5 == 2 and z % 5 == 2
    if form == "classic":
        return classic
    period = {"varied": 17, "clustered": 9, "emergent": 7}[form]
    salt = {"varied": 73, "clustered": 74, "emergent": 75}[form]
    return classic or hash32(seed, x, 0, z, salt) % period == 0


def _set_block(blocks, x, z, y, block_index, min_x, min_z) -> None:
    if y < Y_MIN or y > Y_MAX:
        return
    blocks[x - min_x, z - min_z, y - Y_MIN] = block_index


def _warn_trees(profile: dict, warnings: list[str], warned: set[str]) -> bool:
    kind = profile["features"]["trees"]["kind"]
    if kind == "none":
        return True
    allowed = set(profile["palette"]["allowed"])
    if any(block_id not in allowed for block_id in TREE_BLOCKS.get(kind, ())):
        message = f"skipped {kind} trees because required blocks are not allowed"
        if message not in warned:
            warned.add(message)
            warnings.append(message)
        return False
    return True


def _apply_trees(
    project,
    blocks,
    heights,
    owner,
    mask,
    x_coords,
    z_coords,
    block_ids,
    idx,
    seed,
    warnings,
) -> None:
    warned: set[str] = set()
    regions = project.get("regions", [])
    min_x = int(x_coords[0])
    min_z = int(z_coords[0])
    log_ids = {idx[name] for name in LOGS.values()}
    blend = int(project["blendRadius"])
    for iz, z in enumerate(z_coords.tolist()):
        for ix, x in enumerate(x_coords.tolist()):
            if not mask[ix, iz]:
                continue
            owner_id = int(owner[ix, iz])
            profile = project["defaultTerrain"] if owner_id < 0 else regions[owner_id]
            trees = profile["features"]["trees"]
            kind = trees["kind"]
            form = _tree_form(trees)
            if kind == "none" or not _tree_site(form, seed, x, z):
                continue
            threshold = max(1, int(float(trees["density"]) * 8000))
            if hash32(seed, x, 0, z, 70) % 1000 >= threshold:
                continue
            if not _warn_trees(profile, warnings, warned):
                continue
            column_height = int(heights[ix, iz])
            surface = block_ids[int(blocks[ix, iz, column_height - Y_MIN])]
            roll = hash32(seed, x, 0, z, 71)
            roll2 = hash32(seed, x, 0, z, 76)
            owner_rect = None if owner_id < 0 else regions[owner_id]["shape"]
            clip = owner_id >= 0 and not plain_rect(regions[owner_id], blend)

            def can(tx: int, tz: int, _rect=owner_rect, _clip=clip, _owner_id=owner_id) -> bool:
                return _can_write(tx, tz, _rect, owner, mask, min_x, min_z, _clip, _owner_id)

            if kind == "cactus":
                if surface != SAND:
                    continue
                cactus_i = idx["minecraft:cactus"]
                for step in range(1, 2 + (roll % 2) + 1):
                    if can(x, z):
                        _set_block(blocks, x, z, column_height + step, cactus_i, min_x, min_z)
                continue
            emergent = False
            conical = False
            trunks = [(0, 0)]
            if form == "classic":
                if kind in ("oak", "birch", "acacia"):
                    trunk_h = 4 + (roll % 3)
                    radius = 2
                    manhattan = 3
                elif kind == "spruce":
                    trunk_h = 5 + (roll % 3)
                    radius = 1
                    manhattan = None
                elif kind == "jungle":
                    trunk_h = 6 + (roll % 3)
                    radius = 2
                    manhattan = 3
                else:
                    continue
            elif kind in ("oak", "birch", "acacia"):
                trunk_h = 4 + (roll % 5)
                radius = 2 + (roll2 % 2)
                manhattan = 3 + (roll2 % 2)
            elif kind == "spruce":
                trunk_h = 7 + (roll % 8)
                radius = 2 + (roll2 % 2)
                manhattan = None
                conical = True
                if form == "clustered" and roll2 % 4 == 0:
                    trunks.append((2 if roll % 2 == 0 else -2, 1 if roll2 % 2 == 0 else -1))
            elif kind == "jungle":
                emergent = form == "emergent" and roll2 % 5 == 0
                trunk_h = (14 + (roll % 8)) if emergent else (7 + (roll % 5))
                radius = 3 if emergent else 2
                manhattan = 4 if emergent else 3
                if emergent:
                    trunks = [(0, 0), (1, 0), (0, 1), (1, 1)]
            else:
                continue
            log_i = idx[LOGS[kind]]
            leaf_i = idx[LEAVES[kind]]
            for dx, dz in trunks:
                tx = x + dx
                tz = z + dz
                if not can(tx, tz):
                    continue
                for step in range(1, trunk_h + 1):
                    _set_block(blocks, tx, tz, column_height + step, log_i, min_x, min_z)
            top = column_height + trunk_h
            if conical:
                leaf_rows = [(y, 1 if top - y <= 1 else min(radius, max(1, (top - y) // 2))) for y in range(top - trunk_h + 3, top + 2)]
            else:
                leaf_rows = [(y, radius) for y in range(top - 2, top + 2)]
            for y, layer_radius in leaf_rows:
                for dx in range(-layer_radius, layer_radius + 1):
                    for dz in range(-layer_radius, layer_radius + 1):
                        if not conical and manhattan is not None and abs(dx) + abs(dz) > manhattan:
                            continue
                        if dx == 0 and dz == 0 and y <= top:
                            continue
                        tx = x + dx
                        tz = z + dz
                        if not can(tx, tz):
                            continue
                        if y < Y_MIN or y > Y_MAX:
                            continue
                        current = int(blocks[tx - min_x, tz - min_z, y - Y_MIN])
                        if current in log_ids:
                            continue
                        name = block_ids[current]
                        if name != AIR and not name.endswith("_leaves"):
                            continue
                        blocks[tx - min_x, tz - min_z, y - Y_MIN] = leaf_i


def _plant_id(profile: dict, surface: str, roll: int) -> str | None:
    vegetation = profile["features"]["vegetation"]
    if vegetation == "none" or roll % 100 >= 35:
        return None
    allowed = set(profile["palette"]["allowed"])
    if vegetation == "dry":
        if surface != SAND or "minecraft:dead_bush" not in allowed:
            return None
        return "minecraft:dead_bush"
    if surface not in PLANT_SOIL:
        return None
    if vegetation == "temperate":
        if roll % 11 == 0:
            poppy = "minecraft:poppy" in allowed
            dandelion = "minecraft:dandelion" in allowed
            if poppy and (roll % 22 == 0 or not dandelion):
                return "minecraft:poppy"
            if dandelion:
                return "minecraft:dandelion"
        if "minecraft:short_grass" in allowed:
            return "minecraft:short_grass"
        return None
    if vegetation == "lush":
        if "minecraft:fern" in allowed and roll % 2 == 0:
            return "minecraft:fern"
        if "minecraft:short_grass" in allowed:
            return "minecraft:short_grass"
        return None
    if vegetation == "cold" and "minecraft:short_grass" in allowed:
        return "minecraft:short_grass"
    return None


def _apply_vegetation(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed) -> None:
    regions = project.get("regions", [])
    ixs, izs = np.nonzero(mask)
    if len(ixs) == 0:
        return
    xs = x_coords[ixs]
    zs = z_coords[izs]
    rolls = hash32_array(seed, xs, np.int64(0), zs, 50)
    chosen = np.nonzero((rolls % 100) < 35)[0]
    air_i = idx[AIR]
    for cursor in chosen.tolist():
        ix = int(ixs[cursor])
        iz = int(izs[cursor])
        column_height = int(heights[ix, iz])
        above = column_height + 1
        if above > Y_MAX:
            continue
        if int(blocks[ix, iz, above - Y_MIN]) != air_i:
            continue
        surface = block_ids[int(blocks[ix, iz, column_height - Y_MIN])]
        owner_id = int(owner[ix, iz])
        profile = project["defaultTerrain"] if owner_id < 0 else regions[owner_id]
        plant = _plant_id(profile, surface, int(rolls[cursor]))
        if plant is None:
            continue
        blocks[ix, iz, above - Y_MIN] = idx[plant]


def _apply_caves(blocks, heights, mask, caves_on, x_coords, z_coords, idx, seed, spawn_x, spawn_z) -> None:
    chebyshev = np.maximum(
        np.abs(x_coords.astype(np.int32)[:, None] - int(spawn_x)),
        np.abs(z_coords.astype(np.int32)[None, :] - int(spawn_z)),
    )
    eligible = mask & caves_on & (chebyshev > 12)
    if not np.any(eligible):
        return
    stone_i = idx[STONE]
    deep_i = idx[DEEPSLATE]
    cave_i = idx[CAVE_AIR]
    nx, nz = heights.shape
    tile = 64
    for x_start in range(0, nx, tile):
        x_end = min(nx, x_start + tile)
        for z_start in range(0, nz, tile):
            z_end = min(nz, z_start + tile)
            sub_eligible = eligible[x_start:x_end, z_start:z_end]
            if not np.any(sub_eligible):
                continue
            sub_heights = heights[x_start:x_end, z_start:z_end].astype(np.int32)
            y_hi = int(sub_heights.max()) - 5
            if y_hi < -59:
                continue
            y_vals = np.arange(-59, y_hi + 1, dtype=np.int32)
            density = cave_density_volume(seed, x_coords[x_start:x_end], y_vals, z_coords[z_start:z_end])
            limit = sub_heights[:, :, None] - 5
            hot = (density > 0.58) & (y_vals[None, None, :] <= limit) & sub_eligible[:, :, None]
            block_slice = blocks[x_start:x_end, z_start:z_end]
            for y_index, y in enumerate(y_vals.tolist()):
                selected = hot[:, :, y_index]
                if not np.any(selected):
                    continue
                column = block_slice[:, :, int(y) - Y_MIN]
                carve = selected & ((column == stone_i) | (column == deep_i))
                column[carve] = cave_i


def _aligned(lo: int, hi: int, stride: int):
    if lo > hi:
        return range(0)
    rem = lo % stride
    start = lo if rem == 0 else lo + (stride - rem)
    if start > hi:
        return range(0)
    return range(start, hi + 1, stride)


def _apply_ores(blocks, mask, ores_on, x_coords, z_coords, idx, seed) -> None:
    if not np.any(mask & ores_on):
        return
    min_x = int(x_coords[0])
    max_x = int(x_coords[-1])
    min_z = int(z_coords[0])
    max_z = int(z_coords[-1])
    stone_i = idx[STONE]
    deep_i = idx[DEEPSLATE]
    hosts = (stone_i, deep_i)
    nx, nz = mask.shape
    for regular, deep, y0, y1, salt, stride in ORES:
        regular_i = idx[regular]
        deep_ore_i = idx[deep]
        for x in _aligned(min_x, max_x, stride):
            ix = x - min_x
            if ix < 0 or ix >= nx:
                continue
            for z in _aligned(min_z, max_z, stride):
                iz = z - min_z
                if iz < 0 or iz >= nz or not mask[ix, iz] or not ores_on[ix, iz]:
                    continue
                for y in _aligned(y0, y1, stride):
                    if y < Y_MIN or y > Y_MAX:
                        continue
                    center = int(blocks[ix, iz, y - Y_MIN])
                    if center != stone_i and center != deep_i:
                        continue
                    if hash32(seed, x, y, z, salt) % 17 != 0:
                        continue
                    for dx, dz in PLUS:
                        tx = x + dx
                        tz = z + dz
                        tix = tx - min_x
                        tiz = tz - min_z
                        if not (0 <= tix < nx and 0 <= tiz < nz):
                            continue
                        if not mask[tix, tiz] or not ores_on[tix, tiz]:
                            continue
                        current = int(blocks[tix, tiz, y - Y_MIN])
                        if current not in hosts:
                            continue
                        blocks[tix, tiz, y - Y_MIN] = deep_ore_i if y < 0 else regular_i


def _spiral(cx: int, cz: int, radius: int):
    yield cx, cz
    for ring in range(1, radius + 1):
        for dx in range(2 * ring):
            yield cx - ring + dx, cz - ring
        for dz in range(2 * ring):
            yield cx + ring, cz - ring + dz
        for dx in range(2 * ring):
            yield cx + ring - dx, cz + ring
        for dz in range(2 * ring):
            yield cx - ring, cz + ring - dz


def _block_name(blocks, block_ids, ix: int, iz: int, y: int) -> str:
    if y < Y_MIN or y > Y_MAX:
        return AIR
    return block_ids[int(blocks[ix, iz, y - Y_MIN])]


def _standable(name: str) -> bool:
    if name in {WATER, LAVA, AIR, CAVE_AIR}:
        return False
    if name.endswith("_leaves") or name.endswith("_log"):
        return False
    return load_registry().is_solid(name)


def _headroom(blocks, block_ids, ix: int, iz: int, column_height: int) -> bool:
    for dy in (1, 2):
        if _block_name(blocks, block_ids, ix, iz, column_height + dy) != AIR:
            return False
    return True


def _column_safe(blocks, heights, block_ids, ix: int, iz: int) -> bool:
    column_height = int(heights[ix, iz])
    surface = _block_name(blocks, block_ids, ix, iz, column_height)
    if surface in (WATER, LAVA):
        return False
    return _headroom(blocks, block_ids, ix, iz, column_height)


def _walkable(blocks, heights, block_ids, ix: int, iz: int) -> bool:
    column_height = int(heights[ix, iz])
    surface = _block_name(blocks, block_ids, ix, iz, column_height)
    if not _standable(surface):
        return False
    if _block_name(blocks, block_ids, ix, iz, column_height + 1) in {WATER, LAVA}:
        return False
    return _headroom(blocks, block_ids, ix, iz, column_height)


def _spawn_checks(blocks, heights, block_ids, ix: int, iz: int) -> dict:
    nx, nz = heights.shape
    column_height = int(heights[ix, iz])
    surface = _block_name(blocks, block_ids, ix, iz, column_height)
    solid = _standable(surface)
    headroom = _headroom(blocks, block_ids, ix, iz, column_height)
    dry = surface not in {WATER, LAVA} and _block_name(blocks, block_ids, ix, iz, column_height + 1) not in {WATER, LAVA}
    no_fall = True
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx_i = ix + dx
        nz_i = iz + dz
        if not (0 <= nx_i < nx and 0 <= nz_i < nz):
            continue
        neighbor = int(heights[nx_i, nz_i])
        neighbor_surface = _block_name(blocks, block_ids, nx_i, nz_i, neighbor)
        if neighbor < column_height - 3 or neighbor_surface in {WATER, LAVA}:
            no_fall = False
            break
    inside = 0
    clear = 0
    for dx in range(-2, 3):
        for dz in range(-2, 3):
            nx_i = ix + dx
            nz_i = iz + dz
            if not (0 <= nx_i < nx and 0 <= nz_i < nz):
                continue
            inside += 1
            if _walkable(blocks, heights, block_ids, nx_i, nz_i) and abs(int(heights[nx_i, nz_i]) - column_height) <= 1:
                clear += 1
    nearby = inside > 0 and clear >= max(9, int(0.6 * inside))
    route = _route_away(blocks, heights, block_ids, ix, iz)
    return {
        "solid": bool(solid),
        "headroom": bool(headroom),
        "dry": bool(dry),
        "noImmediateFall": bool(no_fall),
        "nearbyClear": bool(nearby),
        "route": bool(route),
        "pad": False,
    }


def _checks_pass(checks: dict) -> bool:
    return all(checks[key] for key in ("solid", "headroom", "dry", "noImmediateFall", "nearbyClear", "route"))


def _route_away(blocks, heights, block_ids, ix: int, iz: int) -> bool:
    nx, nz = heights.shape
    if not _walkable(blocks, heights, block_ids, ix, iz):
        return False
    seen = {(ix, iz)}
    queue = deque([(ix, iz)])
    popped = 0
    while queue and popped < 900:
        x, z = queue.popleft()
        popped += 1
        if max(abs(x - ix), abs(z - iz)) >= 10:
            return True
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx_i = x + dx
            nz_i = z + dz
            if not (0 <= nx_i < nx and 0 <= nz_i < nz) or (nx_i, nz_i) in seen:
                continue
            if abs(int(heights[nx_i, nz_i]) - int(heights[x, z])) > 1:
                continue
            if not _walkable(blocks, heights, block_ids, nx_i, nz_i):
                continue
            seen.add((nx_i, nz_i))
            queue.append((nx_i, nz_i))
    return False


def _place_pad(blocks, heights, rx: int, rz: int, sea: int, min_x: int, max_x: int, min_z: int, max_z: int, surface_i: int, air_i: int) -> None:
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            x = rx + dx
            z = rz + dz
            if not (min_x <= x <= max_x and min_z <= z <= max_z):
                continue
            ix = x - min_x
            iz = z - min_z
            blocks[ix, iz, sea - Y_MIN] = surface_i
            for dy in (1, 2):
                y = sea + dy
                if Y_MIN <= y <= Y_MAX:
                    blocks[ix, iz, y - Y_MIN] = air_i


def _apply_spawn(project, blocks, heights, x_coords, z_coords, block_ids, idx, warnings: list[str]):
    min_x = int(x_coords[0])
    max_x = int(x_coords[-1])
    min_z = int(z_coords[0])
    max_z = int(z_coords[-1])
    nx = x_coords.size
    nz = z_coords.size
    requested = project["world"]["spawn"]
    rx = int(requested["x"])
    ry = int(requested["y"])
    rz = int(requested["z"])
    sea = int(project["world"]["seaLevel"])
    found = None
    for x, z in _spiral(rx, rz, 48):
        if not (min_x <= x <= max_x and min_z <= z <= max_z):
            continue
        ix = x - min_x
        iz = z - min_z
        if not (0 <= ix < nx and 0 <= iz < nz):
            continue
        if not _column_safe(blocks, heights, block_ids, ix, iz):
            continue
        checks = _spawn_checks(blocks, heights, block_ids, ix, iz)
        if _checks_pass(checks):
            found = (x, z, checks)
            break
    pad = False
    if found is None:
        warnings.append("spawn pad built")
        pad = True
        _place_pad(
            blocks,
            heights,
            rx,
            rz,
            sea,
            min_x,
            max_x,
            min_z,
            max_z,
            idx[project["defaultTerrain"]["palette"]["surface"]],
            idx[AIR],
        )
        sx, sy, sz = rx, sea + 1, rz
        ix = sx - min_x
        iz = sz - min_z
        checks = _spawn_checks(blocks, heights, block_ids, ix, iz)
        checks["pad"] = True
        if not _checks_pass(checks):
            warnings.append("spawn checks incomplete")
    else:
        sx, sz, checks = found
        sy = int(heights[sx - min_x, sz - min_z]) + 1
    _place_camp(blocks, heights, sx, sz, min_x, max_x, min_z, max_z, idx)
    adjusted = sx != rx or sy != ry or sz != rz
    return {"x": int(sx), "y": int(sy), "z": int(sz)}, adjusted, checks, pad


def _place_camp(blocks, heights, sx, sz, min_x, max_x, min_z, max_z, idx) -> None:
    crafting = idx["minecraft:crafting_table"]
    cobble = idx["minecraft:cobblestone"]

    def inside(x: int, z: int) -> bool:
        return min_x <= x <= max_x and min_z <= z <= max_z

    table_x = sx + 2
    if inside(table_x, sz):
        column_height = int(heights[table_x - min_x, sz - min_z])
        y = column_height + 1
        if Y_MIN <= y <= Y_MAX:
            blocks[table_x - min_x, sz - min_z, y - Y_MIN] = crafting
    pillar_x = sx + 3
    if inside(pillar_x, sz):
        column_height = int(heights[pillar_x - min_x, sz - min_z])
        for y in range(column_height + 1, column_height + 6):
            if Y_MIN <= y <= Y_MAX:
                blocks[pillar_x - min_x, sz - min_z, y - Y_MIN] = cobble


def _count_chunks(mask: np.ndarray, x_coords: np.ndarray, z_coords: np.ndarray) -> int:
    ixs, izs = np.nonzero(mask)
    if len(ixs) == 0:
        return 0
    cx = np.right_shift(x_coords[ixs].astype(np.int64), 4)
    cz = np.right_shift(z_coords[izs].astype(np.int64), 4)
    return len(set(zip(cx.tolist(), cz.tolist())))


def build_scope_mask(project: dict, scope: dict | None) -> tuple[np.ndarray, bool]:
    min_x, min_z, max_x, max_z = border_square(project)
    x_coords = np.arange(min_x, max_x, dtype=np.int32)
    z_coords = np.arange(min_z, max_z, dtype=np.int32)
    full = np.ones((x_coords.size, z_coords.size), dtype=bool)
    kind = (scope or {}).get("kind", "all")
    if kind == "all":
        return full, True
    if kind == "region":
        region_id = scope.get("regionId")
        region = next((item for item in project.get("regions", []) if item.get("id") == region_id), None)
        if region is None:
            return full, True
        rect = region["shape"]
    elif kind == "rect":
        rect = {
            "x": int(scope["x"]),
            "z": int(scope["z"]),
            "width": int(scope["width"]),
            "depth": int(scope["depth"]),
        }
    else:
        return full, True
    return columns_near_rect(rect, int(project["blendRadius"]), x_coords, z_coords), False


def generate_arrays(project: dict, mask: np.ndarray, previous: dict | None, block_ids: list[str], biome_ids: list[str]) -> dict:
    min_x, min_z, max_x, max_z = border_square(project)
    x_coords = np.arange(min_x, max_x, dtype=np.int32)
    z_coords = np.arange(min_z, max_z, dtype=np.int32)
    if mask.shape != (x_coords.size, z_coords.size):
        raise RuntimeError("generation mask does not match the border")
    idx = {block_id: index for index, block_id in enumerate(block_ids)}
    biome_index = {biome: index for index, biome in enumerate(biome_ids)}
    seed = int(project["world"]["seed"])
    sea = int(project["world"]["seaLevel"])
    heights = _blend_heights(project, x_coords, z_coords, seed, sea)
    owner, stone_i, sub_i, surf_i, water_i, sand_ok, vanilla, caves_on, ores_on, biomes = _paint_owners(
        project, x_coords, z_coords, idx, biome_index
    )
    blocks = _fill_materials(heights, stone_i, sub_i, surf_i, water_i, sand_ok, vanilla, idx, sea)
    if previous is not None:
        keep = ~mask
        blocks[keep] = previous["blocks"][keep]
        heights[keep] = previous["heights"][keep]
        biomes[keep] = previous["biomes"][keep]
    warnings: list[str] = []
    spawn_x = int(project["world"]["spawn"]["x"])
    spawn_z = int(project["world"]["spawn"]["z"])
    _apply_surface_details(project, blocks, heights, owner, mask, x_coords, z_coords, idx, seed, sea)
    _apply_caves(blocks, heights, mask, caves_on, x_coords, z_coords, idx, seed, spawn_x, spawn_z)
    _apply_ores(blocks, mask, ores_on, x_coords, z_coords, idx, seed)
    _apply_trees(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed, warnings)
    _apply_vegetation(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed)
    _apply_food(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed)
    _apply_crystals(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed, sea, warnings)
    spawn, adjusted, spawn_checks, spawn_pad = _apply_spawn(
        project, blocks, heights, x_coords, z_coords, block_ids, idx, warnings
    )
    return {
        "blocks": blocks,
        "heights": heights.astype(np.int16),
        "biomes": biomes.astype(np.uint8),
        "owners": owner.astype(np.int16),
        "spawn": spawn,
        "spawnChecks": spawn_checks,
        "spawnPad": bool(spawn_pad),
        "spawnAdjusted": bool(adjusted),
        "warnings": warnings,
        "columnsWritten": int(mask.sum()),
        "chunksWritten": _count_chunks(mask, x_coords, z_coords),
        "min_x": min_x,
        "min_z": min_z,
        "y_min": Y_MIN,
        "y_max": Y_MAX,
    }


def _profiles(project: dict):
    yield -1, project["defaultTerrain"]
    for index, region in enumerate(project.get("regions", [])):
        yield index, region


def _selection(owner: np.ndarray, owner_id: int, mask: np.ndarray) -> np.ndarray:
    if owner_id < 0:
        return (owner < 0) & mask
    return (owner == owner_id) & mask


def _apply_surface_details(project, blocks, heights, owner, mask, x_coords, z_coords, idx, seed, sea) -> None:
    for owner_id, profile in _profiles(project):
        selection = _selection(owner, owner_id, mask)
        if not np.any(selection):
            continue
        terrain = profile["terrain"]
        palette = profile["palette"]
        allowed = set(palette.get("allowed") or [])
        snow_line = terrain.get("snowLine")
        if snow_line is not None and "minecraft:snow_block" in allowed and "minecraft:snow_block" in idx:
            snowy = selection & (heights >= int(snow_line)) & (heights >= int(sea))
            xs, zs = np.nonzero(snowy)
            snow_i = idx["minecraft:snow_block"]
            for ix, iz in zip(xs.tolist(), zs.tolist()):
                blocks[ix, iz, int(heights[ix, iz]) - Y_MIN] = snow_i
        strata = [block_id for block_id in (palette.get("strata") or []) if block_id in idx and block_id in allowed]
        if strata:
            thickness = max(1, int(terrain.get("terrace") or 4))
            band_ids = [idx[block_id] for block_id in strata]
            xs, zs = np.nonzero(selection)
            for ix, iz in zip(xs.tolist(), zs.tolist()):
                top = int(heights[ix, iz]) - 4
                bottom = top - len(band_ids) * thickness
                for y in range(max(bottom, -63), top):
                    band = (top - 1 - y) // thickness
                    if 0 <= band < len(band_ids):
                        blocks[ix, iz, y - Y_MIN] = band_ids[band]
        style = _style_name(profile)
        shore = int(terrain.get("shore") or (6 if style == "cliff" else 0))
        cliff = int(terrain.get("cliff") or (8 if style == "cliff" else 0))
        if shore <= 0 and cliff <= 0 or "shape" not in profile:
            continue
        px = x_coords.astype(np.float64)[:, None] + 0.5
        pz = z_coords.astype(np.float64)[None, :] + 0.5
        if mask_kind(profile) == "rect":
            sd = signed_distance_grid(px, pz, profile["shape"])
        else:
            sd = mask_signed_distance(profile, px, pz, seed)
        stone_name = palette.get("stone")
        if stone_name in idx and stone_name in allowed and cliff > 0:
            wall = selection & (sd >= float(shore)) & (sd < float(shore + cliff))
            xs, zs = np.nonzero(wall)
            stone_i = idx[stone_name]
            for ix, iz in zip(xs.tolist(), zs.tolist()):
                blocks[ix, iz, int(heights[ix, iz]) - Y_MIN] = stone_i
        if shore > 0 and SAND in allowed and SAND in idx:
            beach = selection & (sd >= 0.0) & (sd < float(shore)) & (heights >= int(sea))
            xs, zs = np.nonzero(beach)
            sand_i = idx[SAND]
            for ix, iz in zip(xs.tolist(), zs.tolist()):
                blocks[ix, iz, int(heights[ix, iz]) - Y_MIN] = sand_i


def _apply_food(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed) -> None:
    regions = project.get("regions", [])
    if not any((profile["features"].get("food") or "none") != "none" for _owner_id, profile in _profiles(project)):
        return
    air_i = idx[AIR]
    ixs, izs = np.nonzero(mask)
    for ix, iz in zip(ixs.tolist(), izs.tolist()):
        owner_id = int(owner[ix, iz])
        profile = project["defaultTerrain"] if owner_id < 0 else regions[owner_id]
        food = profile["features"].get("food") or "none"
        if food == "none":
            continue
        x = int(x_coords[ix])
        z = int(z_coords[iz])
        roll = hash32(seed, x, 0, z, 81)
        if roll % 100 >= 8:
            continue
        column_height = int(heights[ix, iz])
        above = column_height + 1
        if above > Y_MAX or int(blocks[ix, iz, above - Y_MIN]) != air_i:
            continue
        surface = block_ids[int(blocks[ix, iz, column_height - Y_MIN])]
        allowed = set(profile["palette"]["allowed"])
        if food == "berries" and "minecraft:sweet_berry_bush" in allowed and surface in PLANT_SOIL:
            blocks[ix, iz, above - Y_MIN] = idx["minecraft:sweet_berry_bush"]
            continue
        if food == "melon" and "minecraft:melon" in allowed and surface in PLANT_SOIL:
            blocks[ix, iz, above - Y_MIN] = idx["minecraft:melon"]
            continue
        if food != "mixed":
            continue
        choice = roll % 4
        near_water = False
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx = ix + dx
            nz = iz + dz
            if 0 <= nx < heights.shape[0] and 0 <= nz < heights.shape[1] and int(heights[nx, nz]) < int(project["world"]["seaLevel"]):
                near_water = True
                break
        if choice == 0 and near_water and "minecraft:sugar_cane" in allowed and surface in {SAND, *PLANT_SOIL}:
            blocks[ix, iz, above - Y_MIN] = idx["minecraft:sugar_cane"]
        elif choice == 1 and "minecraft:sweet_berry_bush" in allowed and surface in PLANT_SOIL:
            blocks[ix, iz, above - Y_MIN] = idx["minecraft:sweet_berry_bush"]
        elif choice == 2 and "minecraft:melon" in allowed and surface in PLANT_SOIL:
            blocks[ix, iz, above - Y_MIN] = idx["minecraft:melon"]
        elif "minecraft:pumpkin" in allowed and surface in PLANT_SOIL:
            blocks[ix, iz, above - Y_MIN] = idx["minecraft:pumpkin"]


def _near_water(heights: np.ndarray, sea: int, radius: int = 10) -> np.ndarray:
    near = heights < int(sea)
    for _step in range(max(0, int(radius))):
        expanded = np.array(near, copy=True)
        expanded[1:, :] |= near[:-1, :]
        expanded[:-1, :] |= near[1:, :]
        expanded[:, 1:] |= near[:, :-1]
        expanded[:, :-1] |= near[:, 1:]
        near = expanded
    return near


def _apply_crystals(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed, sea, warnings: list[str]) -> None:
    regions = project.get("regions", [])
    active = []
    for owner_id, profile in _profiles(project):
        crystals = profile["features"].get("crystals") or {}
        if isinstance(crystals, dict) and crystals.get("enabled"):
            active.append((owner_id, profile, crystals))
    if not active:
        return
    near = _near_water(heights, sea, 10)
    warned: set[str] = set()
    min_x = int(x_coords[0])
    min_z = int(z_coords[0])
    for owner_id, profile, crystals in active:
        allowed = set(profile["palette"]["allowed"])
        choices = [block_id for block_id in CRYSTAL_BLOCKS if block_id in allowed and block_id in idx]
        if not choices:
            message = "skipped ice crystals because no crystal block is allowed"
            if message not in warned:
                warned.add(message)
                warnings.append(message)
            continue
        density = float(crystals.get("density") or 0.2)
        threshold = max(1, int(density * 1000))
        radius = max(1, min(8, int(crystals.get("radius") or 4)))
        peak = max(2, min(24, int(crystals.get("height") or 10)))
        selection = _selection(owner, owner_id, mask) & near & (heights >= int(sea) - 1)
        xs, zs = np.nonzero(selection)
        owner_rect = None if owner_id < 0 else regions[owner_id]["shape"]
        clip = owner_id >= 0 and not plain_rect(profile, int(project["blendRadius"]))
        for ix, iz in zip(xs.tolist(), zs.tolist()):
            x = int(x_coords[ix])
            z = int(z_coords[iz])
            if hash32(seed, x, 0, z, 90) % 1000 >= threshold:
                continue
            if x % 3 != 1 or z % 3 != 1:
                continue
            roll = hash32(seed, x, 1, z, 91)
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    dist = (dx * dx + dz * dz) ** 0.5
                    if dist > radius:
                        continue
                    tx = x + dx
                    tz = z + dz
                    if not _can_write(tx, tz, owner_rect, owner, mask, min_x, min_z, clip, owner_id):
                        continue
                    tix = tx - min_x
                    tiz = tz - min_z
                    if int(heights[tix, tiz]) < int(sea) - 1:
                        continue
                    jitter = hash32(seed, tx, 2, tz, 92) % 3
                    spike = int((1.0 - dist / float(radius)) * peak) - int(jitter)
                    if spike < 1:
                        continue
                    choice = idx[choices[hash32(seed, tx, spike, tz, 93) % len(choices)]]
                    base_y = int(heights[tix, tiz])
                    blocks[tix, tiz, base_y - Y_MIN] = choice
                    for step in range(1, spike + 1):
                        y = base_y + step
                        if y > Y_MAX:
                            break
                        current = block_ids[int(blocks[tix, tiz, y - Y_MIN])]
                        if current not in {AIR, CAVE_AIR} and not current.endswith("_leaves") and current not in {
                            "minecraft:short_grass",
                            "minecraft:fern",
                            "minecraft:dead_bush",
                            "minecraft:poppy",
                            "minecraft:dandelion",
                            "minecraft:sweet_berry_bush",
                        }:
                            break
                        blocks[tix, tiz, y - Y_MIN] = choice


def edge_grid(project: dict, x0: int, z0: int, block_ids: list[str], biome_ids: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Terrain continuation for the 16×16 chunk at (x0, z0), without gameplay features."""
    x_coords = np.arange(int(x0), int(x0) + 16, dtype=np.int32)
    z_coords = np.arange(int(z0), int(z0) + 16, dtype=np.int32)
    idx = {block_id: index for index, block_id in enumerate(block_ids)}
    biome_index = {biome: index for index, biome in enumerate(biome_ids)}
    seed = int(project["world"]["seed"])
    sea = int(project["world"]["seaLevel"])
    heights = _blend_heights(project, x_coords, z_coords, seed, sea)
    owner, stone_i, sub_i, surf_i, water_i, sand_ok, vanilla, _caves, _ores, biomes = _paint_owners(
        project, x_coords, z_coords, idx, biome_index
    )
    blocks = _fill_materials(heights, stone_i, sub_i, surf_i, water_i, sand_ok, vanilla, idx, sea)
    mask = np.ones(heights.shape, dtype=bool)
    _apply_surface_details(project, blocks, heights, owner, mask, x_coords, z_coords, idx, seed, sea)
    return blocks, biomes


def _materials_from_owners(project, owner, idx, biome_index):
    nx, nz = owner.shape
    stone_i = np.empty((nx, nz), dtype=np.uint16)
    sub_i = np.empty((nx, nz), dtype=np.uint16)
    surf_i = np.empty((nx, nz), dtype=np.uint16)
    water_i = np.empty((nx, nz), dtype=np.uint16)
    sand_ok = np.empty((nx, nz), dtype=np.bool_)
    vanilla = np.empty((nx, nz), dtype=np.bool_)
    caves_on = np.empty((nx, nz), dtype=np.bool_)
    ores_on = np.empty((nx, nz), dtype=np.bool_)
    biomes = np.empty((nx, nz), dtype=np.uint8)

    def paint(selection, profile: dict) -> None:
        if not np.any(selection):
            return
        palette = profile["palette"]
        features = profile["features"]
        stone_i[selection] = idx[palette["stone"]]
        sub_i[selection] = idx[palette["subsurface"]]
        surf_i[selection] = idx[palette["surface"]]
        water_i[selection] = idx[palette["water"]]
        sand_ok[selection] = SAND in palette["allowed"]
        vanilla[selection] = palette["stone"] == STONE
        caves_on[selection] = bool(features["caves"])
        ores_on[selection] = bool(features["ores"])
        biomes[selection] = biome_index[profile["vanillaBiome"]]

    paint(np.ones((nx, nz), dtype=bool), project["defaultTerrain"])
    for region_index, region in enumerate(project.get("regions", [])):
        paint(owner == region_index, region)
    return stone_i, sub_i, surf_i, water_i, sand_ok, vanilla, caves_on, ores_on, biomes


def materialize_from_fields(
    project: dict,
    heights: np.ndarray,
    owners: np.ndarray,
    x_coords: np.ndarray,
    z_coords: np.ndarray,
    block_ids: list[str],
    biome_ids: list[str],
    spawn_state: dict | None = None,
    warnings: list[str] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Build the block volume for one window from stored heights and owners."""
    idx = {block_id: index for index, block_id in enumerate(block_ids)}
    biome_index = {biome: index for index, biome in enumerate(biome_ids)}
    seed = int(project["world"]["seed"])
    sea = int(project["world"]["seaLevel"])
    stone_i, sub_i, surf_i, water_i, sand_ok, vanilla, caves_on, ores_on, biomes = _materials_from_owners(
        project, owners, idx, biome_index
    )
    blocks = _fill_materials(heights, stone_i, sub_i, surf_i, water_i, sand_ok, vanilla, idx, sea)
    mask = np.ones(heights.shape, dtype=bool)
    notes = warnings if warnings is not None else []
    _apply_surface_details(project, blocks, heights, owners, mask, x_coords, z_coords, idx, seed, sea)
    _apply_caves(
        blocks,
        heights,
        mask,
        caves_on,
        x_coords,
        z_coords,
        idx,
        seed,
        int(project["world"]["spawn"]["x"]),
        int(project["world"]["spawn"]["z"]),
    )
    _apply_ores(blocks, mask, ores_on, x_coords, z_coords, idx, seed)
    _apply_trees(project, blocks, heights, owners, mask, x_coords, z_coords, block_ids, idx, seed, notes)
    _apply_vegetation(project, blocks, heights, owners, mask, x_coords, z_coords, block_ids, idx, seed)
    _apply_food(project, blocks, heights, owners, mask, x_coords, z_coords, block_ids, idx, seed)
    _apply_crystals(project, blocks, heights, owners, mask, x_coords, z_coords, block_ids, idx, seed, sea, notes)
    if spawn_state is not None:
        _apply_saved_spawn(project, blocks, heights, x_coords, z_coords, idx, spawn_state)
    return blocks, biomes


def _apply_saved_spawn(project, blocks, heights, x_coords, z_coords, idx, spawn_state: dict) -> None:
    min_x = int(x_coords[0])
    max_x = int(x_coords[-1])
    min_z = int(z_coords[0])
    max_z = int(z_coords[-1])
    if spawn_state.get("pad"):
        requested = spawn_state.get("requested") or project["world"]["spawn"]
        _place_pad(
            blocks,
            heights,
            int(requested["x"]),
            int(requested["z"]),
            int(project["world"]["seaLevel"]),
            min_x,
            max_x,
            min_z,
            max_z,
            idx[project["defaultTerrain"]["palette"]["surface"]],
            idx[AIR],
        )
    spawn = spawn_state["spawn"]
    _place_camp(blocks, heights, int(spawn["x"]), int(spawn["z"]), min_x, max_x, min_z, max_z, idx)


def column_fields(project: dict, x_coords: np.ndarray, z_coords: np.ndarray, block_ids: list[str], biome_ids: list[str]):
    idx = {block_id: index for index, block_id in enumerate(block_ids)}
    biome_index = {biome: index for index, biome in enumerate(biome_ids)}
    seed = int(project["world"]["seed"])
    sea = int(project["world"]["seaLevel"])
    heights = _blend_heights(project, x_coords, z_coords, seed, sea)
    owner, _stone, _sub, _surf, _water, _sand, _vanilla, _caves, _ores, biomes = _paint_owners(
        project, x_coords, z_coords, idx, biome_index
    )
    return heights.astype(np.int16), owner.astype(np.int16), biomes.astype(np.uint8)
