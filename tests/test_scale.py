"""Exact world size, edge chunks, organic masks, and compact generation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from mcmap.blocks import load_registry
from mcmap.export.reader import _column_records, _read_region_chunks
from mcmap.export.service import export_world
from mcmap.generate.compact import compute_fields
from mcmap.generate.service import generate, sample_column
from mcmap.model import (
    generation_fingerprint,
    new_project,
    storage_span,
    uses_compact_storage,
    validate_project,
    world_coverage,
)
from mcmap.ops import apply_operations


def _quiet(project: dict, base: int = 68) -> None:
    terrain = project["defaultTerrain"]
    terrain["terrain"].update({"baseHeight": base, "amplitude": 0, "roughness": 0, "water": False})
    terrain["features"].update(
        {"trees": {"kind": "none", "density": 0}, "vegetation": "none", "ores": False, "caves": False}
    )


def _columns(world_dir: Path) -> dict:
    registry = load_registry()
    found = {}
    errors: list[str] = []
    for path in sorted((world_dir / "region").glob("*.mca")):
        for chunk in _read_region_chunks(path):
            found.update(_column_records(chunk, registry, errors))
    assert errors == []
    return found


def test_exact_3000_coverage_and_negative_chunks():
    project = new_project("H3M Inspired — 3000", 3000, 3000, 3000424242, 0, 0)
    assert validate_project(project, load_registry()) == []
    coverage = world_coverage(project)
    assert coverage["playable"] == {
        "minX": -1500,
        "minZ": -1500,
        "maxX": 1500,
        "maxZ": 1500,
        "width": 3000,
        "depth": 3000,
    }
    storage = coverage["storage"]
    assert storage["chunkMinX"] == storage["chunkMinZ"] == -94
    assert storage["chunkMaxX"] == storage["chunkMaxZ"] == 93
    assert storage["chunksX"] == storage["chunksZ"] == 188
    assert storage["minX"] == storage["minZ"] == -1504
    assert storage["maxX"] == storage["maxZ"] == 1504
    assert storage["edgeColumns"] == {"west": 4, "east": 4, "north": 4, "south": 4}
    assert coverage["edgePolicy"] == "continuation"
    assert project["world"]["border"]["size"] == 3000
    assert uses_compact_storage(project) is True
    span = storage_span(-1500, 1500)
    assert span["chunkMin"] == -94 and span["chunkMax"] == 93
    assert (-1504 // 16) == -94
    odd = new_project("Odd", 33, 33, 1, 0, 0)
    odd_cover = world_coverage(odd)
    assert odd_cover["playable"]["width"] == 33
    assert odd_cover["playable"]["minX"] == -16
    assert odd_cover["playable"]["maxX"] == 17


def test_dimension_rules_allow_3000_and_reject_out_of_range():
    project = new_project("Wide", 3000, 3000, 1, 0, 0)
    assert validate_project(project, load_registry()) == []
    too_small = new_project("Small", 31, 64, 1)
    assert any(item["code"] == "invalid_dimension" for item in validate_project(too_small, load_registry()))
    too_big = new_project("Huge", 4097, 64, 1)
    assert any(item["code"] == "invalid_dimension" for item in validate_project(too_big, load_registry()))
    created = apply_operations(
        new_project("Resize", 64, 64, 1),
        [{"op": "world.set_meta", "args": {"width": 3000, "depth": 3000}}],
        load_registry(),
    )
    assert created["ok"], created
    assert created["project"]["world"]["border"]["size"] == 3000


def test_partial_edge_chunks_keep_the_playable_border(tmp_path: Path):
    project = new_project("Edge", 36, 36, 5, 0, 0)
    _quiet(project)
    project_dir = tmp_path / "edge"
    project_dir.mkdir()
    exported = export_world(project, str(project_dir), str(tmp_path / "out"))
    assert exported["validation"]["ok"], exported["validation"]["errors"]
    assert exported["validation"]["borderSize"] == 36
    assert exported["validation"]["chunkCount"] == 16
    columns = _columns(Path(exported["worldDir"]))
    assert columns[(-18, -18)]["bedrock"] == "minecraft:bedrock"
    assert columns[(-18, -18)]["surface"][1] == "minecraft:grass_block"
    assert columns[(17, 17)]["surface"][1] == "minecraft:grass_block"
    for edge in ((-19, 0), (18, 0), (0, -19), (0, 18), (-32, -32), (31, 31)):
        assert columns[edge]["bedrock"] == "minecraft:bedrock"
        assert columns[edge]["surface"] is not None
        assert columns[edge]["surface"][1] != "minecraft:air"
    assert (-33, 0) not in columns
    assert (32, 0) not in columns


def test_organic_mask_precedence_and_fingerprint(tmp_path: Path):
    project = new_project("Masks", 64, 64, 9, 0, 0)
    project["blendRadius"] = 0
    _quiet(project, 50)
    created = apply_operations(
        project,
        [
            {
                "op": "region.create",
                "args": {
                    "name": "West Blob",
                    "color": "#336699",
                    "shape": {"x": -24, "z": -24, "width": 32, "depth": 32},
                    "mask": {"kind": "ellipse", "warp": 0, "scale": 32},
                    "terrain": {"baseHeight": 90, "amplitude": 0, "roughness": 0, "water": False},
                    "features": {"trees": {"kind": "none", "density": 0}, "vegetation": "none", "ores": False, "caves": False},
                },
            },
            {
                "op": "region.create",
                "args": {
                    "name": "Later Blob",
                    "color": "#993333",
                    "shape": {"x": -8, "z": -8, "width": 16, "depth": 16},
                    "mask": {"kind": "ellipse", "warp": 0, "scale": 32},
                    "terrain": {"baseHeight": 110, "amplitude": 0, "roughness": 0, "water": False},
                    "features": {"trees": {"kind": "none", "density": 0}, "vegetation": "none", "ores": False, "caves": False},
                },
            },
        ],
        load_registry(),
    )
    assert created["ok"], created
    project = created["project"]
    before = generation_fingerprint(project)
    project_dir = tmp_path / "masks"
    project_dir.mkdir()
    generate(project, str(project_dir), {"kind": "all"})
    assert sample_column(project, str(project_dir), 0, 0)["surfaceY"] == 110
    assert sample_column(project, str(project_dir), -16, 0)["surfaceY"] == 90
    assert sample_column(project, str(project_dir), 24, 24)["surfaceY"] == 50
    briefed = deepcopy(project)
    briefed["regions"][0]["brief"]["text"] = "only a caption"
    assert generation_fingerprint(briefed) == before
    styled = deepcopy(project)
    styled["regions"][1]["terrain"]["style"] = "plateau"
    assert generation_fingerprint(styled) != before
    outside = apply_operations(
        project,
        [
            {
                "op": "region.update",
                "args": {
                    "id": project["regions"][0]["id"],
                    "mask": {"kind": "polygon", "points": [{"x": -40, "z": -20}, {"x": -10, "z": -20}, {"x": -10, "z": 0}]},
                },
            }
        ],
        load_registry(),
    )
    assert outside["ok"] is False
    assert outside["errors"][0]["code"] == "out_of_bounds"


def test_spawn_checks_and_compact_matches_voxel(tmp_path: Path):
    voxel = new_project("Parity", 48, 48, 99, 0, 0)
    _quiet(voxel, 70)
    voxel["defaultTerrain"]["features"]["caves"] = True
    voxel["defaultTerrain"]["features"]["ores"] = True
    voxel_dir = tmp_path / "voxel"
    voxel_dir.mkdir()
    voxel_result = generate(voxel, str(voxel_dir), {"kind": "all"})
    checks = voxel_result["spawnChecks"]
    assert checks["solid"] and checks["headroom"] and checks["dry"]
    assert checks["noImmediateFall"] and checks["nearbyClear"] and checks["route"]
    assert checks["pad"] is False
    compact = deepcopy(voxel)
    compact["world"]["storageMode"] = "compact"
    assert uses_compact_storage(compact) is True
    assert generation_fingerprint(compact) == generation_fingerprint(voxel)
    compact_dir = tmp_path / "compact"
    compact_dir.mkdir()
    first = generate(compact, str(compact_dir), {"kind": "all"})
    second = generate(compact, str(compact_dir), {"kind": "all"})
    assert first["spawn"] == second["spawn"] == voxel_result["spawn"]
    for x, z in ((0, 0), (12, -8), (-20, 15), (-24, -24), (23, 23)):
        assert sample_column(compact, str(compact_dir), x, z) == sample_column(voxel, str(voxel_dir), x, z)
    cached = json.loads((compact_dir / "cache" / "last_generate.json").read_text(encoding="utf-8"))
    assert cached["storage"] == "compact"
    assert cached["coverage"]["playable"]["width"] == 48


def test_field_tiles_match_a_single_rectangle():
    project = new_project("Tiles", 96, 80, 12345, 0, 0)
    _quiet(project, 72)
    created = apply_operations(
        project,
        [
            {
                "op": "region.create",
                "args": {
                    "name": "Blob",
                    "color": "#228855",
                    "shape": {"x": -30, "z": -20, "width": 40, "depth": 36},
                    "mask": {"kind": "blob", "warp": 12, "scale": 24},
                    "terrain": {"baseHeight": 100, "amplitude": 6, "roughness": 0.4, "water": False, "style": "rolling"},
                },
            }
        ],
        load_registry(),
    )
    assert created["ok"], created
    project = created["project"]
    block_ids = list(load_registry().blocks)
    from mcmap.model import VANILLA_BIOMES

    biomes = list(VANILLA_BIOMES)
    full = compute_fields(project, block_ids, biomes)
    west = compute_fields(project, block_ids, biomes, bounds=(-48, -48, 0, 48))
    east = compute_fields(project, block_ids, biomes, bounds=(0, -48, 48, 48))
    assert west["heights"].shape[0] + east["heights"].shape[0] == full["heights"].shape[0]
    assert (full["heights"][: west["heights"].shape[0]] == west["heights"]).all()
    assert (full["owners"][: west["heights"].shape[0]] == west["owners"]).all()
    assert (full["heights"][west["heights"].shape[0] :] == east["heights"]).all()
    assert (full["biomes"][west["heights"].shape[0] :] == east["biomes"]).all()
    again = compute_fields(project, block_ids, list(VANILLA_BIOMES))
    assert (again["heights"] == full["heights"]).all()
    assert (again["owners"] == full["owners"]).all()


def test_existing_example_still_validates():
    example = Path(__file__).resolve().parents[1] / "examples" / "coastal-vale" / "project.json"
    project = json.loads(example.read_text(encoding="utf-8"))
    assert validate_project(project, load_registry()) == []
    assert uses_compact_storage(project) is False
    assert world_coverage(project)["storage"]["edgeColumns"] == {"west": 0, "east": 0, "north": 0, "south": 0}
