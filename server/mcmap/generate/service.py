"""Public terrain generation and column sampling."""

from __future__ import annotations

import json

import numpy as np

from mcmap.blocks import load_registry
from mcmap.generate.preview import write_mesh
from mcmap.generate.storage import cache_dir, load_world, non_region_key, save_columns, try_load_columns
from mcmap.generate.terrain import Y_MAX, Y_MIN, build_scope_mask, columns_near_rect, generate_arrays
from mcmap.model import VANILLA_BIOMES, border_square, generation_fingerprint, generation_inputs, now_iso

AIR = "minecraft:air"


def _registry_tables() -> tuple[list[str], list[str]]:
    registry = load_registry()
    return list(registry.blocks.keys()), list(VANILLA_BIOMES)


def _compatible(previous: dict, project: dict, block_ids: list[str], biome_ids: list[str]) -> bool:
    min_x, min_z, max_x, max_z = border_square(project)
    ny = Y_MAX - Y_MIN + 1
    return (
        previous.get("non_region") == non_region_key(project)
        and previous.get("block_ids") == block_ids
        and previous.get("biome_ids") == biome_ids
        and int(previous["min_x"]) == min_x
        and int(previous["min_z"]) == min_z
        and int(previous["y_min"]) == Y_MIN
        and int(previous["y_max"]) == Y_MAX
        and previous["blocks"].shape == (max_x - min_x, max_z - min_z, ny)
        and previous["heights"].shape == (max_x - min_x, max_z - min_z)
        and previous["biomes"].shape == (max_x - min_x, max_z - min_z)
    )


def _changed_rects(old_regions: list, new_regions: list) -> list[dict]:
    old_by_id = {region["id"]: region for region in old_regions}
    new_by_id = {region["id"]: region for region in new_regions}
    shared_old = [region["id"] for region in old_regions if region["id"] in new_by_id]
    shared_new = [region["id"] for region in new_regions if region["id"] in old_by_id]
    if shared_old != shared_new:
        return [region["shape"] for region in old_regions] + [region["shape"] for region in new_regions]
    rects = []
    for region in old_regions:
        current = new_by_id.get(region["id"])
        if current is None:
            rects.append(region["shape"])
        elif current != region:
            rects.append(region["shape"])
            rects.append(current["shape"])
    for region in new_regions:
        if region["id"] not in old_by_id:
            rects.append(region["shape"])
    return rects


def _mark_column(mask: np.ndarray, x: int, z: int, min_x: int, min_z: int) -> None:
    ix = x - min_x
    iz = z - min_z
    if 0 <= ix < mask.shape[0] and 0 <= iz < mask.shape[1]:
        mask[ix, iz] = True


def _mark_spawn_columns(mask: np.ndarray, spawn: dict, min_x: int, min_z: int) -> None:
    sx = int(spawn["x"])
    sz = int(spawn["z"])
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            _mark_column(mask, sx + dx, sz + dz, min_x, min_z)
    _mark_column(mask, sx + 2, sz, min_x, min_z)
    _mark_column(mask, sx + 3, sz, min_x, min_z)


def _expand_partial_mask(project: dict, previous: dict, mask: np.ndarray) -> np.ndarray:
    """Cover every column a region move, delete, or edit can still affect.

    A partial scope is only an optimization. The saved world is stamped with the
    final fingerprint, so columns left over from the previous plan must be rebuilt.
    """
    old_regions = previous.get("regions")
    new_regions = generation_inputs(project)["regions"]
    if not isinstance(old_regions, list) or not isinstance(previous.get("spawn"), dict):
        return np.ones_like(mask, dtype=bool)
    if old_regions == new_regions:
        return mask
    min_x, min_z, _max_x, _max_z = border_square(project)
    x_coords = np.arange(min_x, min_x + mask.shape[0], dtype=np.int32)
    z_coords = np.arange(min_z, min_z + mask.shape[1], dtype=np.int32)
    expanded = np.array(mask, copy=True)
    blend = int(project["blendRadius"])
    for rect in _changed_rects(old_regions, new_regions):
        expanded |= columns_near_rect(rect, blend, x_coords, z_coords)
    _mark_spawn_columns(expanded, previous["spawn"], min_x, min_z)
    _mark_spawn_columns(expanded, project["world"]["spawn"], min_x, min_z)
    return expanded


def generate(project: dict, project_dir: str, scope: dict) -> dict:
    block_ids, biome_ids = _registry_tables()
    mask, requested_full = build_scope_mask(project, scope)
    previous = None if requested_full else try_load_columns(project_dir)
    if previous is None or not _compatible(previous, project, block_ids, biome_ids):
        previous = None
        mask = np.ones_like(mask, dtype=bool)
    elif not requested_full:
        mask = _expand_partial_mask(project, previous, mask)
    generated = generate_arrays(project, mask, previous, block_ids, biome_ids)
    folder = cache_dir(project_dir)
    folder.mkdir(parents=True, exist_ok=True)
    terrain_meta = {
        "nonRegion": non_region_key(project),
        "blockIds": block_ids,
        "biomeIds": biome_ids,
        "minX": generated["min_x"],
        "minZ": generated["min_z"],
        "yMin": generated["y_min"],
        "yMax": generated["y_max"],
        "regions": generation_inputs(project)["regions"],
        "spawn": generated["spawn"],
    }
    save_columns(project_dir, generated["blocks"], generated["heights"], generated["biomes"], terrain_meta)
    world = {
        "blocks": generated["blocks"],
        "heights": generated["heights"],
        "biomes": generated["biomes"],
        "block_ids": block_ids,
        "biome_ids": biome_ids,
        "min_x": generated["min_x"],
        "min_z": generated["min_z"],
        "y_min": generated["y_min"],
        "y_max": generated["y_max"],
    }
    write_mesh(project, world, str(folder / "mesh.json"))
    fingerprint = generation_fingerprint(project)
    document = {
        "generated": True,
        "fingerprint": fingerprint,
        "spawn": generated["spawn"],
        "spawnAdjusted": generated["spawnAdjusted"],
        "warnings": generated["warnings"],
        "columnsWritten": generated["columnsWritten"],
        "finishedAt": now_iso(),
    }
    (folder / "last_generate.json").write_text(json.dumps(document), encoding="utf-8")
    return {
        "ok": True,
        "columnsWritten": generated["columnsWritten"],
        "chunksWritten": generated["chunksWritten"],
        "spawn": generated["spawn"],
        "spawnAdjusted": generated["spawnAdjusted"],
        "warnings": generated["warnings"],
        "fingerprint": fingerprint,
    }


def sample_column(project: dict, project_dir: str, x: int, z: int) -> dict:
    world = load_world(project_dir, generation_fingerprint(project))
    x = int(x)
    z = int(z)
    ix = x - int(world["min_x"])
    iz = z - int(world["min_z"])
    blocks = world["blocks"]
    if not (0 <= ix < blocks.shape[0] and 0 <= iz < blocks.shape[1]):
        raise RuntimeError("column is outside the border")
    block_ids = world["block_ids"]
    air = block_ids.index(AIR)
    column = []
    y_min = int(world["y_min"])
    for iy, block_index in enumerate(blocks[ix, iz].tolist()):
        if block_index != air:
            column.append({"y": y_min + iy, "id": block_ids[int(block_index)]})
    return {
        "x": x,
        "z": z,
        "surfaceY": int(world["heights"][ix, iz]),
        "biome": world["biome_ids"][int(world["biomes"][ix, iz])],
        "blocks": column,
    }
