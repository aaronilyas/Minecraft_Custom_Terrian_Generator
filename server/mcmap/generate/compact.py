"""Bounded-memory generation for worlds that do not fit in a block volume.

Heights, owners, and biomes are stored for the playable square. Block volumes
are built one tile at a time for sampling and export. Padding columns outside
the playable square are not stored; export fills them with terrain continuation
and no gameplay features.
"""

from __future__ import annotations

import os
import zlib
from collections import defaultdict

import numpy as np

from mcmap.blocks import load_registry
from mcmap.export.writer import _level_dat, _write_region, encode_chunk
from mcmap.generate.terrain import (
    FEATURE_MARGIN,
    Y_MAX,
    Y_MIN,
    _apply_spawn,
    column_fields,
    edge_grid,
    materialize_from_fields,
)
from mcmap.model import border_square, world_coverage

AIR = "minecraft:air"
CAVE_AIR = "minecraft:cave_air"
SECTION_MIN = -4
WORLD_HEIGHT = 384


class GenerationCancelled(RuntimeError):
    def __init__(self) -> None:
        super().__init__("cancelled")


def _check(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise GenerationCancelled()


def compute_fields(project: dict, block_ids: list[str], biome_ids: list[str], progress=None, cancel=None, bounds=None):
    min_x, min_z, max_x, max_z = bounds or border_square(project)
    heights = np.empty((max_x - min_x, max_z - min_z), dtype=np.int16)
    owners = np.empty(heights.shape, dtype=np.int16)
    biomes = np.empty(heights.shape, dtype=np.uint8)
    tile = 192
    steps = ((max_x - min_x + tile - 1) // tile) * ((max_z - min_z + tile - 1) // tile)
    done = 0
    for x0 in range(min_x, max_x, tile):
        for z0 in range(min_z, max_z, tile):
            _check(cancel)
            x1 = min(max_x, x0 + tile)
            z1 = min(max_z, z0 + tile)
            x_coords = np.arange(x0, x1, dtype=np.int32)
            z_coords = np.arange(z0, z1, dtype=np.int32)
            tile_heights, tile_owners, tile_biomes = column_fields(project, x_coords, z_coords, block_ids, biome_ids)
            heights[x0 - min_x : x1 - min_x, z0 - min_z : z1 - min_z] = tile_heights
            owners[x0 - min_x : x1 - min_x, z0 - min_z : z1 - min_z] = tile_owners
            biomes[x0 - min_x : x1 - min_x, z0 - min_z : z1 - min_z] = tile_biomes
            done += 1
            if progress is not None and steps:
                progress("terrain", 0.05 + 0.55 * done / steps, f"Sampling terrain ({int(100 * done / steps)}%)")
    return {
        "heights": heights,
        "owners": owners,
        "biomes": biomes,
        "min_x": min_x,
        "min_z": min_z,
        "y_min": Y_MIN,
        "y_max": Y_MAX,
    }


def _slice_field(fields: dict, x0: int, x1: int, z0: int, z1: int):
    min_x = int(fields["min_x"])
    min_z = int(fields["min_z"])
    heights = fields["heights"][x0 - min_x : x1 - min_x, z0 - min_z : z1 - min_z]
    owners = fields["owners"][x0 - min_x : x1 - min_x, z0 - min_z : z1 - min_z]
    x_coords = np.arange(x0, x1, dtype=np.int32)
    z_coords = np.arange(z0, z1, dtype=np.int32)
    return heights, owners, x_coords, z_coords


def spawn_window(project: dict, fields: dict, block_ids: list[str], biome_ids: list[str]):
    min_x, min_z, max_x, max_z = border_square(project)
    requested = project["world"]["spawn"]
    rx = int(requested["x"])
    rz = int(requested["z"])
    x0 = max(min_x, rx - 56)
    x1 = min(max_x, rx + 57)
    z0 = max(min_z, rz - 56)
    z1 = min(max_z, rz + 57)
    heights, owners, x_coords, z_coords = _slice_field(fields, x0, x1, z0, z1)
    warnings: list[str] = []
    blocks, _biomes = materialize_from_fields(
        project, heights, owners, x_coords, z_coords, block_ids, biome_ids, None, warnings
    )
    spawn, adjusted, checks, pad = _apply_spawn(project, blocks, heights, x_coords, z_coords, block_ids, {block_id: index for index, block_id in enumerate(block_ids)}, warnings)
    return {
        "spawn": spawn,
        "spawnAdjusted": bool(adjusted),
        "spawnChecks": checks,
        "spawnPad": bool(pad),
        "warnings": warnings,
        "requested": {"x": rx, "z": rz},
    }


def _spawn_state(meta: dict) -> dict:
    return {
        "spawn": meta["spawn"],
        "pad": bool(meta.get("spawnPad")),
        "requested": meta.get("requested") or meta.get("spawnRequested") or meta["spawn"],
    }


def materialize_window(project, fields, block_ids, biome_ids, x0, x1, z0, z1, spawn_state):
    playable = border_square(project)
    cx0 = max(int(playable[0]), int(x0))
    cz0 = max(int(playable[1]), int(z0))
    cx1 = min(int(playable[2]), int(x1))
    cz1 = min(int(playable[3]), int(z1))
    if cx0 >= cx1 or cz0 >= cz1:
        return None
    heights, owners, x_coords, z_coords = _slice_field(fields, cx0, cx1, cz0, cz1)
    blocks, biomes = materialize_from_fields(
        project, heights, owners, x_coords, z_coords, block_ids, biome_ids, spawn_state, []
    )
    return {"blocks": blocks, "biomes": biomes, "min_x": cx0, "min_z": cz0}


def sample_from_fields(project, fields, block_ids, biome_ids, x: int, z: int, spawn_state: dict) -> dict:
    min_x, min_z, max_x, max_z = border_square(project)
    coverage = world_coverage(project)["storage"]
    if not (coverage["minX"] <= x < coverage["maxX"] and coverage["minZ"] <= z < coverage["maxZ"]):
        raise RuntimeError("column is outside the border")
    if not (min_x <= x < max_x and min_z <= z < max_z):
        blocks, biomes = edge_grid(project, (x // 16) * 16, (z // 16) * 16, block_ids, biome_ids)
        local_x = x - (x // 16) * 16
        local_z = z - (z // 16) * 16
        column = blocks[local_x, local_z]
        biome = biome_ids[int(biomes[local_x, local_z])]
        air = block_ids.index(AIR)
        named = [{"y": Y_MIN + index, "id": block_ids[int(block_index)]} for index, block_index in enumerate(column.tolist()) if int(block_index) != air]
        surface = named[-1]["y"] if named else Y_MIN
        return {"x": int(x), "z": int(z), "surfaceY": surface, "biome": biome, "blocks": named, "edge": True}
    x0 = max(min_x, x - FEATURE_MARGIN)
    x1 = min(max_x, x + FEATURE_MARGIN + 1)
    z0 = max(min_z, z - FEATURE_MARGIN)
    z1 = min(max_z, z + FEATURE_MARGIN + 1)
    window = materialize_window(project, fields, block_ids, biome_ids, x0, x1, z0, z1, spawn_state)
    ix = x - int(window["min_x"])
    iz = z - int(window["min_z"])
    air = block_ids.index(AIR)
    column = []
    for index, block_index in enumerate(window["blocks"][ix, iz].tolist()):
        if int(block_index) != air:
            column.append({"y": Y_MIN + index, "id": block_ids[int(block_index)]})
    return {
        "x": int(x),
        "z": int(z),
        "surfaceY": int(fields["heights"][x - int(fields["min_x"]), z - int(fields["min_z"])]),
        "biome": biome_ids[int(window["biomes"][ix, iz])],
        "blocks": column,
        "edge": False,
    }


def _motion_ids(registry, block_ids: list[str]) -> tuple[set[int], int, int]:
    air_i = block_ids.index(AIR)
    cave_i = block_ids.index(CAVE_AIR)
    fluids = {"minecraft:water", "minecraft:lava"}
    motion = set()
    for index, block_id in enumerate(block_ids):
        if block_id in {AIR, CAVE_AIR}:
            continue
        if registry.is_solid(block_id) or block_id in fluids:
            motion.add(index)
    return motion, air_i, cave_i


def _chunk_arrays(project, window, edge, block_ids, biome_ids, cx: int, cz: int, air_i: int):
    local = np.full((16, 16, WORLD_HEIGHT), air_i, dtype=np.uint16)
    default_biome = project["defaultTerrain"]["vanillaBiome"]
    local_biome = np.full((16, 16), default_biome, dtype=object)
    x0 = cx * 16
    z0 = cz * 16
    playable = border_square(project)
    for local_x in range(16):
        wx = x0 + local_x
        for local_z in range(16):
            wz = z0 + local_z
            if playable[0] <= wx < playable[2] and playable[1] <= wz < playable[3] and window is not None:
                ix = wx - int(window["min_x"])
                iz = wz - int(window["min_z"])
                if 0 <= ix < window["blocks"].shape[0] and 0 <= iz < window["blocks"].shape[1]:
                    stored = window["blocks"].shape[2]
                    local[local_x, local_z, :stored] = window["blocks"][ix, iz]
                    local_biome[local_x, local_z] = biome_ids[int(window["biomes"][ix, iz])]
                    continue
            if edge is not None:
                stored = edge[0].shape[2]
                local[local_x, local_z, :stored] = edge[0][local_x, local_z]
                local_biome[local_x, local_z] = biome_ids[int(edge[1][local_x, local_z])]
    return local, local_biome


def export_compact(project, fields, block_ids, biome_ids, spawn_state, world_dir, progress=None, cancel=None) -> int:
    registry = load_registry()
    motion_ids, air_i, cave_i = _motion_ids(registry, block_ids)
    coverage = world_coverage(project)
    storage = coverage["storage"]
    cx0, cx1 = int(storage["chunkMinX"]), int(storage["chunkMaxX"])
    cz0, cz1 = int(storage["chunkMinZ"]), int(storage["chunkMaxZ"])
    grouped: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    total = 0
    for cz in range(cz0, cz1 + 1):
        for cx in range(cx0, cx1 + 1):
            grouped[(cx // 32, cz // 32)].append((cx, cz))
            total += 1
    region_dir = world_dir / "region"
    region_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for (rx, rz), chunks in grouped.items():
        _check(cancel)
        payload: dict[int, bytes] = {}
        chunks.sort()
        cursor = 0
        while cursor < len(chunks):
            group = chunks[cursor : cursor + 16]
            cursor += 16
            _check(cancel)
            xs = [cx * 16 for cx, _cz in group]
            zs = [cz * 16 for _cx, cz in group]
            x0 = min(xs) - FEATURE_MARGIN
            x1 = max(xs) + 16 + FEATURE_MARGIN
            z0 = min(zs) - FEATURE_MARGIN
            z1 = max(zs) + 16 + FEATURE_MARGIN
            window = materialize_window(project, fields, block_ids, biome_ids, x0, x1, z0, z1, spawn_state)
            edges: dict[tuple[int, int], tuple] = {}
            for cx, cz in group:
                x_origin = cx * 16
                z_origin = cz * 16
                playable = border_square(project)
                needs_edge = x_origin < playable[0] or x_origin + 16 > playable[2] or z_origin < playable[1] or z_origin + 16 > playable[3]
                edge = None
                if needs_edge:
                    edge = edges.get((cx, cz))
                    if edge is None:
                        edge = edge_grid(project, x_origin, z_origin, block_ids, biome_ids)
                        edges[(cx, cz)] = edge
                local, local_biome = _chunk_arrays(project, window, edge, block_ids, biome_ids, cx, cz, air_i)
                raw = encode_chunk(registry, block_ids, local, local_biome, cx, cz, motion_ids, air_i, cave_i)
                payload[(cx % 32) + (cz % 32) * 32] = zlib.compress(raw)
                written += 1
            if progress is not None and total:
                progress("export", written / total, f"Writing chunks ({written}/{total})")
        partial = region_dir / f".r.{rx}.{rz}.mca.partial"
        _write_region(partial, payload)
        os.replace(partial, region_dir / f"r.{rx}.{rz}.mca")
    _level_dat(project, spawn_state["spawn"], world_dir / "level.dat")
    return written
