import ast
import json
import zipfile
from copy import deepcopy
from pathlib import Path

from mcmap.export.reader import validate_world
from mcmap.export.service import export_world
from mcmap.generate.service import sample_column
from mcmap.model import new_project


def _flat() -> dict:
    project = new_project("Flat Test", 32, 32, 3, 0, 0)
    terrain = project["defaultTerrain"]
    terrain["terrain"]["baseHeight"] = 68
    terrain["terrain"]["amplitude"] = 0
    terrain["terrain"]["roughness"] = 0
    terrain["terrain"]["water"] = False
    terrain["features"]["trees"] = {"kind": "none", "density": 0}
    terrain["features"]["vegetation"] = "none"
    terrain["features"]["ores"] = False
    terrain["features"]["caves"] = False
    return project


def test_export_validate_roundtrip(tmp_path: Path):
    project = _flat()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    exported = export_world(project, str(project_dir), str(tmp_path / "dest"))
    assert exported["dataVersion"] == 4189
    assert exported["ok"] is True
    world_dir = Path(exported["worldDir"])
    zip_path = Path(exported["zipPath"])
    assert world_dir.is_absolute() and zip_path.is_absolute()
    assert world_dir.name == "flat-test"
    assert (world_dir / "level.dat").is_file()
    assert not (world_dir / "session.lock").exists()
    assert list((world_dir / "region").glob("*.mca"))
    validation = exported["validation"]
    assert validation["ok"] is True, validation["errors"]
    assert validation["dataVersion"] == 4189
    assert validation["levelName"] == "Flat Test"
    assert validation["borderSize"] == 32
    assert validation["borderCenterX"] == 0
    assert validation["borderCenterZ"] == 0
    assert validation["spawn"] == exported["spawn"]
    assert validation["chunkCount"] > 0
    direct = validate_world(str(world_dir))
    assert direct["ok"] is True, direct["errors"]
    assert direct["chunkCount"] == validation["chunkCount"]
    column = sample_column(project, str(project_dir), 12, 12)
    names = {(sample["x"], sample["y"], sample["z"]): sample["name"] for sample in validation["samples"]}
    top = column["blocks"][-1]
    assert names[(12, top["y"], 12)] == top["id"]
    assert names[(12, -64, 12)] == "minecraft:bedrock"
    assert names[(12, 0, 12)] == "minecraft:stone"
    stored = json.loads((project_dir / "cache" / "last_export.json").read_text(encoding="utf-8"))
    assert stored["worldDir"] == str(world_dir)
    assert stored["zipPath"] == str(zip_path)
    assert stored["dataVersion"] == 4189
    assert stored["validation"]["ok"] is True
    with zipfile.ZipFile(zip_path) as archive:
        names_in_zip = archive.namelist()
    assert names_in_zip
    assert all(name.startswith("flat-test/") for name in names_in_zip)
    assert any(name.endswith("level.dat") for name in names_in_zip)
    assert not any(name.endswith("session.lock") for name in names_in_zip)
    tops = {name.split("/", 1)[0] for name in names_in_zip}
    assert tops == {"flat-test"}


def test_reader_does_not_import_writer():
    source = Path(__file__).resolve().parents[1].joinpath("server/mcmap/export/reader.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported = [node.module or "", *[alias.name for alias in node.names]]
        else:
            continue
        assert all("writer" not in name for name in imported)


def _unpack_longs(values, bits: int, count: int) -> list[int]:
    mask = (1 << bits) - 1
    per = 64 // bits
    longs = []
    for item in values:
        item = int(item)
        if item < 0:
            item += 1 << 64
        longs.append(item)
    unpacked = []
    for index in range(count):
        long_index = index // per
        shift = (index % per) * bits
        unpacked.append((longs[long_index] >> shift) & mask)
    return unpacked


def _read_chunk_nbt(world_dir: Path, x: int, z: int):
    import io
    import zlib

    from nbtlib import File

    cx = x >> 4
    cz = z >> 4
    path = world_dir / "region" / f"r.{cx >> 5}.{cz >> 5}.mca"
    data = path.read_bytes()
    local = (cx & 31) + (cz & 31) * 32
    entry = int.from_bytes(data[local * 4 : local * 4 + 4], "big")
    offset = (entry >> 8) * 4096
    length = int.from_bytes(data[offset : offset + 4], "big")
    assert data[offset + 4] == 2
    raw = zlib.decompress(data[offset + 5 : offset + 4 + length])
    return File.parse(io.BytesIO(raw))


def _section_indices(states) -> tuple[list[str], list[int]]:
    palette = [str(item["Name"]) for item in states["palette"]]
    if len(palette) == 1 or "data" not in states:
        return palette, [0] * 4096
    bits = max(4, (len(palette) - 1).bit_length())
    return palette, _unpack_longs(states["data"], bits, 4096)


def _stored_heightmaps(chunk) -> tuple[list[int], list[int]]:
    return (
        _unpack_longs(chunk["Heightmaps"]["WORLD_SURFACE"], 9, 256),
        _unpack_longs(chunk["Heightmaps"]["MOTION_BLOCKING"], 9, 256),
    )


def _column_blocks(chunk, x: int, z: int) -> dict[int, str]:
    names: dict[int, str] = {}
    local_x = x & 15
    local_z = z & 15
    for section in chunk["sections"]:
        palette, indices = _section_indices(section["block_states"])
        base_y = int(section["Y"]) * 16
        for index, palette_index in enumerate(indices):
            if (index & 15) != local_x or ((index >> 4) & 15) != local_z:
                continue
            names[base_y + (index >> 8)] = palette[palette_index]
    return names


def _first_available(column: dict[int, str], predicate) -> int:
    """Minecraft stores the Y above the highest matching block, offset from minY -64."""
    matches = [y for y, name in column.items() if predicate(name)]
    if not matches:
        return 0
    return (max(matches) + 1) - (-64)


def test_heightmaps_use_minecraft_first_available_block(tmp_path: Path):
    """Decode chunk NBT directly. Do not ask the repository reader what the values should be."""
    from mcmap.blocks import load_registry

    registry = load_registry()
    air = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
    fluids = {"minecraft:water", "minecraft:lava"}

    def blocks_motion(name: str) -> bool:
        if name in air:
            return False
        return bool(registry.is_solid(name) or name in fluids)

    def check(project: dict, directory: Path, x: int, z: int) -> tuple[int, int, dict[int, str]]:
        exported = export_world(project, str(directory), str(directory / "dest"))
        assert exported["validation"]["ok"] is True, exported["validation"]["errors"]
        chunk = _read_chunk_nbt(Path(exported["worldDir"]), x, z)
        surface_map, motion_map = _stored_heightmaps(chunk)
        column = _column_blocks(chunk, x, z)
        slot = (x & 15) + (z & 15) * 16
        assert surface_map[slot] == _first_available(column, lambda name: name not in air)
        assert motion_map[slot] == _first_available(column, blocks_motion)
        return surface_map[slot], motion_map[slot], column

    planted = _flat()
    planted["defaultTerrain"]["features"]["vegetation"] = "temperate"
    planted["defaultTerrain"]["features"]["trees"] = {"kind": "oak", "density": 1}
    planted_dir = tmp_path / "planted"
    planted_dir.mkdir()
    export_world(planted, str(planted_dir), str(planted_dir / "dest"))
    grass = leaves = None
    for z in range(-16, 16):
        for x in range(-16, 16):
            top = sample_column(planted, str(planted_dir), x, z)["blocks"][-1]["id"]
            if grass is None and top == "minecraft:short_grass":
                grass = (x, z)
            if leaves is None and top == "minecraft:oak_leaves":
                leaves = (x, z)
            if grass and leaves:
                break
        if grass and leaves:
            break
    assert grass is not None and leaves is not None
    surface, motion, column = check(planted, planted_dir, *grass)
    assert column[max(y for y, name in column.items() if name == "minecraft:short_grass")] == "minecraft:short_grass"
    assert surface == motion + 1
    surface, motion, column = check(planted, planted_dir, *leaves)
    assert any(name == "minecraft:oak_leaves" for name in column.values())
    assert surface == motion

    wet = _flat()
    wet["defaultTerrain"]["terrain"]["baseHeight"] = 40
    wet["defaultTerrain"]["terrain"]["water"] = True
    wet_dir = tmp_path / "wet"
    wet_dir.mkdir()
    surface, motion, column = check(wet, wet_dir, 12, 12)
    assert column[62] == "minecraft:water"
    assert surface == motion == (62 + 1) - (-64)


def test_export_regenerates_when_missing(tmp_path: Path):
    project = _flat()
    other = deepcopy(project)
    other["world"]["seed"] = 8
    project_dir = tmp_path / "again"
    project_dir.mkdir()
    first = export_world(project, str(project_dir), str(tmp_path / "out"))
    assert first["validation"]["chunkCount"] > 0
    second = export_world(other, str(project_dir), str(tmp_path / "out"))
    assert second["validation"]["ok"] is True, second["validation"]["errors"]
