from __future__ import annotations

import json
import shutil
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from mcmap.model import is_uuid, new_id, now_iso

MAX_IMAGE_BYTES = 8_000_000
ALLOWED_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}


class StoreError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ProjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        if not is_uuid(project_id):
            raise StoreError("schema", "Project id must be a UUID.")
        return self.root / project_id

    def list_summaries(self) -> list[dict]:
        rows = []
        if not self.root.exists():
            return rows
        for path in self.root.iterdir():
            project_file = path / "project.json"
            if not project_file.is_file():
                continue
            try:
                project = json.loads(project_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            world = project.get("world") or {}
            rows.append(
                {
                    "id": project.get("id"),
                    "name": project.get("name"),
                    "width": world.get("width"),
                    "depth": world.get("depth"),
                    "seed": world.get("seed"),
                    "updatedAt": project.get("updatedAt"),
                    "regionCount": len(project.get("regions") or []),
                }
            )
        rows.sort(key=lambda row: row.get("updatedAt") or "", reverse=True)
        return rows

    def exists(self, project_id: str) -> bool:
        return (self.project_dir(project_id) / "project.json").is_file()

    def load(self, project_id: str) -> dict:
        path = self.project_dir(project_id) / "project.json"
        if not path.is_file():
            raise StoreError("not_found", "Project not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, project: dict) -> None:
        directory = self.project_dir(project["id"])
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "assets").mkdir(exist_ok=True)
        (directory / "cache").mkdir(exist_ok=True)
        target = directory / "project.json"
        temporary = directory / "project.json.tmp"
        temporary.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)

    def delete(self, project_id: str) -> None:
        directory = self.project_dir(project_id)
        if not directory.exists():
            raise StoreError("not_found", "Project not found.")
        shutil.rmtree(directory)

    def asset_file(self, project_id: str, asset_id: str, thumb: bool = False) -> Path:
        if not is_uuid(asset_id):
            raise StoreError("schema", "Asset id must be a UUID.")
        name = f"{asset_id}.thumb.png" if thumb else None
        directory = self.project_dir(project_id) / "assets"
        if thumb:
            return directory / name
        project = self.load(project_id)
        for asset in project.get("assets", []):
            if asset.get("id") == asset_id:
                return directory / asset["filename"]
        raise StoreError("unknown_asset", "Reference image not found.")

    def save_asset(self, project: dict, raw: bytes, caption: str) -> dict:
        if len(raw) > MAX_IMAGE_BYTES:
            raise StoreError("schema", "Reference images must be 8 MB or smaller.")
        if len(caption) > 200:
            raise StoreError("schema", "Caption must be 200 characters or fewer.")
        try:
            with Image.open(BytesIO(raw)) as image:
                image.load()
                fmt = image.format or ""
                if fmt not in ALLOWED_FORMATS:
                    raise StoreError("schema", "Use a PNG, JPEG, WEBP, or GIF image.")
                width, height = image.size
                thumb = image.convert("RGBA")
                thumb.thumbnail((160, 160))
        except StoreError:
            raise
        except (UnidentifiedImageError, OSError) as exc:
            raise StoreError("schema", "The file is not a readable image.") from exc
        asset_id = new_id()
        ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}[fmt]
        filename = f"{asset_id}.{ext}"
        directory = self.project_dir(project["id"]) / "assets"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_bytes(raw)
        thumb.save(directory / f"{asset_id}.thumb.png", format="PNG")
        record = {
            "id": asset_id,
            "filename": filename,
            "caption": caption.strip(),
            "mime": ALLOWED_FORMATS[fmt],
            "width": width,
            "height": height,
        }
        project.setdefault("assets", []).append(record)
        project["updatedAt"] = now_iso()
        self.save(project)
        return record

    def delete_asset_files(self, project_id: str, asset: dict) -> None:
        directory = self.project_dir(project_id) / "assets"
        for name in (asset.get("filename"), f"{asset.get('id')}.thumb.png"):
            if not name:
                continue
            path = directory / name
            if path.is_file():
                path.unlink()

    def import_example(self, example_dir: Path) -> dict:
        source = example_dir / "project.json"
        if not source.is_file():
            raise StoreError("not_found", "Example project is not available.")
        project = json.loads(source.read_text(encoding="utf-8"))
        project["id"] = new_id()
        stamp = now_iso()
        project["createdAt"] = stamp
        project["updatedAt"] = stamp
        self.save(project)
        asset_source = example_dir / "assets"
        asset_dest = self.project_dir(project["id"]) / "assets"
        if asset_source.is_dir():
            for item in asset_source.iterdir():
                if item.is_file():
                    shutil.copy2(item, asset_dest / item.name)
        for asset in project.get("assets", []):
            thumb = asset_dest / f"{asset['id']}.thumb.png"
            original = asset_dest / asset["filename"]
            if original.is_file() and not thumb.is_file():
                with Image.open(original) as image:
                    image = image.convert("RGBA")
                    image.thumbnail((160, 160))
                    image.save(thumb, format="PNG")
        return project
