"""Read a Minecraft Java 1.21.4 world folder without using the writer."""

from __future__ import annotations

import gzip
import io
import math
import zlib
from pathlib import Path

from nbtlib import File

from mcmap.blocks import load_registry
from mcmap.model import DATA_VERSION

AIR = "minecraft:air"
CAVE_AIR = "minecraft:cave_air"
FLUIDS = {"minecraft:water", "minecraft:lava"}
Y_MIN = -64


def _signed_to_unsigned(value: int) -> int:
    if value < 0:
        return value + (1 << 64)
    return value


def unpack_longs(values, bits: int, count: int) -> list[int]:
    per = 64 // bits
    mask = (1 << bits) - 1
    longs = [_signed_to_unsigned(int(item)) for item in values]
    unpacked = []
    for index in range(count):
        long_index = index // per
        if long_index >= len(longs):
            raise ValueError("packed long array is shorter than the block volume")
        shift = (index % per) * bits
        unpacked.append((longs[long_index] >> shift) & mask)
    return unpacked


def _is_motion(name: str, registry) -> bool:
    if name in (AIR, CAVE_AIR):
        return False
    if registry.is_solid(name):
        return True
    return name in FLUIDS


def _properties(entry) -> dict[str, str]:
    if "Properties" not in entry:
        return {}
    return {str(key): str(value) for key, value in entry["Properties"].items()}


def _decode_states(container, count: int, minimum_bits: int) -> tuple[list[dict], list[int]]:
    palette = []
    for entry in container["palette"]:
        palette.append({"name": str(entry["Name"]), "properties": _properties(entry)})
    if len(palette) <= 1:
        return palette, [0] * count
    if "data" not in container:
        raise ValueError("palette data is missing")
    bits = max(minimum_bits, math.ceil(math.log2(len(palette))))
    indices = unpack_longs(container["data"].tolist(), bits, count)
    if any(index >= len(palette) for index in indices):
        raise ValueError("palette index is out of range")
    return palette, indices


def _check_properties(palette: list[dict], registry, errors: list[str]) -> None:
    for entry in palette:
        expected = registry.properties(entry["name"])
        if entry["properties"] != expected:
            errors.append(f"properties for {entry['name']} are {entry['properties']}, expected {expected}")


def _iter_region_chunks(path: Path):
    """Yield one parsed chunk at a time so a large region is not held all at once."""
    data = path.read_bytes()
    if len(data) < 8192:
        raise ValueError(f"{path.name} header is truncated")
    for index in range(1024):
        location = int.from_bytes(data[index * 4 : index * 4 + 4], "big")
        if location == 0:
            continue
        offset = (location >> 8) * 4096
        sectors = location & 0xFF
        blob = data[offset : offset + sectors * 4096]
        if len(blob) < 5:
            raise ValueError(f"{path.name} chunk {index} is truncated")
        length = int.from_bytes(blob[0:4], "big")
        compression = blob[4]
        if compression != 2:
            raise ValueError(f"{path.name} chunk {index} compression is {compression}")
        raw = zlib.decompress(blob[5 : 4 + length])
        yield File.parse(io.BytesIO(raw))


def _read_region_chunks(path: Path) -> list:
    return list(_iter_region_chunks(path))


def _column_records(chunk, registry, errors: list[str]) -> dict[tuple[int, int], dict]:
    cx = int(chunk["xPos"])
    cz = int(chunk["zPos"])
    if int(chunk["DataVersion"]) != DATA_VERSION:
        errors.append(f"chunk {cx},{cz} dataVersion is {int(chunk['DataVersion'])}")
    if int(chunk["yPos"]) != -4:
        errors.append(f"chunk {cx},{cz} yPos is {int(chunk['yPos'])}")
    columns: dict[tuple[int, int], dict] = {
        (local_x, local_z): {"surface": None, "motion": None, "bedrock": None, "zero": None}
        for local_z in range(16)
        for local_x in range(16)
    }
    for section in chunk["sections"]:
        section_y = int(section["Y"])
        palette, indices = _decode_states(section["block_states"], 4096, 4)
        _check_properties(palette, registry, errors)
        for local_y in range(16):
            for local_z in range(16):
                for local_x in range(16):
                    name = palette[indices[local_x + local_z * 16 + local_y * 256]]["name"]
                    world_y = section_y * 16 + local_y
                    record = columns[(local_x, local_z)]
                    if name not in (AIR, CAVE_AIR) and (record["surface"] is None or world_y > record["surface"][0]):
                        record["surface"] = (world_y, name)
                    if _is_motion(name, registry) and (record["motion"] is None or world_y > record["motion"]):
                        record["motion"] = world_y
                    if world_y == Y_MIN:
                        record["bedrock"] = name
                    elif world_y == 0 and name not in (AIR, CAVE_AIR):
                        record["zero"] = name
    heightmaps = chunk["Heightmaps"]
    motion_map = unpack_longs(heightmaps["MOTION_BLOCKING"].tolist(), 9, 256)
    surface_map = unpack_longs(heightmaps["WORLD_SURFACE"].tolist(), 9, 256)
    if len(heightmaps["MOTION_BLOCKING"]) != 37 or len(heightmaps["WORLD_SURFACE"]) != 37:
        errors.append(f"chunk {cx},{cz} heightmaps are not 37 longs")
    for local_z in range(16):
        for local_x in range(16):
            slot = local_x + local_z * 16
            record = columns[(local_x, local_z)]
            expected_surface = 0 if record["surface"] is None else record["surface"][0] - Y_MIN + 1
            expected_motion = 0 if record["motion"] is None else record["motion"] - Y_MIN + 1
            if surface_map[slot] != expected_surface or motion_map[slot] != expected_motion:
                errors.append(
                    f"heightmap mismatch at {cx * 16 + local_x},{cz * 16 + local_z}: "
                    f"surface {surface_map[slot]}!={expected_surface}, motion {motion_map[slot]}!={expected_motion}"
                )
    return {(cx * 16 + local_x, cz * 16 + local_z): record for (local_x, local_z), record in columns.items()}


def validate_world(world_dir: str) -> dict:
    errors: list[str] = []
    result = {
        "ok": False,
        "dataVersion": None,
        "levelName": None,
        "spawn": None,
        "borderSize": None,
        "borderCenterX": None,
        "borderCenterZ": None,
        "chunkCount": 0,
        "samples": [],
        "errors": errors,
    }
    root = Path(world_dir)
    level_path = root / "level.dat"
    if not level_path.is_file():
        errors.append("missing level.dat")
        return result
    if (root / "session.lock").exists():
        errors.append("session.lock should not be written")
    try:
        parsed = File.parse(io.BytesIO(gzip.decompress(level_path.read_bytes())))
        result["dataVersion"] = int(parsed["DataVersion"])
        data = parsed["Data"]
        result["levelName"] = str(data["LevelName"])
        result["spawn"] = {"x": int(data["SpawnX"]), "y": int(data["SpawnY"]), "z": int(data["SpawnZ"])}
        result["borderSize"] = float(data["BorderSize"])
        result["borderCenterX"] = float(data["BorderCenterX"])
        result["borderCenterZ"] = float(data["BorderCenterZ"])
    except Exception as exc:  # noqa: BLE001 - validation reports the read failure
        errors.append(f"level.dat: {exc}")
        result["ok"] = False
        return result
    if result["dataVersion"] != DATA_VERSION:
        errors.append(f"dataVersion is {result['dataVersion']}")
    half = float(result["borderSize"]) / 2.0
    registry = load_registry()
    samples = []
    chunk_count = 0
    # Small worlds keep every column in the report. Larger worlds still check every
    # chunk and heightmap, and keep spawn, corners, and a stride of columns.
    keep_all = half <= 256
    stride = 1 if keep_all else 64
    spawn = result["spawn"] or {"x": 0, "y": 0, "z": 0}
    region_dir = root / "region"
    paths = sorted(region_dir.glob("*.mca")) if region_dir.is_dir() else []
    if not paths:
        errors.append("no region files")
    for path in paths:
        try:
            for chunk in _iter_region_chunks(path):
                chunk_count += 1
                try:
                    columns = _column_records(chunk, registry, errors)
                except Exception as exc:  # noqa: BLE001 - report the chunk and keep reading
                    errors.append(f"chunk decode: {exc}")
                    continue
                for (x, z), record in columns.items():
                    if x < -half or x >= half or z < -half or z >= half:
                        continue
                    if not keep_all:
                        near_spawn = abs(x - int(spawn["x"])) <= 2 and abs(z - int(spawn["z"])) <= 2
                        on_grid = x % stride == 0 and z % stride == 0
                        corner = x in {int(-half), int(half) - 1} and z in {int(-half), int(half) - 1}
                        if not (near_spawn or on_grid or corner):
                            continue
                    if record["bedrock"] is not None:
                        samples.append({"x": x, "y": Y_MIN, "z": z, "name": record["bedrock"]})
                    if record["zero"] is not None:
                        samples.append({"x": x, "y": 0, "z": z, "name": record["zero"]})
                    if record["surface"] is not None:
                        sy, name = record["surface"]
                        if sy not in (Y_MIN, 0):
                            samples.append({"x": x, "y": sy, "z": z, "name": name})
        except Exception as exc:  # noqa: BLE001 - one bad region should not hide the rest
            errors.append(f"{path.name}: {exc}")
            continue
    result["chunkCount"] = chunk_count
    if chunk_count <= 0:
        errors.append("no chunks")
    samples.sort(key=lambda item: (item["x"], item["z"], item["y"], item["name"]))
    result["samples"] = samples
    result["ok"] = not errors
    return result
