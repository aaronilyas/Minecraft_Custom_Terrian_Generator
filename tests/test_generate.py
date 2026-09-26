import ast
import json
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from mcmap.generate.preview import render_preview
from mcmap.generate.service import generate, sample_column
from mcmap.model import generation_fingerprint, new_project


def _quiet(profile: dict, base: int, surface: str | None = None) -> None:
    profile["terrain"]["baseHeight"] = base
    profile["terrain"]["amplitude"] = 0
    profile["terrain"]["roughness"] = 0
    profile["terrain"]["water"] = False
    profile["features"]["trees"] = {"kind": "none", "density": 0}
    profile["features"]["vegetation"] = "none"
    profile["features"]["ores"] = False
    profile["features"]["caves"] = False
    if surface is not None:
        profile["palette"]["surface"] = surface
        if surface not in profile["palette"]["allowed"]:
            profile["palette"]["allowed"].append(surface)


def _flat(size: int = 32, seed: int = 1, base: int = 68) -> dict:
    project = new_project("Flat Test", size, size, seed, 0, 0)
    _quiet(project["defaultTerrain"], base)
    return project


def _region(project: dict, region_id: str, name: str, shape: dict, base: int, surface: str | None = None) -> dict:
    profile = deepcopy(project["defaultTerrain"])
    _quiet(profile, base, surface)
    region = {
        "id": region_id,
        "name": name,
        "color": "#336699",
        "shape": shape,
        "brief": {"text": "notes", "assetIds": []},
        **profile,
    }
    project["regions"].append(region)
    return region


def _block_map(column: dict) -> dict[int, str]:
    return {block["y"]: block["id"] for block in column["blocks"]}


def test_reproducible_samples(tmp_path: Path):
    project = new_project("Repeat", 32, 32, 99, 0, 0)
    project_dir = tmp_path / "repeat"
    project_dir.mkdir()
    generate(project, str(project_dir), {"kind": "all"})
    first = sample_column(project, str(project_dir), 12, 12)
    generate(project, str(project_dir), {"kind": "all"})
    second = sample_column(project, str(project_dir), 12, 12)
    assert first == second
    assert first["blocks"]


def test_flat_column_materials_spawn_and_preview(tmp_path: Path):
    project = _flat()
    project_dir = tmp_path / "flat"
    project_dir.mkdir()
    result = generate(project, str(project_dir), {"kind": "all"})
    column = sample_column(project, str(project_dir), 12, 12)
    base = 68
    expected = [(-64, "minecraft:bedrock")]
    expected.extend((y, "minecraft:deepslate") for y in range(-63, 0))
    expected.extend((y, "minecraft:stone") for y in range(0, base - 4 + 1))
    expected.extend((y, "minecraft:dirt") for y in range(base - 3, base))
    expected.append((base, "minecraft:grass_block"))
    assert [(block["y"], block["id"]) for block in column["blocks"]] == expected
    assert column["surfaceY"] == base
    assert column["biome"] == "minecraft:plains"
    assert result["spawn"] == {"x": 0, "y": base + 1, "z": 0}
    assert result["spawnAdjusted"] is True
    assert result["warnings"] == []
    assert result["columnsWritten"] == 32 * 32
    assert result["chunksWritten"] == 4
    assert result["fingerprint"] == generation_fingerprint(project)

    cached = json.loads((project_dir / "cache" / "last_generate.json").read_text(encoding="utf-8"))
    assert cached["generated"] is True
    assert cached["fingerprint"] == result["fingerprint"]
    assert cached["spawn"] == result["spawn"]
    assert cached["columnsWritten"] == 32 * 32
    assert cached["finishedAt"]

    mesh = json.loads((project_dir / "cache" / "mesh.json").read_text(encoding="utf-8"))
    assert mesh["step"] == 1
    assert mesh["minX"] == -16 and mesh["minZ"] == -16
    assert mesh["width"] == 32 and mesh["depth"] == 32
    assert mesh["seaLevel"] == 63
    assert len(mesh["heights"]) == 32 * 32
    assert len(mesh["surface"]) == len(mesh["heights"])
    assert "minecraft:grass_block" in mesh["surface"]
    assert set(mesh["surface"]) <= {
        "minecraft:grass_block",
        "minecraft:cobblestone",
        "minecraft:crafting_table",
    }

    top_path = tmp_path / "top.png"
    iso_path = tmp_path / "iso.png"
    top = render_preview(project, str(project_dir), "topdown", str(top_path))
    iso = render_preview(project, str(project_dir), "isometric", str(iso_path))
    assert top == {"ok": True, "path": str(top_path), "width": 32, "height": 32}
    assert top_path.stat().st_size > 0
    assert iso["width"] >= 640 and iso["height"] > 0
    assert iso_path.stat().st_size > 0
    assert Image.open(iso_path).convert("L").getextrema()[0] != Image.open(iso_path).convert("L").getextrema()[1]


def test_distant_region_is_stable_for_full_and_scoped_regeneration(tmp_path: Path):
    project = _flat(size=48, seed=7, base=68)
    project["blendRadius"] = 4
    region_a = _region(
        project,
        "11111111-1111-4111-8111-111111111111",
        "A",
        {"x": -24, "z": -24, "width": 8, "depth": 8},
        100,
    )
    _region(
        project,
        "22222222-2222-4222-8222-222222222222",
        "B",
        {"x": 4, "z": 4, "width": 16, "depth": 16},
        70,
        "minecraft:moss_block",
    )
    gap = 4 - (-16)
    assert gap > project["blendRadius"] + 4

    def expect_b(column: dict) -> None:
        base = 70
        expected = [(-64, "minecraft:bedrock")]
        expected.extend((y, "minecraft:deepslate") for y in range(-63, 0))
        expected.extend((y, "minecraft:stone") for y in range(0, base - 4 + 1))
        expected.extend((y, "minecraft:dirt") for y in range(base - 3, base))
        expected.append((base, "minecraft:moss_block"))
        assert [(block["y"], block["id"]) for block in column["blocks"]] == expected
        assert column["surfaceY"] == base

    full_dir = tmp_path / "full"
    full_dir.mkdir()
    generate(project, str(full_dir), {"kind": "all"})
    before_full = sample_column(project, str(full_dir), 12, 12)
    expect_b(before_full)
    changed = deepcopy(project)
    changed["regions"][0]["terrain"]["baseHeight"] = 40
    generate(changed, str(full_dir), {"kind": "all"})
    assert sample_column(changed, str(full_dir), 12, 12) == before_full

    partial_dir = tmp_path / "partial"
    partial_dir.mkdir()
    generate(project, str(partial_dir), {"kind": "all"})
    before = sample_column(project, str(partial_dir), 12, 12)
    inside_before = sample_column(project, str(partial_dir), -22, -22)
    changed = deepcopy(project)
    changed["regions"][0]["terrain"]["baseHeight"] = 40
    scoped = generate(changed, str(partial_dir), {"kind": "region", "regionId": region_a["id"]})
    assert sample_column(changed, str(partial_dir), 12, 12) == before
    assert sample_column(changed, str(partial_dir), -22, -22) != inside_before
    assert 0 < scoped["columnsWritten"] < 48 * 48


def test_brief_text_does_not_change_blocks(tmp_path: Path):
    project = _flat()
    _region(project, "33333333-3333-4333-8333-333333333333", "Notes", {"x": -8, "z": -8, "width": 8, "depth": 8}, 72)
    project_dir = tmp_path / "brief"
    project_dir.mkdir()
    generate(project, str(project_dir), {"kind": "all"})
    before = sample_column(project, str(project_dir), 12, 12)
    project["regions"][0]["brief"]["text"] = "A different description that must not move a single block."
    assert generation_fingerprint(project) == json.loads((project_dir / "cache" / "last_generate.json").read_text())["fingerprint"]
    assert sample_column(project, str(project_dir), 12, 12) == before
    generate(project, str(project_dir), {"kind": "all"})
    assert sample_column(project, str(project_dir), 12, 12) == before


def test_caves_ores_and_underwater_column(tmp_path: Path):
    project = new_project("Cavern", 48, 48, 99, 0, 0)
    _quiet(project["defaultTerrain"], 80)
    project["defaultTerrain"]["features"]["caves"] = True
    project["defaultTerrain"]["features"]["ores"] = True
    region = _region(project, "44444444-4444-4444-8444-444444444444", "Cavern", {"x": -20, "z": -20, "width": 40, "depth": 40}, 80)
    region["features"]["caves"] = True
    region["features"]["ores"] = True
    project_dir = tmp_path / "caves"
    project_dir.mkdir()
    generate(project, str(project_dir), {"kind": "all"})
    ore_ids = {
        "minecraft:coal_ore",
        "minecraft:deepslate_coal_ore",
        "minecraft:iron_ore",
        "minecraft:deepslate_iron_ore",
    }
    found_cave = False
    found_ore = False
    shape = region["shape"]
    for z in range(shape["z"], shape["z"] + shape["depth"]):
        for x in range(shape["x"], shape["x"] + shape["width"]):
            blocks = {block["id"] for block in sample_column(project, str(project_dir), x, z)["blocks"]}
            found_cave = found_cave or "minecraft:cave_air" in blocks
            found_ore = found_ore or bool(blocks & ore_ids)
            if found_cave and found_ore:
                break
        if found_cave and found_ore:
            break
    assert found_cave
    assert found_ore

    project["defaultTerrain"]["features"]["caves"] = False
    region["features"]["caves"] = False
    generate(project, str(project_dir), {"kind": "all"})
    min_x = project["world"]["border"]["size"] // 2
    for z in range(-min_x, min_x):
        for x in range(-min_x, min_x):
            blocks = {block["id"] for block in sample_column(project, str(project_dir), x, z)["blocks"]}
            assert "minecraft:cave_air" not in blocks

    wet = _flat(base=40)
    wet["defaultTerrain"]["terrain"]["water"] = True
    wet_dir = tmp_path / "wet"
    wet_dir.mkdir()
    wet_result = generate(wet, str(wet_dir), {"kind": "all"})
    assert "spawn pad built" in wet_result["warnings"]
    water = _block_map(sample_column(wet, str(wet_dir), 12, 12))
    assert water[40] == "minecraft:sand"
    assert water[39] == "minecraft:dirt"
    for y in range(41, 63):
        assert water[y] == "minecraft:water"
    assert 63 not in water


def test_sample_and_preview_require_current_cache(tmp_path: Path):
    project = _flat()
    with pytest.raises(RuntimeError, match="not_generated"):
        sample_column(project, str(tmp_path), 0, 0)
    with pytest.raises(RuntimeError, match="not_generated"):
        render_preview(project, str(tmp_path), "topdown", str(tmp_path / "missing.png"))
    project_dir = tmp_path / "stale"
    project_dir.mkdir()
    generate(project, str(project_dir), {"kind": "all"})
    project["world"]["seed"] = 123456
    with pytest.raises(RuntimeError, match="not_generated"):
        sample_column(project, str(project_dir), 0, 0)
    with pytest.raises(RuntimeError, match="not_generated"):
        render_preview(project, str(project_dir), "isometric", str(tmp_path / "stale.png"))


def test_preview_module_has_no_export_dependency():
    source = Path(__file__).resolve().parents[1].joinpath("server/mcmap/generate/preview.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or not node.module.startswith("mcmap.export")
        elif isinstance(node, ast.Import):
            assert all(not alias.name.startswith("mcmap.export") for alias in node.names)
