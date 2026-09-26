"""Column cache under project_dir/cache. Sample reads are cached; generation loads a private copy."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from mcmap.model import generation_inputs

_SAMPLE_CACHE: dict[str, tuple] = {}


def non_region_key(project: dict) -> str:
    data = dict(generation_inputs(project))
    data.pop("regions", None)
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def cache_dir(project_dir: str) -> Path:
    return Path(project_dir) / "cache"


def save_columns(project_dir: str, blocks: np.ndarray, heights: np.ndarray, biomes: np.ndarray, terrain_meta: dict) -> None:
    folder = cache_dir(project_dir)
    folder.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(folder / "columns.npz", blocks=blocks, heights=heights, biomes=biomes)
    (folder / "terrain_meta.json").write_text(json.dumps(terrain_meta), encoding="utf-8")


def try_load_columns(project_dir: str) -> dict | None:
    folder = cache_dir(project_dir)
    col_path = folder / "columns.npz"
    meta_path = folder / "terrain_meta.json"
    if not col_path.is_file() or not meta_path.is_file():
        return None
    terrain_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    with np.load(col_path) as data:
        blocks = np.array(data["blocks"])
        heights = np.array(data["heights"])
        biomes = np.array(data["biomes"])
    return {
        "blocks": blocks,
        "heights": heights,
        "biomes": biomes,
        "block_ids": list(terrain_meta["blockIds"]),
        "biome_ids": list(terrain_meta["biomeIds"]),
        "min_x": int(terrain_meta["minX"]),
        "min_z": int(terrain_meta["minZ"]),
        "y_min": int(terrain_meta["yMin"]),
        "y_max": int(terrain_meta["yMax"]),
        "non_region": terrain_meta.get("nonRegion"),
    }


def load_world(project_dir: str, fingerprint: str) -> dict:
    folder = cache_dir(project_dir)
    meta_path = folder / "last_generate.json"
    col_path = folder / "columns.npz"
    terrain_path = folder / "terrain_meta.json"
    if not meta_path.is_file() or not col_path.is_file() or not terrain_path.is_file():
        raise RuntimeError("not_generated")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("fingerprint") != fingerprint or not meta.get("generated"):
        raise RuntimeError("not_generated")
    key = (str(col_path.resolve()), col_path.stat().st_mtime_ns, fingerprint)
    cached = _SAMPLE_CACHE.get("world")
    if cached and cached[0] == key:
        return cached[1]
    terrain_meta = json.loads(terrain_path.read_text(encoding="utf-8"))
    with np.load(col_path) as data:
        blocks = np.array(data["blocks"])
        heights = np.array(data["heights"])
        biomes = np.array(data["biomes"])
    world = {
        "blocks": blocks,
        "heights": heights,
        "biomes": biomes,
        "block_ids": list(terrain_meta["blockIds"]),
        "biome_ids": list(terrain_meta["biomeIds"]),
        "min_x": int(terrain_meta["minX"]),
        "min_z": int(terrain_meta["minZ"]),
        "y_min": int(terrain_meta["yMin"]),
        "y_max": int(terrain_meta["yMax"]),
        "meta": meta,
    }
    _SAMPLE_CACHE["world"] = (key, world)
    return world
