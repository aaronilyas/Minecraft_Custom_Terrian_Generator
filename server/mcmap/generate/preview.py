"""Top-down and isometric previews plus the stepped mesh document."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from mcmap.blocks import load_registry
from mcmap.generate.storage import load_world
from mcmap.model import border_square, generation_fingerprint


def mesh_step(size: int) -> int:
    if size <= 192:
        return 1
    if size <= 384:
        return 2
    return 4


def visible_surface(world: dict, sea: int) -> tuple[np.ndarray, np.ndarray]:
    """Highest non-air block in each column, so trees and plants show on the map."""
    blocks = world["blocks"]
    names = world["block_ids"]
    skip = [index for index, name in enumerate(names) if name in {"minecraft:air", "minecraft:cave_air"}]
    occupied = ~np.isin(blocks, skip) if skip else np.ones(blocks.shape, dtype=bool)
    from_top = np.argmax(occupied[..., ::-1], axis=2)
    found = occupied.any(axis=2)
    y_index = occupied.shape[2] - 1 - from_top
    heights = world["heights"].astype(np.int32)
    fallback = np.where(heights < int(sea), int(sea) - 1, heights)
    fallback_index = np.clip(fallback - int(world["y_min"]), 0, occupied.shape[2] - 1)
    y_index = np.where(found, y_index, fallback_index)
    visible_y = (y_index + int(world["y_min"])).astype(np.int32)
    nx, nz = y_index.shape
    ix = np.arange(nx)[:, None]
    iz = np.arange(nz)[None, :]
    return visible_y, blocks[ix, iz, y_index]


def mesh_document(project: dict, world: dict) -> dict:
    min_x, min_z, max_x, max_z = border_square(project)
    sea = int(project["world"]["seaLevel"])
    visible_y, block_index = visible_surface(world, sea)
    nx, nz = visible_y.shape
    step = mesh_step(max_x - min_x)
    block_ids = world["block_ids"]
    heights = []
    surface = []
    for iz in range(0, nz, step):
        for ix in range(0, nx, step):
            heights.append(int(visible_y[ix, iz]))
            surface.append(block_ids[int(block_index[ix, iz])])
    return {
        "minX": int(min_x),
        "minZ": int(min_z),
        "width": int(nx),
        "depth": int(nz),
        "step": int(step),
        "seaLevel": sea,
        "heights": heights,
        "surface": surface,
    }


def write_mesh(project: dict, world: dict, path: str) -> dict:
    document = mesh_document(project, world)
    Path(path).write_text(json.dumps(document), encoding="utf-8")
    return document


def _color_lut(block_ids: list[str]) -> np.ndarray:
    registry = load_registry()
    lut = np.zeros((len(block_ids), 3), dtype=np.uint8)
    for index, block_id in enumerate(block_ids):
        rgb = registry.rgb(block_id)
        lut[index] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return lut


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(channel * factor))) for channel in color)


def _render_topdown(world: dict, sea: int, out_path: str) -> tuple[int, int]:
    _visible_y, block_index = visible_surface(world, sea)
    rgb = _color_lut(world["block_ids"])[block_index]
    image = Image.fromarray(np.transpose(rgb, (1, 0, 2)), mode="RGB")
    image.save(out_path, "PNG")
    return image.size


def _render_isometric(world: dict, sea: int, out_path: str) -> tuple[int, int]:
    visible_y, block_index = visible_surface(world, sea)
    colors = _color_lut(world["block_ids"])[block_index]
    nx, nz = visible_y.shape
    span = nx + nz
    scale = max(1, math.ceil(640 / span))
    hw = scale
    hh = max(1, scale // 2)
    vh = max(1, scale // 2)
    margin = scale * 2
    base_body = max(6, scale * 2)
    hmin = int(visible_y.min())
    hmax = int(visible_y.max())
    img_w = span * hw + margin * 2
    if img_w < 640:
        margin += (640 - img_w) // 2 + 1
        img_w = span * hw + margin * 2
    img_h = span * hh + (hmax - hmin) * vh + base_body + margin * 2
    origin_x = nz * hw + margin
    origin_y = (hmax - hmin) * vh + margin
    image = Image.new("RGB", (img_w, img_h), (16, 20, 28))
    draw = ImageDraw.Draw(image)
    order = sorted(((ix, iz) for iz in range(nz) for ix in range(nx)), key=lambda item: (item[0] + item[1], item[1], item[0]))
    for ix, iz in order:
        height = int(visible_y[ix, iz])
        color = (int(colors[ix, iz, 0]), int(colors[ix, iz, 1]), int(colors[ix, iz, 2]))
        body = base_body + (height - hmin) * vh
        sx = origin_x + (ix - iz) * hw
        sy = origin_y + (ix + iz) * hh - (height - hmin) * vh
        draw.polygon([sx, sy, sx + hw, sy + hh, sx, sy + 2 * hh, sx - hw, sy + hh], fill=_shade(color, 1.0))
        draw.polygon(
            [sx - hw, sy + hh, sx, sy + 2 * hh, sx, sy + 2 * hh + body, sx - hw, sy + hh + body],
            fill=_shade(color, 0.62),
        )
        draw.polygon(
            [sx + hw, sy + hh, sx, sy + 2 * hh, sx, sy + 2 * hh + body, sx + hw, sy + hh + body],
            fill=_shade(color, 0.78),
        )
    image.save(out_path, "PNG")
    return image.size


def render_preview(project: dict, project_dir: str, mode: str, out_path: str) -> dict:
    if mode not in ("topdown", "isometric"):
        raise RuntimeError(f"unknown preview mode {mode}")
    world = load_world(project_dir, generation_fingerprint(project))
    sea = int(project["world"]["seaLevel"])
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode == "topdown":
        width, height = _render_topdown(world, sea, str(destination))
    else:
        width, height = _render_isometric(world, sea, str(destination))
    return {"ok": True, "path": out_path, "width": int(width), "height": int(height)}
