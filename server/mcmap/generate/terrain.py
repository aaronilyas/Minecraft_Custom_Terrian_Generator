"""Column terrain, features, and spawn. Heights blend; materials and features use the hard owner."""

from __future__ import annotations

import numpy as np

from mcmap.generate.noise import cave_density, hash32, hash32_array, height_noise_grid
from mcmap.model import TREE_BLOCKS, border_square

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


def signed_distance_grid(px: np.ndarray, pz: np.ndarray, rect: dict) -> np.ndarray:
    minx = float(rect["x"])
    maxx = float(rect["x"] + rect["width"])
    minz = float(rect["z"])
    maxz = float(rect["z"] + rect["depth"])
    dx_out = np.maximum(np.maximum(minx - px, 0.0), px - maxx)
    dz_out = np.maximum(np.maximum(minz - pz, 0.0), pz - maxz)
    outside = (dx_out > 0.0) | (dz_out > 0.0)
    dist_out = np.sqrt(dx_out * dx_out + dz_out * dz_out)
    dist_in = np.minimum(np.minimum(px - minx, maxx - px), np.minimum(pz - minz, maxz - pz))
    return np.where(outside, -dist_out, dist_in)


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


def _profile_heights(profile: dict, x_coords: np.ndarray, z_coords: np.ndarray, seed: int, sea: int) -> np.ndarray:
    terrain = profile["terrain"]
    base = int(terrain["baseHeight"])
    amplitude = int(terrain["amplitude"])
    if amplitude == 0:
        heights = np.full((x_coords.size, z_coords.size), base, dtype=np.int32)
    else:
        noise = height_noise_grid(seed, x_coords, z_coords, float(terrain["roughness"]))
        raw = base + amplitude * noise
        heights = np.asarray([round(float(value)) for value in raw.reshape(-1)], dtype=np.int32).reshape(raw.shape)
    np.clip(heights, 8, 180, out=heights)
    if terrain.get("water"):
        np.minimum(heights, int(sea) - 4, out=heights)
    return heights


def _blend_heights(project: dict, x_coords: np.ndarray, z_coords: np.ndarray, seed: int, sea: int) -> np.ndarray:
    blend = int(project["blendRadius"])
    heights = _profile_heights(project["defaultTerrain"], x_coords, z_coords, seed, sea)
    for region in project.get("regions", []):
        weights = influence_grid(region["shape"], blend, x_coords, z_coords)
        if not np.any(weights > 0.0):
            continue
        region_heights = _profile_heights(region, x_coords, z_coords, seed, sea)
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
    for region_index, region in enumerate(project.get("regions", [])):
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


def _can_write(x: int, z: int, owner_rect, owner: np.ndarray, mask: np.ndarray, min_x: int, min_z: int) -> bool:
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
    return int(shape["x"]) <= x < int(shape["x"]) + int(shape["width"]) and int(shape["z"]) <= z < int(shape["z"]) + int(
        shape["depth"]
    )


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
    for iz, z in enumerate(z_coords.tolist()):
        if z % 5 != 2:
            continue
        for ix, x in enumerate(x_coords.tolist()):
            if x % 5 != 2 or not mask[ix, iz]:
                continue
            owner_id = int(owner[ix, iz])
            profile = project["defaultTerrain"] if owner_id < 0 else regions[owner_id]
            trees = profile["features"]["trees"]
            kind = trees["kind"]
            if kind == "none":
                continue
            threshold = max(1, int(float(trees["density"]) * 8000))
            if hash32(seed, x, 0, z, 70) % 1000 >= threshold:
                continue
            if not _warn_trees(profile, warnings, warned):
                continue
            column_height = int(heights[ix, iz])
            surface = block_ids[int(blocks[ix, iz, column_height - Y_MIN])]
            roll = hash32(seed, x, 0, z, 71)
            owner_rect = None if owner_id < 0 else regions[owner_id]["shape"]
            if kind == "cactus":
                if surface != SAND:
                    continue
                cactus_i = idx["minecraft:cactus"]
                for step in range(1, 2 + (roll % 2) + 1):
                    if _can_write(x, z, owner_rect, owner, mask, min_x, min_z):
                        _set_block(blocks, x, z, column_height + step, cactus_i, min_x, min_z)
                continue
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
            log_i = idx[LOGS[kind]]
            leaf_i = idx[LEAVES[kind]]
            for step in range(1, trunk_h + 1):
                if _can_write(x, z, owner_rect, owner, mask, min_x, min_z):
                    _set_block(blocks, x, z, column_height + step, log_i, min_x, min_z)
            top = column_height + trunk_h
            for y in range(top - 2, top + 2):
                for dx in range(-radius, radius + 1):
                    for dz in range(-radius, radius + 1):
                        if manhattan is not None and abs(dx) + abs(dz) > manhattan:
                            continue
                        if dx == 0 and dz == 0 and y <= top:
                            continue
                        tx = x + dx
                        tz = z + dz
                        if not _can_write(tx, tz, owner_rect, owner, mask, min_x, min_z):
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
    selected = np.argwhere(mask & caves_on & (chebyshev > 12))
    if len(selected) == 0:
        return
    stone_i = idx[STONE]
    deep_i = idx[DEEPSLATE]
    cave_i = idx[CAVE_AIR]
    batch = 128
    for start in range(0, len(selected), batch):
        part = selected[start : start + batch]
        ixs = part[:, 0]
        izs = part[:, 1]
        column_heights = heights[ixs, izs].astype(np.int32)
        limit = int(column_heights.max()) - 5
        if limit < -59:
            continue
        y_vals = np.arange(-59, limit + 1, dtype=np.int32)
        density = cave_density(seed, x_coords[ixs], y_vals, z_coords[izs])
        for row in range(len(part)):
            y_end = int(column_heights[row]) - 5
            if y_end < -59:
                continue
            count = y_end - (-59) + 1
            hot = np.nonzero(density[row, :count] > 0.58)[0]
            ix = int(ixs[row])
            iz = int(izs[row])
            for hot_index in hot.tolist():
                y = int(y_vals[hot_index])
                iy = y - Y_MIN
                current = int(blocks[ix, iz, iy])
                if current == stone_i or current == deep_i:
                    blocks[ix, iz, iy] = cave_i


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


def _column_safe(blocks, heights, block_ids, ix: int, iz: int) -> bool:
    column_height = int(heights[ix, iz])
    surface = block_ids[int(blocks[ix, iz, column_height - Y_MIN])]
    if surface in (WATER, LAVA):
        return False
    for dy in (1, 2):
        y = column_height + dy
        if y < Y_MIN or y > Y_MAX:
            return False
        if block_ids[int(blocks[ix, iz, y - Y_MIN])] != AIR:
            return False
    return True


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
    for x, z in _spiral(rx, rz, 32):
        if not (min_x <= x <= max_x and min_z <= z <= max_z):
            continue
        ix = x - min_x
        iz = z - min_z
        if 0 <= ix < nx and 0 <= iz < nz and _column_safe(blocks, heights, block_ids, ix, iz):
            found = (x, z)
            break
    if found is None:
        warnings.append("spawn pad built")
        surface_i = idx[project["defaultTerrain"]["palette"]["surface"]]
        air_i = idx[AIR]
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
        sx, sy, sz = rx, sea + 1, rz
    else:
        sx, sz = found
        sy = int(heights[sx - min_x, sz - min_z]) + 1
    _place_camp(blocks, heights, sx, sz, min_x, max_x, min_z, max_z, idx)
    adjusted = sx != rx or sy != ry or sz != rz
    return {"x": int(sx), "y": int(sy), "z": int(sz)}, adjusted


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
    _apply_caves(blocks, heights, mask, caves_on, x_coords, z_coords, idx, seed, spawn_x, spawn_z)
    _apply_ores(blocks, mask, ores_on, x_coords, z_coords, idx, seed)
    _apply_trees(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed, warnings)
    _apply_vegetation(project, blocks, heights, owner, mask, x_coords, z_coords, block_ids, idx, seed)
    spawn, adjusted = _apply_spawn(project, blocks, heights, x_coords, z_coords, block_ids, idx, warnings)
    return {
        "blocks": blocks,
        "heights": heights.astype(np.int16),
        "biomes": biomes.astype(np.uint8),
        "spawn": spawn,
        "spawnAdjusted": bool(adjusted),
        "warnings": warnings,
        "columnsWritten": int(mask.sum()),
        "chunksWritten": _count_chunks(mask, x_coords, z_coords),
        "min_x": min_x,
        "min_z": min_z,
        "y_min": Y_MIN,
        "y_max": Y_MAX,
    }
