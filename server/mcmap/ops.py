from __future__ import annotations

from copy import deepcopy
from typing import Any

from mcmap.blocks import BlockRegistry
from mcmap.model import (
    COLOR_RE,
    MAX_SEED,
    VANILLA_BIOMES,
    _is_int,
    _point_xz,
    coerce_float,
    coerce_int,
    coerce_shape,
    dimension_message,
    dimension_ok,
    err,
    is_uuid,
    make_border,
    new_id,
    now_iso,
    validate_project,
    validate_shape,
)

OPS = (
    "world.set_meta",
    "region.create",
    "region.update",
    "region.move",
    "region.delete",
    "asset.delete",
)


def _merge_palette(base: dict, patch: dict) -> dict:
    merged = deepcopy(base)
    for key in ("surface", "subsurface", "stone", "water"):
        if key in patch:
            merged[key] = patch[key]
    if "allowed" in patch:
        merged["allowed"] = list(patch["allowed"])
    if "strata" in patch:
        merged["strata"] = [] if patch["strata"] is None else list(patch["strata"])
    for key in ("surface", "subsurface", "stone", "water"):
        if merged[key] not in merged["allowed"]:
            merged["allowed"].append(merged[key])
    return merged


def _merge_terrain(base: dict, patch: dict) -> dict:
    merged = deepcopy(base)
    merged.update(patch)
    for key in ("baseHeight", "amplitude"):
        if key in merged:
            coerced = coerce_int(merged[key])
            if coerced is not None:
                merged[key] = coerced
    if "roughness" in merged:
        coerced = coerce_float(merged["roughness"])
        if coerced is not None:
            merged["roughness"] = coerced
    if isinstance(merged.get("water"), str):
        if merged["water"].lower() in {"true", "false"}:
            merged["water"] = merged["water"].lower() == "true"
    return merged


def _merge_features(base: dict, patch: dict) -> dict:
    merged = deepcopy(base)
    if "trees" in patch and isinstance(patch["trees"], dict):
        trees = dict(merged.get("trees") or {})
        trees.update(patch["trees"])
        if "density" in trees:
            coerced = coerce_float(trees["density"])
            if coerced is not None:
                trees["density"] = coerced
        merged["trees"] = trees
    for key in ("vegetation", "ores", "caves", "food"):
        if key in patch:
            value = patch[key]
            if key in {"ores", "caves"} and isinstance(value, str) and value.lower() in {"true", "false"}:
                value = value.lower() == "true"
            merged[key] = value
    if "crystals" in patch:
        if patch["crystals"] is None:
            merged.pop("crystals", None)
        elif isinstance(patch["crystals"], dict):
            crystals = dict(merged.get("crystals") or {})
            crystals.update(patch["crystals"])
            for key in ("radius", "height"):
                if key in crystals:
                    coerced = coerce_int(crystals[key])
                    if coerced is not None:
                        crystals[key] = coerced
            if "density" in crystals:
                coerced = coerce_float(crystals["density"])
                if coerced is not None:
                    crystals["density"] = coerced
            if isinstance(crystals.get("enabled"), str) and crystals["enabled"].lower() in {"true", "false"}:
                crystals["enabled"] = crystals["enabled"].lower() == "true"
            merged["crystals"] = crystals
    return merged


def _normalize_mask(mask: Any) -> tuple[dict | None, dict | None]:
    if mask is None:
        return None, None
    if not isinstance(mask, dict):
        return None, err("schema", "Mask must be an object.", "mask")
    normalized = dict(mask)
    for key in ("warp", "scale", "falloff"):
        if key in normalized and normalized[key] is not None:
            coerced = coerce_int(normalized[key])
            if coerced is not None:
                normalized[key] = coerced
    points = normalized.get("points")
    if isinstance(points, list):
        coerced_points = []
        for point in points:
            px, pz = _point_xz(point)
            if px is None or pz is None:
                coerced_points.append(point)
            else:
                coerced_points.append({"x": px, "z": pz})
        normalized["points"] = coerced_points
    return normalized, None


def _find_region(project: dict, region_id: str) -> tuple[int, dict] | None:
    for index, region in enumerate(project["regions"]):
        if region["id"] == region_id:
            return index, region
    return None


def _apply_world_set_meta(project: dict, args: dict) -> dict:
    if not isinstance(args, dict):
        return {"result": None, "error": err("schema", "args must be an object.")}
    world = project["world"]
    if "name" in args:
        if not isinstance(args["name"], str) or not 1 <= len(args["name"].strip()) <= 60:
            return {"result": None, "error": err("schema", "Name must be 1 to 60 characters.", "name")}
        project["name"] = args["name"].strip()
    if "seed" in args:
        args["seed"] = coerce_int(args["seed"])
        if not _is_int(args["seed"]) or not 0 <= args["seed"] <= MAX_SEED:
            return {"result": None, "error": err("schema", "Seed must be an integer from 0 to 2^53-1.", "seed")}
        world["seed"] = args["seed"]
    if "seaLevel" in args:
        args["seaLevel"] = coerce_int(args["seaLevel"])
        if not _is_int(args["seaLevel"]) or not 32 <= args["seaLevel"] <= 120:
            return {"result": None, "error": err("schema", "seaLevel must be an integer from 32 to 120.", "seaLevel")}
        world["seaLevel"] = args["seaLevel"]
    if "blendRadius" in args:
        args["blendRadius"] = coerce_int(args["blendRadius"])
        if not _is_int(args["blendRadius"]) or not 0 <= args["blendRadius"] <= 32:
            return {"result": None, "error": err("schema", "blendRadius must be an integer from 0 to 32.", "blendRadius")}
        project["blendRadius"] = args["blendRadius"]
    if "width" in args:
        args["width"] = coerce_int(args["width"])
    if "depth" in args:
        args["depth"] = coerce_int(args["depth"])
    width = args.get("width", world["width"])
    depth = args.get("depth", world["depth"])
    if "width" in args or "depth" in args:
        if not dimension_ok(width, depth):
            return {
                "result": None,
                "error": err("invalid_dimension", dimension_message(), "world"),
            }
        world["width"] = width
        world["depth"] = depth
    if "defaultTerrain" in args:
        patch = args["defaultTerrain"]
        if not isinstance(patch, dict):
            return {"result": None, "error": err("schema", "defaultTerrain must be an object.", "defaultTerrain")}
        profile = project["defaultTerrain"]
        if "vanillaBiome" in patch:
            profile["vanillaBiome"] = patch["vanillaBiome"]
        if "palette" in patch:
            if not isinstance(patch["palette"], dict):
                return {"result": None, "error": err("schema", "palette must be an object.", "defaultTerrain.palette")}
            profile["palette"] = _merge_palette(profile["palette"], patch["palette"])
        if "terrain" in patch:
            if not isinstance(patch["terrain"], dict):
                return {"result": None, "error": err("schema", "terrain must be an object.", "defaultTerrain.terrain")}
            profile["terrain"] = _merge_terrain(profile["terrain"], patch["terrain"])
        if "features" in patch:
            if not isinstance(patch["features"], dict):
                return {"result": None, "error": err("schema", "features must be an object.", "defaultTerrain.features")}
            profile["features"] = _merge_features(profile["features"], patch["features"])
    if "spawn" in args:
        spawn = args["spawn"]
        if not isinstance(spawn, dict):
            return {"result": None, "error": err("schema", "spawn must be an object.", "spawn")}
        updated = dict(world["spawn"])
        for key in ("x", "y", "z"):
            if key in spawn:
                coerced = coerce_int(spawn[key])
                if coerced is None:
                    return {"result": None, "error": err("schema", f"spawn.{key} must be an integer.", f"spawn.{key}")}
                updated[key] = coerced
        world["spawn"] = updated
    if "border" in args:
        border = args["border"]
        if not isinstance(border, dict):
            return {"result": None, "error": err("schema", "border must be an object.", "border")}
        if "size" in border and border["size"] != max(world["width"], world["depth"]):
            return {
                "result": None,
                "error": err("border_locked", "Border size is locked to the larger world dimension.", "border.size"),
            }
        if "centerX" in border and border["centerX"] != 0 or "centerZ" in border and border["centerZ"] != 0:
            return {"result": None, "error": err("border_locked", "Border center stays at 0, 0.", "border")}
        next_border = make_border(world["width"], world["depth"], world["border"])
        for key in ("warningBlocks", "warningTime", "damagePerBlock", "safeZone"):
            if key in border:
                next_border[key] = border[key]
        world["border"] = next_border
    else:
        world["border"] = make_border(world["width"], world["depth"], world["border"])
    return {"result": {"op": "world.set_meta"}, "error": None}


def _new_region(project: dict, args: dict) -> tuple[dict | None, dict | None]:
    if not isinstance(args, dict):
        return None, err("schema", "args must be an object.")
    for key in ("name", "color", "shape"):
        if key not in args:
            return None, err("schema", f"region.create requires {key}.", key)
    base = deepcopy(project["defaultTerrain"])
    region_id = args.get("id") or new_id()
    if not is_uuid(region_id):
        return None, err("schema", "Region id must be a UUID.", "id")
    region = {
        "id": region_id,
        "name": args["name"].strip() if isinstance(args["name"], str) else args["name"],
        "color": args["color"],
        "vanillaBiome": args.get("vanillaBiome", base["vanillaBiome"]),
        "shape": coerce_shape(args["shape"]),
        "brief": deepcopy(args.get("brief") or {"text": "", "assetIds": []}),
        "palette": deepcopy(base["palette"]),
        "terrain": deepcopy(base["terrain"]),
        "features": deepcopy(base["features"]),
    }
    if "palette" in args:
        if not isinstance(args["palette"], dict):
            return None, err("schema", "palette must be an object.", "palette")
        region["palette"] = _merge_palette(region["palette"], args["palette"])
    if "terrain" in args:
        if not isinstance(args["terrain"], dict):
            return None, err("schema", "terrain must be an object.", "terrain")
        region["terrain"] = _merge_terrain(region["terrain"], args["terrain"])
    if "features" in args:
        if not isinstance(args["features"], dict):
            return None, err("schema", "features must be an object.", "features")
        region["features"] = _merge_features(region["features"], args["features"])
    if "mask" in args:
        normalized, error = _normalize_mask(args["mask"])
        if error:
            return None, error
        if normalized is None:
            region.pop("mask", None)
        else:
            region["mask"] = normalized
    if region["vanillaBiome"] not in VANILLA_BIOMES:
        return None, err("schema", "Unsupported vanilla biome.", "vanillaBiome")
    if not isinstance(region["color"], str) or not COLOR_RE.match(region["color"]):
        return None, err("schema", "Region color must be #RRGGBB.", "color")
    return region, None


def _apply_region_create(project: dict, args: dict) -> dict:
    region, error = _new_region(project, args)
    if error:
        return {"result": None, "error": error}
    shape_errors = validate_shape(region["shape"], "shape")
    if shape_errors:
        return {"result": None, "error": shape_errors[0]}
    project["regions"].append(region)
    return {"result": {"op": "region.create", "regionId": region["id"]}, "error": None}


def _apply_region_update(project: dict, args: dict) -> dict:
    if not isinstance(args, dict) or "id" not in args:
        return {"result": None, "error": err("schema", "region.update requires id.", "id")}
    found = _find_region(project, args["id"])
    if not found:
        return {"result": None, "error": err("unknown_region", "Region not found.", "id")}
    index, region = found
    if "name" in args:
        region["name"] = args["name"].strip() if isinstance(args["name"], str) else args["name"]
    if "color" in args:
        region["color"] = args["color"]
    if "vanillaBiome" in args:
        region["vanillaBiome"] = args["vanillaBiome"]
    if "shape" in args:
        region["shape"] = coerce_shape(args["shape"])
    if "brief" in args:
        if not isinstance(args["brief"], dict):
            return {"result": None, "error": err("schema", "brief must be an object.", "brief")}
        brief = deepcopy(region.get("brief") or {"text": "", "assetIds": []})
        if "text" in args["brief"]:
            brief["text"] = args["brief"]["text"]
        if "assetIds" in args["brief"]:
            brief["assetIds"] = list(args["brief"]["assetIds"])
        region["brief"] = brief
    if "palette" in args:
        if not isinstance(args["palette"], dict):
            return {"result": None, "error": err("schema", "palette must be an object.", "palette")}
        region["palette"] = _merge_palette(region["palette"], args["palette"])
    if "terrain" in args:
        if not isinstance(args["terrain"], dict):
            return {"result": None, "error": err("schema", "terrain must be an object.", "terrain")}
        region["terrain"] = _merge_terrain(region["terrain"], args["terrain"])
    if "features" in args:
        if not isinstance(args["features"], dict):
            return {"result": None, "error": err("schema", "features must be an object.", "features")}
        region["features"] = _merge_features(region["features"], args["features"])
    if "mask" in args:
        normalized, error = _normalize_mask(args["mask"])
        if error:
            return {"result": None, "error": error}
        if normalized is None:
            region.pop("mask", None)
        else:
            region["mask"] = normalized
    project["regions"][index] = region
    return {"result": {"op": "region.update", "regionId": region["id"]}, "error": None}


def _apply_region_move(project: dict, args: dict) -> dict:
    if not isinstance(args, dict) or not all(key in args for key in ("id", "x", "z")):
        return {"result": None, "error": err("schema", "region.move requires id, x, and z.")}
    moved_x = coerce_int(args["x"])
    moved_z = coerce_int(args["z"])
    if moved_x is None or moved_z is None:
        return {"result": None, "error": err("schema", "x and z must be integers.", "x")}
    found = _find_region(project, args["id"])
    if not found:
        return {"result": None, "error": err("unknown_region", "Region not found.", "id")}
    index, region = found
    old_x = int(region["shape"]["x"])
    old_z = int(region["shape"]["z"])
    region["shape"] = dict(region["shape"])
    region["shape"]["x"] = moved_x
    region["shape"]["z"] = moved_z
    mask = region.get("mask")
    if isinstance(mask, dict) and isinstance(mask.get("points"), list):
        shifted = []
        for point in mask["points"]:
            px, pz = _point_xz(point)
            if px is None or pz is None:
                shifted.append(point)
                continue
            moved = {"x": px + (moved_x - old_x), "z": pz + (moved_z - old_z)}
            shifted.append(moved)
        mask = dict(mask)
        mask["points"] = shifted
        region["mask"] = mask
    project["regions"][index] = region
    return {"result": {"op": "region.move", "regionId": region["id"]}, "error": None}


def _apply_region_delete(project: dict, args: dict) -> dict:
    if not isinstance(args, dict) or "id" not in args:
        return {"result": None, "error": err("schema", "region.delete requires id.", "id")}
    found = _find_region(project, args["id"])
    if not found:
        return {"result": None, "error": err("unknown_region", "Region not found.", "id")}
    index, region = found
    del project["regions"][index]
    return {"result": {"op": "region.delete", "regionId": region["id"]}, "error": None}


def _apply_asset_delete(project: dict, args: dict) -> dict:
    if not isinstance(args, dict) or "id" not in args:
        return {"result": None, "error": err("schema", "asset.delete requires id.", "id")}
    assets = project.get("assets") or []
    kept = [asset for asset in assets if asset.get("id") != args["id"]]
    if len(kept) == len(assets):
        return {"result": None, "error": err("unknown_asset", "Reference image not found.", "id")}
    removed = next(asset for asset in assets if asset.get("id") == args["id"])
    project["assets"] = kept
    for region in project["regions"]:
        brief = region.get("brief") or {}
        brief["assetIds"] = [asset_id for asset_id in brief.get("assetIds", []) if asset_id != args["id"]]
        region["brief"] = brief
    return {"result": {"op": "asset.delete", "assetId": args["id"], "removed": removed}, "error": None}


_HANDLERS = {
    "world.set_meta": _apply_world_set_meta,
    "region.create": _apply_region_create,
    "region.update": _apply_region_update,
    "region.move": _apply_region_move,
    "region.delete": _apply_region_delete,
    "asset.delete": _apply_asset_delete,
}


def apply_operations(project: dict, operations: list, registry: BlockRegistry) -> dict:
    if not isinstance(operations, list) or not operations:
        return {"ok": False, "errors": [err("schema", "Provide at least one operation.", "operations")]}
    if len(operations) > 50:
        return {"ok": False, "errors": [err("schema", "At most 50 operations can be applied at once.", "operations")]}
    working = deepcopy(project)
    results = []
    removed_assets = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or operation.get("op") not in _HANDLERS:
            return {"ok": False, "errors": [err("schema", "Unknown operation.", "op", index)]}
        outcome = _HANDLERS[operation["op"]](working, operation.get("args") or {})
        if outcome["error"]:
            outcome["error"]["index"] = index
            return {"ok": False, "errors": [outcome["error"]]}
        results.append(outcome["result"])
        if outcome["result"].get("removed"):
            removed_assets.append(outcome["result"].pop("removed"))
        errors = validate_project(working, registry)
        if errors:
            errors[0]["index"] = index
            return {"ok": False, "errors": [errors[0]]}
    working["updatedAt"] = now_iso()
    return {"ok": True, "project": working, "results": results, "removedAssets": removed_assets}
