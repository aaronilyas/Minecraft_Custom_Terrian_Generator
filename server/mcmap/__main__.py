from __future__ import annotations

import argparse

import uvicorn

from mcmap.api import create_app
from mcmap.paths import repo_root


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mcmap")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--projects-root", default=None)
    args = parser.parse_args(argv)
    root = repo_root()
    projects = args.projects_root or str(root / "data" / "projects")
    app = create_app(root, projects)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
