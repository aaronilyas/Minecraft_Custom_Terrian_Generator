import json
from pathlib import Path

from mcmap.blocks import load_registry
from mcmap.model import generation_fingerprint, new_project, validate_project
from mcmap.ops import apply_operations
from mcmap.store import ProjectStore


def _project():
    project = new_project("Valley", 64, 64, 42, 0, 0)
    errors = validate_project(project, load_registry())
    assert errors == []
    return project


def test_region_persists_across_store_reload(tmp_path):
    store = ProjectStore(tmp_path)
    project = _project()
    store.save(project)
    created = apply_operations(
        store.load(project["id"]),
        [
            {
                "op": "region.create",
                "args": {
                    "name": "Meadow",
                    "color": "#7CB342",
                    "shape": {"x": -16, "z": -16, "width": 20, "depth": 24},
                    "brief": {"text": "Open grass", "assetIds": []},
                },
            }
        ],
        load_registry(),
    )
    assert created["ok"], created
    store.save(created["project"])
    moved = apply_operations(
        store.load(project["id"]),
        [{"op": "region.move", "args": {"id": created["results"][0]["regionId"], "x": -8, "z": 0}}],
        load_registry(),
    )
    assert moved["ok"], moved
    store.save(moved["project"])
    loaded = store.load(project["id"])
    assert loaded["regions"][0]["name"] == "Meadow"
    assert loaded["regions"][0]["shape"] == {"x": -8, "z": 0, "width": 20, "depth": 24}
    assert loaded["world"]["border"]["size"] == 64
    assert loaded["world"]["spawn"] == {"x": 0, "y": 64, "z": 0}


def test_rejects_unknown_block_and_out_of_bounds():
    project = _project()
    bad_block = apply_operations(
        project,
        [
            {
                "op": "region.create",
                "args": {
                    "name": "Odd",
                    "color": "#112233",
                    "shape": {"x": -8, "z": -8, "width": 8, "depth": 8},
                    "palette": {"surface": "minecraft:not_a_block"},
                },
            }
        ],
        load_registry(),
    )
    assert bad_block["ok"] is False
    assert bad_block["errors"][0]["code"] == "invalid_block"
    outside = apply_operations(
        project,
        [
            {
                "op": "region.create",
                "args": {
                    "name": "Edge",
                    "color": "#112233",
                    "shape": {"x": 20, "z": 0, "width": 16, "depth": 8},
                },
            }
        ],
        load_registry(),
    )
    assert outside["ok"] is False
    assert outside["errors"][0]["code"] == "out_of_bounds"


def test_brief_edit_does_not_change_generation_fingerprint():
    project = _project()
    created = apply_operations(
        project,
        [{"op": "region.create", "args": {"name": "Meadow", "color": "#7CB342", "shape": {"x": -16, "z": -16, "width": 16, "depth": 16}}}],
        load_registry(),
    )
    assert created["ok"]
    before = generation_fingerprint(created["project"])
    updated = apply_operations(
        created["project"],
        [{"op": "region.update", "args": {"id": created["results"][0]["regionId"], "brief": {"text": "A quieter meadow"}}}],
        load_registry(),
    )
    assert updated["ok"]
    assert generation_fingerprint(updated["project"]) == before
    changed = apply_operations(
        updated["project"],
        [{"op": "region.update", "args": {"id": created["results"][0]["regionId"], "terrain": {"baseHeight": 80}}}],
        load_registry(),
    )
    assert changed["ok"]
    assert generation_fingerprint(changed["project"]) != before


def test_example_project_validates():
    example = Path(__file__).resolve().parents[1] / "examples" / "coastal-vale"
    project = json.loads((example / "project.json").read_text(encoding="utf-8"))
    assert validate_project(project, load_registry()) == []
    assert (example / "assets" / "33333333-3333-4333-8333-333333333333.png").is_file()
    assert {region["name"] for region in project["regions"]} == {"Meadow", "Dunes"}


def test_dimension_and_seed_rules():
    project = new_project("Bad", 30, 64, 1)
    errors = validate_project(project, load_registry())
    assert any(item["code"] == "invalid_dimension" for item in errors)
    project = _project()
    result = apply_operations(project, [{"op": "world.set_meta", "args": {"seed": 2**53}}], load_registry())
    assert result["ok"] is False
    locked = apply_operations(project, [{"op": "world.set_meta", "args": {"border": {"size": 32}}}], load_registry())
    assert locked["ok"] is False
    assert locked["errors"][0]["code"] == "border_locked"


def test_cli_apply_roundtrip(tmp_path):
    store = ProjectStore(tmp_path)
    project = _project()
    store.save(project)
    import os
    import subprocess

    payload = {
        "operations": [
            {"op": "region.create", "args": {"name": "Dunes", "color": "#E6C36A", "shape": {"x": 0, "z": -12, "width": 12, "depth": 12}}}
        ]
    }
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "server")
    completed = subprocess.run(
        [
            env.get("PYTHON", "") or __import__("sys").executable,
            "-m",
            "mcmap.cli",
            "--root",
            str(tmp_path),
            "--project",
            project["id"],
            "apply",
            "--json",
            json.dumps(payload),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    body = json.loads(completed.stdout)
    assert body["project"]["regions"][0]["name"] == "Dunes"
    listed = subprocess.run(
        [__import__("sys").executable, "-m", "mcmap.cli", "--root", str(tmp_path), "--project", project["id"], "get"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert json.loads(listed.stdout)["project"]["regions"][0]["name"] == "Dunes"
