from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def schema_dir() -> Path:
    return repo_root() / "schema"


def examples_dir() -> Path:
    return repo_root() / "examples"
