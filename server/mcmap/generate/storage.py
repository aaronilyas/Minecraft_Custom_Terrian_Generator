"""Column cache under project_dir/cache. Sample reads are cached; generation loads a private copy."""

from __future__ import annotations

import json
import os
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


def save_columns(
    project_dir: str,
    blocks: np.ndarray | None,
    heights: np.ndarray,
    biomes: np.ndarray,
    terrain_meta: dict,
    owners: np.ndarray | None = None,
) -> None:
    folder = cache_dir(project_dir)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"heights": heights, "biomes": biomes}
    if blocks is not None:
        payload["blocks"] = blocks
    if owners is not None:
        payload["owners"] = owners
    partial = folder / "_columns_partial.npz"
    if partial.exists():
        partial.unlink()
    np.savez_compressed(partial, **payload)
    os.replace(partial, folder / "columns.npz")
    meta_partial = folder / "_terrain_meta.json"
    meta_partial.write_text(json.dumps(terrain_meta), encoding="utf-8")
    os.replace(meta_partial, folder / "terrain_meta.json")


def _unpack_columns(data, terrain_meta: dict) -> dict:
    compact = "blocks" not in data.files
    return {
        "blocks": None if compact else np.array(data["blocks"]),
        "heights": np.array(data["heights"]),
        "biomes": np.array(data["biomes"]),
        "owners": np.array(data["owners"]) if "owners" in data.files else None,
        "compact": compact,
        "block_ids": list(terrain_meta["blockIds"]),
        "biome_ids": list(terrain_meta["biomeIds"]),
        "min_x": int(terrain_meta["minX"]),
        "min_z": int(terrain_meta["minZ"]),
        "y_min": int(terrain_meta["yMin"]),
        "y_max": int(terrain_meta["yMax"]),
        "non_region": terrain_meta.get("nonRegion"),
        "regions": terrain_meta.get("regions"),
        "spawn": terrain_meta.get("spawn"),
        "spawnPad": terrain_meta.get("spawnPad"),
        "spawnRequested": terrain_meta.get("spawnRequested"),
    }


def try_load_columns(project_dir: str) -> dict | None:
    folder = cache_dir(project_dir)
    col_path = folder / "columns.npz"
    meta_path = folder / "terrain_meta.json"
    if not col_path.is_file() or not meta_path.is_file():
        return None
    terrain_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    with np.load(col_path) as data:
        return _unpack_columns(data, terrain_meta)


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
        unpacked = _unpack_columns(data, terrain_meta)
    world = {
        **unpacked,
        "meta": meta,
    }
    _SAMPLE_CACHE["world"] = (key, world)
    return world
