"""Public terrain generation and column sampling."""

from __future__ import annotations

import json

import numpy as np

from mcmap.blocks import load_registry
from mcmap.generate.preview import write_mesh
from mcmap.generate.storage import cache_dir, load_world, non_region_key, save_columns, try_load_columns
from mcmap.generate.terrain import Y_MAX, Y_MIN, build_scope_mask, generate_arrays
from mcmap.model import VANILLA_BIOMES, border_square, generation_fingerprint, now_iso

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


def generate(project: dict, project_dir: str, scope: dict) -> dict:
    block_ids, biome_ids = _registry_tables()
    mask, requested_full = build_scope_mask(project, scope)
    previous = None if requested_full else try_load_columns(project_dir)
    if previous is None or not _compatible(previous, project, block_ids, biome_ids):
        previous = None
        mask = np.ones_like(mask, dtype=bool)
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
