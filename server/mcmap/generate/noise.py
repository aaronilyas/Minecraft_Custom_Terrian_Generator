"""Deterministic value noise from the generator contract. Not random and not NumPy's Generator."""

from __future__ import annotations

import numpy as np

_MASK32 = 0xFFFFFFFF


def hash32(seed: int, x: int, y: int, z: int, salt: int) -> int:
    n = (int(seed) & _MASK32) ^ (int(x) * 374761393) ^ (int(y) * 668265263) ^ (int(z) * 2147483647) ^ (
        int(salt) * 1274126177
    )
    n &= _MASK32
    n = ((n ^ (n >> 13)) * 1274126177) & _MASK32
    return (n ^ (n >> 16)) & _MASK32


def hash32_array(seed: int, x, y, z, salt: int) -> np.ndarray:
    seed_i = np.int64(int(seed) & _MASK32)
    salt_i = np.int64(int(salt))
    xa = np.asarray(x, dtype=np.int64)
    ya = np.asarray(y, dtype=np.int64)
    za = np.asarray(z, dtype=np.int64)
    n = seed_i ^ (xa * np.int64(374761393)) ^ (ya * np.int64(668265263)) ^ (za * np.int64(2147483647)) ^ (
        salt_i * np.int64(1274126177)
    )
    n &= np.int64(_MASK32)
    n = ((n ^ (n >> np.int64(13))) * np.int64(1274126177)) & np.int64(_MASK32)
    return (n ^ (n >> np.int64(16))) & np.int64(_MASK32)


def value_noise_3d_array(seed: int, x, y, z, cell: int) -> np.ndarray:
    sx = np.asarray(x, dtype=np.float64) / float(cell)
    sy = np.asarray(y, dtype=np.float64) / float(cell)
    sz = np.asarray(z, dtype=np.float64) / float(cell)
    x0 = np.floor(sx).astype(np.int64)
    y0 = np.floor(sy).astype(np.int64)
    z0 = np.floor(sz).astype(np.int64)
    tx = sx - x0
    ty = sy - y0
    tz = sz - z0
    ux = tx * tx * (3.0 - 2.0 * tx)
    uy = ty * ty * (3.0 - 2.0 * ty)
    uz = tz * tz * (3.0 - 2.0 * tz)

    def lattice(ix, iy, iz):
        return (hash32_array(seed, ix, iy, iz, 99) % 10000) / 10000.0

    c000 = lattice(x0, y0, z0)
    c100 = lattice(x0 + 1, y0, z0)
    c010 = lattice(x0, y0 + 1, z0)
    c110 = lattice(x0 + 1, y0 + 1, z0)
    c001 = lattice(x0, y0, z0 + 1)
    c101 = lattice(x0 + 1, y0, z0 + 1)
    c011 = lattice(x0, y0 + 1, z0 + 1)
    c111 = lattice(x0 + 1, y0 + 1, z0 + 1)
    x00 = c000 + (c100 - c000) * ux
    x10 = c010 + (c110 - c010) * ux
    x01 = c001 + (c101 - c001) * ux
    x11 = c011 + (c111 - c011) * ux
    y0v = x00 + (x10 - x00) * uy
    y1v = x01 + (x11 - x01) * uy
    return y0v + (y1v - y0v) * uz


def height_noise_grid(seed: int, x_coords: np.ndarray, z_coords: np.ndarray, roughness: float) -> np.ndarray:
    cell = max(4, 32 - int(roughness * 20))
    x = x_coords.astype(np.float64)[:, None]
    z = z_coords.astype(np.float64)[None, :]
    n = value_noise_3d_array(seed ^ 0x11, x, 0.0, z, cell)
    n2 = value_noise_3d_array(seed ^ 0x12, x, 0.0, z, max(4, cell // 2))
    return (n * 0.75 + n2 * 0.25) * 2.0 - 1.0


def cave_density(seed: int, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray) -> np.ndarray:
    x = xs.astype(np.float64)[:, None]
    y = ys.astype(np.float64)[None, :]
    z = zs.astype(np.float64)[:, None]
    low = value_noise_3d_array(seed ^ 0x51, x, y, z, 12)
    high = value_noise_3d_array(seed ^ 0x52, x, y, z, 6)
    return low * 0.65 + high * 0.35


def cave_density_volume(seed: int, x_coords: np.ndarray, y_vals: np.ndarray, z_coords: np.ndarray) -> np.ndarray:
    """Density on a full x/z/y grid. Same noise as cave_density, broadcast over the tile."""
    x = np.asarray(x_coords, dtype=np.float64)[:, None, None]
    z = np.asarray(z_coords, dtype=np.float64)[None, :, None]
    y = np.asarray(y_vals, dtype=np.float64)[None, None, :]
    low = value_noise_3d_array(seed ^ 0x51, x, y, z, 12)
    high = value_noise_3d_array(seed ^ 0x52, x, y, z, 6)
    return low * 0.65 + high * 0.35
