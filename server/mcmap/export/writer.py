"""Write a Minecraft Java 1.21.4 world folder. The reader must not import this module."""

from __future__ import annotations

import gzip
import io
import math
import re
import struct
import time
import zlib
from collections import defaultdict
from pathlib import Path

import numpy as np
from nbtlib import Byte, Compound, Double, File, Float, Int, List, Long, LongArray, String

from mcmap.blocks import load_registry
from mcmap.model import DATA_VERSION, MINECRAFT_VERSION

Y_MIN = -64
SECTION_MIN = -4
SECTION_MAX = 19
WORLD_HEIGHT = 384
AIR = "minecraft:air"
CAVE_AIR = "minecraft:cave_air"
FLUIDS = {"minecraft:water", "minecraft:lava"}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "world"


def _signed64(value: int) -> int:
    value &= (1 << 64) - 1
    if value >= (1 << 63):
        return value - (1 << 64)
    return value


def pack_longs(indices, bits: int) -> list[int]:
    per = 64 // bits
    mask = (1 << bits) - 1
    packed = []
    acc = 0
    count = 0
    for index in indices:
        acc |= (int(index) & mask) << (count * bits)
        count += 1
        if count == per:
            packed.append(_signed64(acc))
            acc = 0
            count = 0
    if count:
        packed.append(_signed64(acc))
    return packed


def _palette_entry(registry, block_id: str) -> Compound:
    entry = Compound({"Name": String(block_id)})
    properties = registry.properties(block_id)
    if properties:
        entry["Properties"] = Compound({key: String(value) for key, value in properties.items()})
    return entry


def _block_states(registry, block_ids: list[str], section: np.ndarray) -> Compound:
    palette_ids: list[int] = []
    mapping: dict[int, int] = {}
    indices = [0] * 4096
    cursor = 0
    for local_y in range(16):
        for local_z in range(16):
            for local_x in range(16):
                block_index = int(section[local_x, local_z, local_y])
                palette_index = mapping.get(block_index)
                if palette_index is None:
                    palette_index = len(palette_ids)
                    mapping[block_index] = palette_index
                    palette_ids.append(block_index)
                indices[cursor] = palette_index
                cursor += 1
    tag = Compound({"palette": List[Compound]([_palette_entry(registry, block_ids[i]) for i in palette_ids])})
    if len(palette_ids) > 1:
        bits = max(4, math.ceil(math.log2(len(palette_ids))))
        tag["data"] = LongArray(pack_longs(indices, bits))
    return tag


def _biomes(local_biome: np.ndarray) -> Compound:
    palette: list[str] = []
    mapping: dict[str, int] = {}
    indices = [0] * 64
    for index in range(64):
        bx = index & 3
        bz = (index >> 2) & 3
        name = str(local_biome[bx * 4 + 2, bz * 4 + 2])
        palette_index = mapping.get(name)
        if palette_index is None:
            palette_index = len(palette)
            mapping[name] = palette_index
            palette.append(name)
        indices[index] = palette_index
    tag = Compound({"palette": List[String](palette)})
    if len(palette) > 1:
        bits = math.ceil(math.log2(len(palette)))
        tag["data"] = LongArray(pack_longs(indices, bits))
    return tag


def _highest(column: np.ndarray, predicate) -> int:
    """Return Minecraft's stored heightmap value for one column.

    The chunk array starts at minY, so index ``i`` is world Y ``minY + i``.
    Minecraft stores the first available block above the highest match:
    ``(highestY + 1) - minY``, which is ``i + 1``. An empty column stores 0.
    """
    for index in range(len(column) - 1, -1, -1):
        if predicate(int(column[index])):
            return index + 1
    return 0


def _chunk_bytes(registry, world: dict, cx: int, cz: int, motion_ids: set[int], air_i: int, cave_i: int) -> bytes:
    block_ids = world["block_ids"]
    biome_ids = world["biome_ids"]
    blocks = world["blocks"]
    biomes = world["biomes"]
    min_x = int(world["min_x"])
    min_z = int(world["min_z"])
    max_x = min_x + blocks.shape[0]
    max_z = min_z + blocks.shape[1]
    stored = blocks.shape[2]
    local = np.full((16, 16, WORLD_HEIGHT), air_i, dtype=np.uint16)
    local_biome = np.full((16, 16), world["default_biome"], dtype=object)
    x0 = cx * 16
    z0 = cz * 16
    for local_x in range(16):
        wx = x0 + local_x
        if wx < min_x or wx >= max_x:
            continue
        ix = wx - min_x
        for local_z in range(16):
            wz = z0 + local_z
            if wz < min_z or wz >= max_z:
                continue
            iz = wz - min_z
            local[local_x, local_z, :stored] = blocks[ix, iz]
            local_biome[local_x, local_z] = biome_ids[int(biomes[ix, iz])]
    motion = [0] * 256
    surface = [0] * 256

    def is_motion(block_index: int) -> bool:
        return block_index in motion_ids

    def is_world_surface(block_index: int) -> bool:
        return block_index != air_i and block_index != cave_i

    for local_z in range(16):
        for local_x in range(16):
            column = local[local_x, local_z]
            slot = local_x + local_z * 16
            motion[slot] = _highest(column, is_motion)
            surface[slot] = _highest(column, is_world_surface)
    if len(pack_longs(motion, 9)) != 37 or len(pack_longs(surface, 9)) != 37:
        raise RuntimeError("heightmap packing did not produce 37 longs")
    sections = []
    for section_y in range(SECTION_MIN, SECTION_MAX + 1):
        offset = (section_y - SECTION_MIN) * 16
        sections.append(
            Compound(
                {
                    "Y": Byte(section_y),
                    "block_states": _block_states(registry, block_ids, local[:, :, offset : offset + 16]),
                    "biomes": _biomes(local_biome),
                }
            )
        )
    chunk = File(
        {
            "DataVersion": Int(DATA_VERSION),
            "xPos": Int(int(cx)),
            "zPos": Int(int(cz)),
            "yPos": Int(SECTION_MIN),
            "Status": String("minecraft:full"),
            "LastUpdate": Long(0),
            "InhabitedTime": Long(0),
            "isLightOn": Byte(0),
            "sections": List[Compound](sections),
            "block_entities": List[Compound]([]),
            "Heightmaps": Compound(
                {
                    "MOTION_BLOCKING": LongArray(pack_longs(motion, 9)),
                    "WORLD_SURFACE": LongArray(pack_longs(surface, 9)),
                }
            ),
        },
        root_name="",
    )
    buffer = io.BytesIO()
    chunk.write(buffer)
    return buffer.getvalue()


def _write_region(path: Path, compressed_by_local: dict[int, bytes]) -> None:
    offset = 2
    locations = [0] * 1024
    payload = bytearray()
    for local in range(1024):
        compressed = compressed_by_local.get(local)
        if compressed is None:
            continue
        length = len(compressed) + 1
        record = struct.pack(">I", length) + bytes([2]) + compressed
        sectors = (len(record) + 4095) // 4096
        if sectors > 255:
            raise RuntimeError("chunk exceeds the region sector limit")
        locations[local] = ((offset & 0xFFFFFF) << 8) | sectors
        payload.extend(record)
        padding = sectors * 4096 - len(record)
        if padding:
            payload.extend(b"\x00" * padding)
        offset += sectors
    header = bytearray()
    for location in locations:
        header.extend(struct.pack(">I", location))
    header.extend(b"\x00" * 4096)
    path.write_bytes(bytes(header) + bytes(payload))


def _dimension(dimension_id: str) -> Compound:
    return Compound(
        {
            "type": String(dimension_id),
            "generator": Compound(
                {
                    "type": String("minecraft:flat"),
                    "settings": Compound(
                        {
                            "biome": String("minecraft:plains"),
                            "features": Byte(0),
                            "lakes": Byte(0),
                            "layers": List[Compound]([]),
                        }
                    ),
                }
            ),
        }
    )


def _level_dat(project: dict, spawn: dict, path: Path) -> None:
    world = project["world"]
    border = world["border"]
    seed = int(world["seed"])
    size = float(border["size"])
    root = File(
        {
            "DataVersion": Int(DATA_VERSION),
            "Data": Compound(
                {
                    "version": Int(19133),
                    "Version": Compound(
                        {
                            "Id": Int(DATA_VERSION),
                            "Name": String(MINECRAFT_VERSION),
                            "Series": String("main"),
                            "Snapshot": Byte(0),
                        }
                    ),
                    "LevelName": String(str(project["name"])),
                    "GameType": Int(0),
                    "Difficulty": Byte(2),
                    "hardcore": Byte(0),
                    "initialized": Byte(1),
                    "allowCommands": Byte(0),
                    "SpawnX": Int(int(spawn["x"])),
                    "SpawnY": Int(int(spawn["y"])),
                    "SpawnZ": Int(int(spawn["z"])),
                    "SpawnAngle": Float(0.0),
                    "Time": Long(0),
                    "DayTime": Long(1000),
                    "LastPlayed": Long(int(time.time() * 1000)),
                    "BorderCenterX": Double(0.0),
                    "BorderCenterZ": Double(0.0),
                    "BorderSize": Double(size),
                    "BorderSizeLerpTarget": Double(size),
                    "BorderSizeLerpTime": Long(0),
                    "BorderWarningBlocks": Double(float(border["warningBlocks"])),
                    "BorderWarningTime": Double(float(border["warningTime"])),
                    "BorderSafeZone": Double(float(border["safeZone"])),
                    "BorderDamagePerBlock": Double(float(border["damagePerBlock"])),
                    "GameRules": Compound(
                        {
                            "doMobSpawning": String("true"),
                            "doDaylightCycle": String("true"),
                            "keepInventory": String("false"),
                            "mobGriefing": String("true"),
                        }
                    ),
                    "DataPacks": Compound(
                        {
                            "Enabled": List[String](["vanilla"]),
                            "Disabled": List[String]([]),
                        }
                    ),
                    "RandomSeed": Long(seed),
                    "generatorName": String("flat"),
                    "generatorVersion": Int(1),
                    "clearWeatherTime": Int(0),
                    "rainTime": Int(0),
                    "thunderTime": Int(0),
                    "raining": Byte(0),
                    "thundering": Byte(0),
                    "WorldGenSettings": Compound(
                        {
                            "bonus_chest": Byte(0),
                            "generate_features": Byte(0),
                            "seed": Long(seed),
                            "dimensions": Compound(
                                {
                                    "minecraft:overworld": _dimension("minecraft:overworld"),
                                    "minecraft:the_nether": _dimension("minecraft:the_nether"),
                                    "minecraft:the_end": _dimension("minecraft:the_end"),
                                }
                            ),
                        }
                    ),
                }
            ),
        },
        root_name="",
    )
    buffer = io.BytesIO()
    root.write(buffer)
    path.write_bytes(gzip.compress(buffer.getvalue()))


def write_world(project: dict, world: dict, world_dir: Path) -> None:
    registry = load_registry()
    block_ids = world["block_ids"]
    index = {block_id: i for i, block_id in enumerate(block_ids)}
    air_i = index[AIR]
    cave_i = index[CAVE_AIR]
    motion_ids = set()
    for block_index, block_id in enumerate(block_ids):
        if block_id in (AIR, CAVE_AIR):
            continue
        if registry.is_solid(block_id) or block_id in FLUIDS:
            motion_ids.add(block_index)
    enriched = dict(world)
    enriched["default_biome"] = project["defaultTerrain"]["vanillaBiome"]
    min_x = int(world["min_x"])
    min_z = int(world["min_z"])
    max_x = min_x + world["blocks"].shape[0]
    max_z = min_z + world["blocks"].shape[1]
    cx0 = min_x >> 4
    cx1 = (max_x - 1) >> 4
    cz0 = min_z >> 4
    cz1 = (max_z - 1) >> 4
    grouped: dict[tuple[int, int], dict[int, bytes]] = defaultdict(dict)
    for cz in range(cz0, cz1 + 1):
        for cx in range(cx0, cx1 + 1):
            raw = _chunk_bytes(registry, enriched, cx, cz, motion_ids, air_i, cave_i)
            local = (cx & 31) + (cz & 31) * 32
            grouped[(cx >> 5, cz >> 5)][local] = zlib.compress(raw)
    region_dir = world_dir / "region"
    region_dir.mkdir(parents=True, exist_ok=True)
    for (rx, rz), chunks in grouped.items():
        _write_region(region_dir / f"r.{rx}.{rz}.mca", chunks)
    _level_dat(project, world["spawn"], world_dir / "level.dat")
