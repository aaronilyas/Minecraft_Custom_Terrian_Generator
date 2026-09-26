"""Organic region masks.

A missing mask, or kind "rect", is the rectangle already stored in shape.
Ellipse and blob masks are inscribed in that rectangle. Blob is the ellipse
after the sample point is pushed by value noise. Polygon masks use absolute
world points that must lie inside the rectangle.

Hard ownership is the last mask that contains the column. Columns in a cove,
inside the rectangle but outside the mask, fall through to an earlier region
or to defaultTerrain. Height influence uses the same smoothstep as rectangles,
on the minimum of the rectangle distance and the mask distance, so a column
farther than blendRadius outside the rectangle stays at weight 0.

Water is not a separate mask mode. A profile with terrain.water true caps its
height at seaLevel - 4 before the blend. Unclaimed columns keep defaultTerrain,
which is the ocean when that profile has water enabled.
"""

from __future__ import annotations

import numpy as np

from mcmap.generate.noise import value_noise_3d_array

MASK_KINDS = ("rect", "ellipse", "polygon", "blob")


def mask_kind(region: dict) -> str:
    mask = region.get("mask")
    if not isinstance(mask, dict):
        return "rect"
    kind = mask.get("kind") or "rect"
    if kind not in MASK_KINDS:
        return "rect"
    return kind


def mask_falloff(region: dict, blend: int) -> int:
    mask = region.get("mask")
    if not isinstance(mask, dict) or "falloff" not in mask or mask.get("falloff") is None:
        return int(blend)
    return max(0, min(int(mask["falloff"]), int(blend)))


def plain_rect(region: dict, blend: int) -> bool:
    return mask_kind(region) == "rect" and mask_falloff(region, blend) == int(blend)


def signed_distance_grid(px: np.ndarray, pz: np.ndarray, rect: dict) -> np.ndarray:
    minx = float(rect["x"])
    maxx = float(rect["x"] + rect["width"])
    minz = float(rect["z"])
    maxz = float(rect["z"] + rect["depth"])
    dx_out = np.maximum(np.maximum(minx - px, 0.0), px - maxx)
    dz_out = np.maximum(np.maximum(minz - pz, 0.0), pz - maxz)
    outside = (dx_out > 0.0) | (dz_out > 0.0)
    dist_out = np.sqrt(dx_out * dx_out + dz_out * dz_out)
    dist_in = np.minimum(np.minimum(px - minx, maxx - px), np.minimum(pz - minz, maxz - pz))
    return np.where(outside, -dist_out, dist_in)


def _warp(region: dict, px: np.ndarray, pz: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    mask = region.get("mask") or {}
    warp = int(mask.get("warp") or 0)
    if warp <= 0:
        return px, pz
    cell = max(8, int(mask.get("scale") or 64))
    n1 = value_noise_3d_array(int(seed) ^ 0x31, px, 0.0, pz, cell)
    n2 = value_noise_3d_array(int(seed) ^ 0x32, px, 0.0, pz, cell)
    return px + (n1 * 2.0 - 1.0) * float(warp), pz + (n2 * 2.0 - 1.0) * float(warp)


def _ellipse_factor(rect: dict, px: np.ndarray, pz: np.ndarray) -> tuple[np.ndarray, float, float]:
    rx = max(float(rect["width"]) * 0.5, 0.5)
    rz = max(float(rect["depth"]) * 0.5, 0.5)
    cx = float(rect["x"]) + rx
    cz = float(rect["z"]) + rz
    nx = (px - cx) / rx
    nz = (pz - cz) / rz
    return np.sqrt(nx * nx + nz * nz), rx, rz


def _ellipse_sd(rect: dict, px: np.ndarray, pz: np.ndarray) -> np.ndarray:
    k, rx, rz = _ellipse_factor(rect, px, pz)
    radial = np.sqrt(((px - (float(rect["x"]) + rx)) ** 2) + ((pz - (float(rect["z"]) + rz)) ** 2))
    safe = np.maximum(k, 1e-6)
    return (1.0 - k) * (radial / safe)


def _polygon_points(region: dict) -> list[tuple[float, float]]:
    mask = region.get("mask") or {}
    points = []
    for point in mask.get("points") or []:
        if isinstance(point, dict):
            points.append((float(point["x"]), float(point["z"])))
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            points.append((float(point[0]), float(point[1])))
    return points


def _polygon_contains(points: list[tuple[float, float]], px: np.ndarray, pz: np.ndarray) -> np.ndarray:
    inside = np.zeros(px.shape, dtype=bool)
    if len(points) < 3:
        return inside
    previous = len(points) - 1
    for index, (xi, zi) in enumerate(points):
        xj, zj = points[previous]
        denom = (zj - zi) if zj != zi else 1e-12
        hit = ((zi > pz) != (zj > pz)) & (px < (xj - xi) * (pz - zi) / denom + xi)
        inside ^= hit
        previous = index
    return inside


def _segment_distance(px, pz, x1, z1, x2, z2) -> np.ndarray:
    dx = x2 - x1
    dz = z2 - z1
    length2 = dx * dx + dz * dz
    if length2 <= 1e-12:
        return np.sqrt((px - x1) ** 2 + (pz - z1) ** 2)
    t = np.clip(((px - x1) * dx + (pz - z1) * dz) / length2, 0.0, 1.0)
    return np.sqrt((px - (x1 + t * dx)) ** 2 + (pz - (z1 + t * dz)) ** 2)


def _polygon_sd(points: list[tuple[float, float]], px: np.ndarray, pz: np.ndarray) -> np.ndarray:
    if len(points) < 3:
        return np.full(px.shape, -1.0e6, dtype=np.float64)
    distance = np.full(px.shape, 1.0e9, dtype=np.float64)
    previous = len(points) - 1
    for index, (x1, z1) in enumerate(points):
        x2, z2 = points[previous]
        distance = np.minimum(distance, _segment_distance(px, pz, x1, z1, x2, z2))
        previous = index
    sign = np.where(_polygon_contains(points, px, pz), 1.0, -1.0)
    return sign * distance


def mask_signed_distance(region: dict, px: np.ndarray, pz: np.ndarray, seed: int) -> np.ndarray:
    kind = mask_kind(region)
    rect = region["shape"]
    if kind == "rect":
        return signed_distance_grid(px, pz, rect)
    warped_x, warped_z = _warp(region, px, pz, seed)
    if kind == "polygon":
        return _polygon_sd(_polygon_points(region), warped_x, warped_z)
    return _ellipse_sd(rect, warped_x, warped_z)


def contains_grid(region: dict, x_coords: np.ndarray, z_coords: np.ndarray, seed: int) -> np.ndarray:
    shape = region["shape"]
    x0 = int(shape["x"])
    z0 = int(shape["z"])
    inside_rect = (
        (x_coords[:, None] >= x0)
        & (x_coords[:, None] < x0 + int(shape["width"]))
        & (z_coords[None, :] >= z0)
        & (z_coords[None, :] < z0 + int(shape["depth"]))
    )
    if mask_kind(region) == "rect":
        return inside_rect
    px = x_coords.astype(np.float64)[:, None] + 0.5
    pz = z_coords.astype(np.float64)[None, :] + 0.5
    warped_x, warped_z = _warp(region, px, pz, seed)
    kind = mask_kind(region)
    if kind == "polygon":
        inside = _polygon_contains(_polygon_points(region), warped_x, warped_z)
    else:
        factor, _rx, _rz = _ellipse_factor(shape, warped_x, warped_z)
        inside = factor <= 1.0
    return inside_rect & inside


def smoothstep_weight(sd: np.ndarray, falloff: int) -> np.ndarray:
    weights = np.empty(sd.shape, dtype=np.float64)
    if falloff <= 0:
        weights[:] = np.where(sd > 0.0, 1.0, 0.0)
        return weights
    full = sd >= float(falloff)
    outside = sd <= -float(falloff)
    mid = ~full & ~outside
    weights[full] = 1.0
    weights[outside] = 0.0
    if np.any(mid):
        t = (sd[mid] + float(falloff)) / (2.0 * float(falloff))
        weights[mid] = t * t * (3.0 - 2.0 * t)
    return weights


def organic_influence(region: dict, falloff: int, x_coords: np.ndarray, z_coords: np.ndarray, seed: int) -> np.ndarray:
    if falloff <= 0:
        return contains_grid(region, x_coords, z_coords, seed).astype(np.float64)
    px = x_coords.astype(np.float64)[:, None] + 0.5
    pz = z_coords.astype(np.float64)[None, :] + 0.5
    sd_rect = signed_distance_grid(px, pz, region["shape"])
    sd_mask = mask_signed_distance(region, px, pz, seed)
    return smoothstep_weight(np.minimum(sd_rect, sd_mask), falloff)
