import json
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from mcmap.api import create_app
from mcmap.paths import repo_root


def _client(tmp_path):
    app = create_app(repo_root(), tmp_path)
    return TestClient(app)


def test_create_reopen_and_edit(tmp_path):
    client = _client(tmp_path)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["minecraftVersion"] == "1.21.4"
    created = client.post(
        "/api/projects",
        json={"name": "Harbor", "width": 64, "depth": 96, "seed": 7, "spawn": {"x": 4, "z": -4}},
    )
    assert created.status_code == 200, created.text
    project = created.json()["project"]
    assert project["world"]["border"]["size"] == 96
    region = client.post(
        f"/api/projects/{project['id']}/operations",
        json={
            "operations": [
                {
                    "op": "region.create",
                    "args": {
                        "name": "Marsh",
                        "color": "#4C9A2A",
                        "shape": {"x": -20, "z": -10, "width": 16, "depth": 12},
                        "terrain": {"water": True, "baseHeight": 60},
                        "palette": {"surface": "minecraft:mud", "allowed": ["minecraft:mud", "minecraft:clay", "minecraft:water", "minecraft:dirt", "minecraft:stone"]},
                        "features": {"trees": {"kind": "none", "density": 0}, "vegetation": "none", "ores": False, "caves": False},
                    },
                }
            ]
        },
    )
    assert region.status_code == 200, region.text
    reopened = client.get(f"/api/projects/{project['id']}")
    assert reopened.json()["project"]["regions"][0]["name"] == "Marsh"
    rejected = client.post(
        f"/api/projects/{project['id']}/operations",
        json={"operations": [{"op": "region.move", "args": {"id": region.json()["results"][0]["regionId"], "x": 80, "z": 0}}]},
    )
    assert rejected.status_code == 422
    assert rejected.json()["errors"][0]["code"] == "out_of_bounds"
    listing = client.get("/api/projects")
    assert listing.json()["projects"][0]["name"] == "Harbor"


def test_reference_image_thumbnail(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/projects", json={"name": "Pics", "width": 32, "depth": 32, "seed": 3}).json()["project"]
    buffer = BytesIO()
    Image.new("RGB", (24, 18), (30, 120, 180)).save(buffer, format="PNG")
    uploaded = client.post(
        f"/api/projects/{project['id']}/assets",
        files={"file": ("coast.png", buffer.getvalue(), "image/png")},
        data={"caption": "Painted coast"},
    )
    assert uploaded.status_code == 200, uploaded.text
    asset = uploaded.json()["asset"]
    thumb = client.get(uploaded.json()["thumbnailUrl"])
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/png")
    attached = client.post(
        f"/api/projects/{project['id']}/operations",
        json={
            "operations": [
                {
                    "op": "region.create",
                    "args": {
                        "name": "Shore",
                        "color": "#D8C48A",
                        "shape": {"x": -8, "z": -8, "width": 8, "depth": 8},
                        "brief": {"text": "Sandy shore", "assetIds": [asset["id"]]},
                        "features": {"trees": {"kind": "none", "density": 0}, "vegetation": "none"},
                        "palette": {"allowed": ["minecraft:sand", "minecraft:sandstone", "minecraft:stone", "minecraft:water"]},
                        "terrain": {"baseHeight": 66, "amplitude": 2},
                    },
                }
            ]
        },
    )
    assert attached.status_code == 200, attached.text
    missing = client.post(
        f"/api/projects/{project['id']}/operations",
        json={
            "operations": [
                {
                    "op": "region.update",
                    "args": {
                        "id": attached.json()["results"][0]["regionId"],
                        "brief": {"assetIds": ["00000000-0000-4000-8000-000000000000"]},
                    },
                }
            ]
        },
    )
    assert missing.status_code == 422
    assert missing.json()["errors"][0]["code"] == "unknown_asset"


def test_edits_do_not_present_stale_preview_or_mesh(tmp_path):
    from mcmap.generate.service import generate

    client = _client(tmp_path)
    created = client.post(
        "/api/projects",
        json={"name": "Stale", "width": 32, "depth": 32, "seed": 4, "spawn": {"x": 0, "z": 0}},
    )
    assert created.status_code == 200, created.text
    project = created.json()["project"]
    assert project["generationFingerprint"]
    created_region = client.post(
        f"/api/projects/{project['id']}/operations",
        json={
            "operations": [
                {
                    "op": "region.create",
                    "args": {
                        "name": "Plot",
                        "color": "#336699",
                        "shape": {"x": -12, "z": -12, "width": 8, "depth": 8},
                        "terrain": {"baseHeight": 90, "amplitude": 0, "roughness": 0, "water": False},
                        "features": {"trees": {"kind": "none", "density": 0}, "vegetation": "none", "ores": False, "caves": False},
                    },
                }
            ]
        },
    )
    assert created_region.status_code == 200, created_region.text
    project = created_region.json()["project"]
    region_id = created_region.json()["results"][0]["regionId"]
    generate(project, str(tmp_path / project["id"]), {"kind": "all"})

    def preview(mode="topdown"):
        return client.get(f"/api/projects/{project['id']}/preview", params={"mode": mode})

    mesh = client.get(f"/api/projects/{project['id']}/mesh")
    assert mesh.status_code == 200
    assert mesh.headers["content-type"].startswith("application/json")
    assert preview().status_code == 200
    status = client.get(f"/api/projects/{project['id']}/generation").json()
    assert status["generated"] is True
    assert status["stale"] is False

    brief = client.post(
        f"/api/projects/{project['id']}/operations",
        json={"operations": [{"op": "region.update", "args": {"id": region_id, "brief": {"text": "Notes only"}}}]},
    )
    assert brief.status_code == 200, brief.text
    assert brief.json()["project"]["generationFingerprint"] == project["generationFingerprint"]
    assert client.get(f"/api/projects/{project['id']}/mesh").status_code == 200
    assert preview("isometric").status_code == 200

    moved = client.post(
        f"/api/projects/{project['id']}/operations",
        json={"operations": [{"op": "region.move", "args": {"id": region_id, "x": 4, "z": 4}}]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["project"]["generationFingerprint"] != project["generationFingerprint"]
    status = client.get(f"/api/projects/{project['id']}/generation").json()
    assert status["generated"] is False
    assert status["stale"] is True
    stale_mesh = client.get(f"/api/projects/{project['id']}/mesh")
    assert stale_mesh.status_code == 409
    assert "heights" not in stale_mesh.text
    stale_preview = preview()
    assert stale_preview.status_code == 409
    assert not stale_preview.headers["content-type"].startswith("image/")


def test_blocks_endpoint_rejects_nothing_and_lists_grass(tmp_path):
    client = _client(tmp_path)
    listed = client.get("/api/blocks", params={"q": "grass"})
    ids = [row["id"] for row in listed.json()["blocks"]]
    assert "minecraft:grass_block" in ids
    assert "minecraft:air" not in ids


def test_export_status_is_empty_until_saved_and_omits_samples(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/projects", json={"name": "Export Status", "width": 32, "depth": 32, "seed": 1}).json()["project"]
    missing = client.get(f"/api/projects/{project['id']}/export")
    assert missing.status_code == 200
    assert missing.json() == {"ok": True, "export": None}
    cache = tmp_path / project["id"] / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "last_export.json").write_text(
        json.dumps(
            {
                "ok": True,
                "worldDir": "/tmp/world",
                "zipPath": "/tmp/world.zip",
                "dataVersion": 4189,
                "spawn": {"x": 1, "y": 70, "z": 2},
                "validation": {
                    "ok": True,
                    "dataVersion": 4189,
                    "levelName": "Export Status",
                    "spawn": {"x": 1, "y": 70, "z": 2},
                    "borderSize": 32,
                    "chunkCount": 4,
                    "samples": [{"x": 0, "y": -64, "z": 0, "name": "minecraft:bedrock"}],
                    "errors": [],
                },
            }
        ),
        encoding="utf-8",
    )
    found = client.get(f"/api/projects/{project['id']}/export")
    assert found.status_code == 200, found.text
    body = found.json()["export"]
    assert body["worldDir"] == "/tmp/world"
    assert body["dataVersion"] == 4189
    assert body["validation"]["chunkCount"] == 4
    assert body["validation"]["borderSize"] == 32
    assert "samples" not in body["validation"]
    assert "zipPath" not in body
