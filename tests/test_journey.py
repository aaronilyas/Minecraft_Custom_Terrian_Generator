"""Lead integration journey. Skips until the generator and exporter packages exist."""

from __future__ import annotations

import importlib.util
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from mcmap.blocks import load_registry
from mcmap.model import generation_fingerprint, new_project
from mcmap.ops import apply_operations


def _available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


pytestmark = pytest.mark.skipif(
    not (_available("mcmap.generate.service") and _available("mcmap.export.service")),
    reason="generator and exporter are not integrated yet",
)


def _flat_world():
    project = new_project("Flat", 48, 48, 99, 0, 0)
    project["defaultTerrain"]["terrain"] = {
        "baseHeight": 70,
        "amplitude": 0,
        "roughness": 0,
        "water": False,
    }
    project["defaultTerrain"]["features"] = {
        "trees": {"kind": "none", "density": 0},
        "vegetation": "none",
        "ores": False,
        "caves": False,
    }
    return project


def test_flat_column_export_and_reopen(tmp_path):
    from mcmap.export.service import export_world, validate_world
    from mcmap.generate.service import generate, sample_column

    project = _flat_world()
    first = generate(project, str(tmp_path), {"kind": "all"})
    second = generate(project, str(tmp_path), {"kind": "all"})
    assert first["spawn"]["y"] > 70
    column = sample_column(project, str(tmp_path), 12, 12)
    ids = {block["y"]: block["id"] for block in column["blocks"]}
    assert ids[-64] == "minecraft:bedrock"
    assert ids[-1] == "minecraft:deepslate"
    assert ids[0] == "minecraft:stone"
    assert ids[66] == "minecraft:stone"
    assert ids[67] == "minecraft:dirt"
    assert ids[70] == "minecraft:grass_block"
    assert 71 not in ids
    again = sample_column(project, str(tmp_path), 12, 12)
    assert again == column
    assert second["fingerprint"] == first["fingerprint"] == generation_fingerprint(project)

    exported = export_world(project, str(tmp_path), str(tmp_path / "export"))
    report = validate_world(exported["worldDir"])
    assert report["ok"], report
    assert report["dataVersion"] == 4189
    assert report["borderSize"] == 48
    assert report["chunkCount"] > 0
    assert report["samples"]
    assert all(sample["name"].startswith("minecraft:") for sample in report["samples"])
    assert zipfile.ZipFile(exported["zipPath"]).namelist()


def test_distant_region_edit_is_stable(tmp_path):
    from mcmap.generate.service import generate, sample_column

    project = new_project("Split", 96, 96, 1234, 0, 0)
    created = apply_operations(
        project,
        [
            {
                "op": "region.create",
                "args": {
                    "name": "West",
                    "color": "#336699",
                    "shape": {"x": -40, "z": -16, "width": 16, "depth": 16},
                    "terrain": {"baseHeight": 80, "amplitude": 0, "roughness": 0, "water": False},
                    "features": {"trees": {"kind": "none", "density": 0}, "vegetation": "none", "ores": False, "caves": False},
                },
            },
            {
                "op": "region.create",
                "args": {
                    "name": "East",
                    "color": "#993333",
                    "shape": {"x": 24, "z": -8, "width": 16, "depth": 16},
                    "terrain": {"baseHeight": 60, "amplitude": 0, "roughness": 0, "water": False},
                    "features": {"trees": {"kind": "none", "density": 0}, "vegetation": "none", "ores": False, "caves": False},
                },
            },
        ],
        load_registry(),
    )
    assert created["ok"], created
    project = created["project"]
    east_id = next(region["id"] for region in project["regions"] if region["name"] == "East")
    generate(project, str(tmp_path), {"kind": "all"})
    before = sample_column(project, str(tmp_path), -32, -8)
    edited = deepcopy(project)
    for region in edited["regions"]:
        if region["name"] == "East":
            region["terrain"]["baseHeight"] = 90
    generate(edited, str(tmp_path), {"kind": "region", "regionId": east_id})
    after = sample_column(edited, str(tmp_path), -32, -8)
    assert after == before
