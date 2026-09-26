"""Export a generated project to a Java 1.21.4 world folder and zip."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from mcmap.export.reader import validate_world
from mcmap.export.writer import slugify, write_world
from mcmap.generate.service import generate
from mcmap.generate.storage import load_world
from mcmap.model import DATA_VERSION, generation_fingerprint


def _cache_fresh(project: dict, project_dir: Path) -> bool:
    meta_path = project_dir / "cache" / "last_generate.json"
    columns = project_dir / "cache" / "columns.npz"
    if not meta_path.is_file() or not columns.is_file():
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return bool(meta.get("generated")) and meta.get("fingerprint") == generation_fingerprint(project)


def export_world(project: dict, project_dir: str, dest_dir: str) -> dict:
    project_path = Path(project_dir)
    if not _cache_fresh(project, project_path):
        generate(project, project_dir, {"kind": "all"})
    fingerprint = generation_fingerprint(project)
    world = load_world(project_dir, fingerprint)
    meta = json.loads((project_path / "cache" / "last_generate.json").read_text(encoding="utf-8"))
    world["spawn"] = meta["spawn"]
    slug = slugify(str(project["name"]))
    destination = Path(dest_dir)
    destination.mkdir(parents=True, exist_ok=True)
    world_dir = (destination / slug).resolve()
    zip_path = (destination / f"{slug}.zip").resolve()
    if world_dir.exists():
        shutil.rmtree(world_dir)
    world_dir.mkdir(parents=True)
    write_world(project, world, world_dir)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(world_dir.rglob("*")):
            if path.is_file() and path.name != "session.lock":
                archive.write(path, f"{slug}/{path.relative_to(world_dir).as_posix()}")
    validation = validate_world(str(world_dir))
    payload = {
        "ok": bool(validation.get("ok")),
        "worldDir": str(world_dir),
        "zipPath": str(zip_path),
        "dataVersion": DATA_VERSION,
        "spawn": {"x": int(meta["spawn"]["x"]), "y": int(meta["spawn"]["y"]), "z": int(meta["spawn"]["z"])},
        "validation": validation,
    }
    cache = project_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "last_export.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload
