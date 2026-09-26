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
