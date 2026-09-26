from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from mcmap.paths import schema_dir


class BlockRegistry:
    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.minecraft_version = data["minecraftVersion"]
        self.data_version = int(data["dataVersion"])
        self.blocks = {entry["id"]: entry for entry in data["blocks"]}

    def get(self, block_id: str) -> dict | None:
        return self.blocks.get(block_id)

    def known(self, block_id: str) -> bool:
        return block_id in self.blocks

    def placeable_ids(self) -> set[str]:
        return {block_id for block_id, entry in self.blocks.items() if entry.get("placeable")}

    def is_solid(self, block_id: str) -> bool:
        entry = self.blocks.get(block_id)
        return bool(entry and entry.get("solid"))

    def properties(self, block_id: str) -> dict[str, str]:
        entry = self.blocks.get(block_id)
        if not entry:
            return {}
        return {str(key): str(value) for key, value in (entry.get("properties") or {}).items()}

    def rgb(self, block_id: str) -> list[int]:
        entry = self.blocks.get(block_id) or self.blocks["minecraft:air"]
        return list(entry.get("rgb") or [0, 0, 0])

    def public_blocks(self) -> list[dict]:
        rows = []
        for entry in self.blocks.values():
            if not entry.get("placeable"):
                continue
            rows.append(
                {
                    "id": entry["id"],
                    "name": entry["name"],
                    "category": entry["category"],
                    "rgb": entry["rgb"],
                    "solid": entry["solid"],
                }
            )
        rows.sort(key=lambda item: (item["category"], item["name"]))
        return rows


@lru_cache(maxsize=1)
def load_registry() -> BlockRegistry:
    return BlockRegistry(schema_dir() / "blocks.json")
