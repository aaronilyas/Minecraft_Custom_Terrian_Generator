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


def test_blocks_endpoint_rejects_nothing_and_lists_grass(tmp_path):
    client = _client(tmp_path)
    listed = client.get("/api/blocks", params={"q": "grass"})
    ids = [row["id"] for row in listed.json()["blocks"]]
    assert "minecraft:grass_block" in ids
    assert "minecraft:air" not in ids
