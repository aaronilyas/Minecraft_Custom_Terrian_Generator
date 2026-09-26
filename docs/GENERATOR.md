# Generator and exporter

Implement this document exactly. Brief text, colors, names, and images do not affect blocks. Import `generation_fingerprint` and `generation_inputs` from `mcmap.model`; do not reimplement the fingerprint. Import block properties and colors from `mcmap.blocks.load_registry`.

## Public functions

```python
def generate(project: dict, project_dir: str, scope: dict) -> dict:
    """scope is {kind: all} or {kind: region, regionId} or {kind: rect, x, z, width, depth}.
    Returns ok, columnsWritten, chunksWritten, spawn {x,y,z}, spawnAdjusted, warnings, fingerprint.
    """

def sample_column(project: dict, project_dir: str, x: int, z: int) -> dict:
    """{"x","z","surfaceY","biome","blocks":[{"y","id"}, ...]} including every non-air block.
    Raise RuntimeError("not_generated") when the cache does not match the fingerprint.
    """

def render_preview(project: dict, project_dir: str, mode: str, out_path: str) -> dict:
    """mode is topdown or isometric. Write a PNG to out_path.
    Raise RuntimeError("not_generated") when the cache is missing.
    Return {"ok": True, "path": out_path, "width": int, "height": int}.
    """

def export_world(project: dict, project_dir: str, dest_dir: str) -> dict:
    """Generate first if the cache is missing or stale. Write a world folder and zip.
    Return worldDir, zipPath, dataVersion, spawn, validation.
    """

def validate_world(world_dir: str) -> dict:
    """Independent reader. Do not import the writer module.
    Return ok, dataVersion, levelName, spawn, borderSize, borderCenterX, borderCenterZ,
    chunkCount, samples [{x,y,z,name}], errors.
    """
```

## Files the API already reads

- `cache/last_generate.json` with `generated: true`, `fingerprint`, `spawn`, `spawnAdjusted`, `warnings`, `columnsWritten`, `finishedAt`.
- `cache/mesh.json` (schema below).
- `cache/last_export.json` with absolute `worldDir`, `zipPath`, `dataVersion`, and `validation`.

## Coordinate model

Generation domain is the border square from `mcmap.model.border_square`: `[-size/2, size/2)` on both axes. `size` is `max(width, depth)`.

Hard owner of a column:

- Walk regions from first to last. The last region whose rectangle contains `(x, z)` owns the column.
- Otherwise `defaultTerrain` owns it. Treat that profile like a region without a shape.

Features, surface material, stone, and biome use the hard owner. Trees and vegetation may place blocks only inside that owner's rectangle (default features only on columns no region contains).

Height blends. Let `blendRadius` be the project value.

```text
signed_distance(px, pz, rect):
  px, pz are x+0.5, z+0.5
  outside distance is the euclidean distance to the rectangle, returned negative
  inside distance is the minimum distance to an edge, returned positive

influence(profile_rect):
  if blendRadius <= 0: 1 inside the rect else 0
  sd = signed_distance(...)
  if sd >= blendRadius: 1
  if sd <= -blendRadius: 0
  t = (sd + blendRadius) / (2 * blendRadius)
  return t*t*(3-2*t)
```

Start from the default profile's height. For each region with influence `w > 0`, set `height = round((1-w)*height + w*regionHeight)`. Deep inside a region, `w` is 1, so the height equals that region's own height and does not depend on distant regions.

A column farther than `blendRadius` outside a region's rectangle must be identical before and after edits to that region. This is the stability rule. Tests must cover a full regenerate and a `scope.kind == "region"` regenerate.

## Noise

Use this hash, not `random` and not NumPy's generator.

```text
hash32(seed, x, y, z, salt) -> uint32:
  n = (seed & 0xFFFFFFFF) xor (x * 374761393) xor (y * 668265263) xor (z * 2147483647) xor (salt * 1274126177)
  n &= 0xFFFFFFFF
  n = ((n xor (n >> 13)) * 1274126177) & 0xFFFFFFFF
  return (n xor (n >> 16)) & 0xFFFFFFFF

lattice(seed, ix, iy, iz) = (hash32(seed, ix, iy, iz, 99) % 10000) / 10000

value_noise_3d(seed, x, y, z, cell):
  scale x,y,z by 1/cell
  fade(t) = t*t*(3-2*t)
  trilinear interpolation of the 8 lattice corners

height_noise(seed, x, z, roughness):
  cell = max(4, 32 - int(roughness * 20))
  n = value_noise_3d(seed xor 0x11, x, 0, z, cell)
  n2 = value_noise_3d(seed xor 0x12, x, 0, z, max(4, cell // 2))
  return (n * 0.75 + n2 * 0.25) * 2 - 1
```

`regionHeight = clamp(round(baseHeight + amplitude * height_noise(seed, x, z, roughness)), 8, 180)`.

If `terrain.water` is true, use `min(regionHeight, seaLevel - 4)` before the blend.

## Column materials

Let `H` be the blended height.

- `y == -64`: `minecraft:bedrock`
- If the owner's stone is `minecraft:stone` and `y < 0`: `minecraft:deepslate` (write its properties)
- Else stone from `-63` through `H-4` inclusive
- Subsurface from `H-3` through `H-1`
- Surface at `H`
- Air above, up to at least `y == 192`

If `H < seaLevel`, the solid surface becomes `minecraft:sand` when that block is in `allowed`, otherwise it stays the subsurface block. Fill `minecraft:water` using the owner's water block from `H+1` through `seaLevel-1` inclusive.

## Caves, ores, plants, camp

Skip a step when the owner's feature flag is off. Replace only stone or deepslate (the blocks placed above, not surface, dirt, sand, or water).

Caves: carve when `y > -60`, `y <= H-5`, and chebyshev distance from `(x, z)` to the requested spawn `(spawn.x, spawn.z)` is greater than 12.

```text
density = value_noise_3d(seed xor 0x51, x, y, z, 12) * 0.65
        + value_noise_3d(seed xor 0x52, x, y, z, 6) * 0.35
carve when density > 0.58, replacing the block with minecraft:cave_air
```

Ores, after caves, on this grid. `stride` is the last number. Place a plus shape (center and four edge neighbors) when `hash32(seed, x, y, z, salt) % 17 == 0` and the existing block is still host stone or deepslate. Use the deepslate ore id when `y < 0` and the host is `minecraft:stone` or `minecraft:deepslate`; otherwise use the regular ore id.

| Block | Deepslate | y | salt | stride |
| --- | --- | --- | --- | --- |
| coal_ore | deepslate_coal_ore | 0..96 | 1 | 7 |
| iron_ore | deepslate_iron_ore | -24..64 | 2 | 8 |
| copper_ore | deepslate_copper_ore | -16..48 | 3 | 9 |
| gold_ore | deepslate_gold_ore | -48..0 | 4 | 11 |
| redstone_ore | deepslate_redstone_ore | -64..-8 | 5 | 11 |
| lapis_ore | deepslate_lapis_ore | -32..16 | 6 | 13 |
| diamond_ore | deepslate_diamond_ore | -64..12 | 7 | 13 |

Trees, only on columns with `x % 5 == 2` and `z % 5 == 2`, and only inside the owner rectangle. Place when `hash32(seed, x, 0, z, 70) % 1000 < max(1, int(density * 8000))`. Skip, with a warning, if the kind's blocks are not all in `allowed`.

- Oak, birch, acacia: trunk height `4 + hash32(seed,x,0,z,71) % 3`, leaves in a radius-2 blob from `trunk-2` to `trunk+1`, skipping cells with Manhattan distance above 3. Do not replace the trunk.
- Spruce: trunk `5 + hash % 3`, leaves in radius 1.
- Jungle: trunk `6 + hash % 3`, leaves like oak.
- Cactus: only on sand, height `2 + hash % 2`, no leaves.

Logs and leaves use the registry properties (`axis`, `persistent`, `distance`, `waterlogged`). Never let a tree write outside its owner rectangle.

Vegetation on the remaining air at `H+1` when `hash32(seed, x, 0, z, 50) % 100 < 35`:

- temperate: `short_grass`, and a `poppy` or `dandelion` when that block is allowed and `hash % 11 == 0`
- lush: `short_grass` or `fern` when fern is allowed
- dry: `dead_bush` on sand
- cold: `short_grass`
- Plant only on grass, podzol, mycelium, or moss, except dry scrub which stays on sand.

Spawn search: spiral from the requested `spawn.x, spawn.z` out to radius 32. A column is safe when the solid surface is not water or lava, the two blocks above it are `minecraft:air`, and it is inside the border square. Set spawn to `(x, surfaceY+1, z)`. `spawnAdjusted` is true when x, z, or y differs from the stored spawn. If none is safe, build a 3×3 pad of the default surface at `y = seaLevel` around the requested column, clear two air blocks above, and warn `spawn pad built`.

Spawn camp, after everything else, only inside the border: `minecraft:crafting_table` at `(spawnX+2, surfaceY+1, spawnZ)` and a `minecraft:cobblestone` pillar at `(spawnX+3, spawnZ)` from `surfaceY+1` through `surfaceY+5`. Skip positions outside the square. This camp is the in-game landmark.

## Cache and previews

Recompute every column for `scope.kind == "all"`. For `region` or `rect`, recompute only columns within `blendRadius` of the target (region rectangle, or the given rect) and copy the other columns from the previous cache. If the previous cache is missing or the world fingerprint inputs other than regions changed, recompute everything.

`mesh.json`:

```json
{
  "minX": -64,
  "minZ": -64,
  "width": 128,
  "depth": 128,
  "step": 1,
  "seaLevel": 63,
  "heights": [0],
  "surface": ["minecraft:grass_block"]
}
```

`step` is 1 when `size <= 192`, 2 when `size <= 384`, otherwise 4. Arrays are row-major `(z - minZ) / step` then `(x - minX) / step`. Height is the visible top: water surface `seaLevel - 1` when flooded, otherwise the solid surface. `surface` is the block id at that visible top.

Top-down PNG: one pixel per column of the border square, column 0 is `minX`, row 0 is `minZ` (north, `-Z`, at the top). Color is the registry RGB of the visible surface. Isometric PNG: at least 640 pixels wide, back-to-front height columns, same colors, not a blank image.

## Anvil export for 1.21.4

World folder:

```text
<slug>/
  level.dat
  region/r.X.Z.mca
```

Zip that folder as a single top-level directory. Slug is the project name reduced to lowercase letters, numbers, and hyphens. Also write `session.lock` nowhere; a lock file makes Minecraft treat the world as open.

`level.dat` is gzip-compressed NBT with an empty root name. `nbtlib.File.write` already writes an empty root name and big-endian uncompressed NBT. Gzip that byte string for `level.dat`. Chunks inside a region are zlib (compression type 2), not gzip.

Root fields:

- `DataVersion`: int 4189
- `Data` compound:
  - `version` int 19133
  - `Version` compound `{Id: 4189, Name: "1.21.4", Series: "main", Snapshot: byte 0}`
  - `LevelName` string, `GameType` int 0 (survival), `Difficulty` byte 2, `hardcore` byte 0, `initialized` byte 1, `allowCommands` byte 0
  - `SpawnX`, `SpawnY`, `SpawnZ` ints, `SpawnAngle` float 0
  - `Time` long 0, `DayTime` long 1000, `LastPlayed` long (unix millis)
  - `BorderCenterX/Z` doubles 0, `BorderSize` and `BorderSizeLerpTarget` doubles of the border size, `BorderSizeLerpTime` long 0
  - `BorderWarningBlocks`, `BorderWarningTime`, `BorderSafeZone` doubles from the project, `BorderDamagePerBlock` double
  - `GameRules` compound of strings: `doMobSpawning=true`, `doDaylightCycle=true`, `keepInventory=false`, `mobGriefing=true`
  - `DataPacks`: `Enabled` list of string `vanilla`, `Disabled` empty list of string
  - `RandomSeed` long, `generatorName` string `flat`, `generatorVersion` int 1
  - `clearWeatherTime`, `rainTime`, `thunderTime` ints 0; `raining` and `thundering` bytes 0
  - `WorldGenSettings`: `bonus_chest` byte 0, `generate_features` byte 0, `seed` long, `dimensions` with `minecraft:overworld`, `minecraft:the_nether`, and `minecraft:the_end`. Each dimension `type` is its own id. Each generator is `{type: "minecraft:flat", settings: {biome: "minecraft:plains", features: byte 0, lakes: byte 0, layers: empty compound list}}`.

Chunk NBT, one compound per present chunk, zlib-compressed:

- `DataVersion` 4189, `xPos`, `zPos`, `yPos` -4, `Status` `minecraft:full`, `LastUpdate` long 0, `InhabitedTime` long 0, `isLightOn` byte 0
- `sections`: every section `Y` from -4 through 19. Each has `block_states` and `biomes`.
- `block_entities`: empty compound list
- `Heightmaps.MOTION_BLOCKING` and `WORLD_SURFACE`

Block index inside a section is `x + z*16 + y*256` for local `0..15`. Palette entries are `{Name, Properties}` and Properties is omitted when empty. Property values are strings. If the palette length is 1, omit `data`. Otherwise bits per index is `max(4, ceil(log2(paletteLength)))`. Pack into signed 64-bit longs, `64 // bits` indices each, no index crossing a long boundary. The same packing with no minimum of 4 applies to biomes (64 cells of 4×4×4, index `bx + bz*4 + by*16`). A single biome omits `data`. Use the hard owner's `vanillaBiome` for the cell's center column.

Heightmap values are 9 bits, 7 values per long, 37 longs. Minecraft stores the first available block above the highest relevant block, as `(highestRelevantY + 1) - minY` (`minY` is -64), or 0 when the column has no matching block. `WORLD_SURFACE` is the highest non-air. `MOTION_BLOCKING` is the highest solid or fluid. Leaves count as solid here.

Region file `r.<cx>>5>.<cz>>5>.mca`: 4096-byte locations, 4096-byte timestamps, then 4096-byte sectors. Location is a big-endian 3-byte sector offset plus a 1-byte sector count. Local index is `(chunk & 31) + (chunkZ & 31) * 32`. Chunk payload is a big-endian length (compressed size + 1), a type byte `2`, then zlib bytes. Empty chunks stay zero in the header.

Write every chunk that intersects the border square.

## Tests to add

Use 32×32 or 48×48 projects. Assert:

- Two `generate` calls produce the same `sample_column` away from spawn.
- Amplitude 0, caves off, ores off, trees none, vegetation none: at `(12, 12)` the column is bedrock at -64, deepslate from -63 through -1, stone from 0 through `baseHeight-4`, three subsurface blocks, the surface block, and air above. Spawn camp must not cover this sample.
- Two regions separated by more than `blendRadius + 4`. After changing only region A, a column inside B is unchanged for both a full generate and a region-scoped generate.
- Changing only brief text does not change sampled blocks.
- A cave-enabled region contains `minecraft:cave_air`. The same project with caves off does not.
- An ore-enabled region contains at least one of iron or coal ore.
- A column with height below sea level contains water up through `seaLevel-1`.
- Export then `validate_world`: `dataVersion` 4189, border size, spawn, `chunkCount > 0`, and the flat sample block name matches. The reader module must not import the writer module.
- Preview PNGs are non-empty and `mesh.json` lengths match the stepped grid.

Run `.venv/bin/pytest -q tests/test_generate.py tests/test_export.py`. Do not start the API or Vite.
