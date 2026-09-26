from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcmap.blocks import load_registry
from mcmap.ops import apply_operations
from mcmap.store import ProjectStore, StoreError


def _print(payload: dict) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _load_json_arg(value: str) -> dict:
    if value == "-":
        raw = sys.stdin.read()
    elif value.startswith("@"):
        raw = Path(value[1:]).read_text(encoding="utf-8")
    else:
        raw = value
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON payload must be an object.")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcmap.cli")
    parser.add_argument("--root", required=True, help="Directory that contains project folders")
    parser.add_argument("--project", required=True, help="Project UUID")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("get")
    sub.add_parser("blocks")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--json", required=True, help="Operations object, @file, or - for stdin")
    generate_parser = sub.add_parser("generate")
    generate_parser.add_argument("--region")
    generate_parser.add_argument("--x", type=int)
    generate_parser.add_argument("--z", type=int)
    generate_parser.add_argument("--width", type=int)
    generate_parser.add_argument("--depth", type=int)
    preview_parser = sub.add_parser("preview")
    preview_parser.add_argument("--mode", required=True, choices=("topdown", "isometric"))
    preview_parser.add_argument("--out", required=True)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--out", required=True)
    sample_parser = sub.add_parser("sample")
    sample_parser.add_argument("--x", type=int, required=True)
    sample_parser.add_argument("--z", type=int, required=True)
    args = parser.parse_args(argv)
    store = ProjectStore(Path(args.root))
    try:
        project = store.load(args.project)
    except StoreError as exc:
        _print({"ok": False, "errors": [{"code": exc.code, "message": exc.message}]})
        return 2 if exc.code != "not_found" else 1
    project_dir = store.project_dir(args.project)
    try:
        if args.command == "get":
            _print({"ok": True, "project": project})
            return 0
        if args.command == "blocks":
            _print({"ok": True, "blocks": load_registry().public_blocks()})
            return 0
        if args.command == "apply":
            payload = _load_json_arg(args.json)
            result = apply_operations(project, payload.get("operations"), load_registry())
            if not result["ok"]:
                _print(result)
                return 2
            for asset in result["removedAssets"]:
                store.delete_asset_files(project["id"], asset)
            store.save(result["project"])
            _print({"ok": True, "project": result["project"], "results": result["results"]})
            return 0
        if args.command == "generate":
            from mcmap.generate.service import generate

            if args.region:
                scope = {"kind": "region", "regionId": args.region}
            elif args.x is not None:
                scope = {"kind": "rect", "x": args.x, "z": args.z, "width": args.width, "depth": args.depth}
            else:
                scope = {"kind": "all"}
            result = generate(project, str(project_dir), scope)
            if result.get("spawn"):
                project["world"]["spawn"] = result["spawn"]
                from mcmap.model import now_iso

                project["updatedAt"] = now_iso()
                store.save(project)
            _print({"ok": True, "result": result, "project": project})
            return 0
        if args.command == "preview":
            from mcmap.generate.preview import render_preview

            info = render_preview(project, str(project_dir), args.mode, args.out)
            _print({"ok": True, "result": info})
            return 0
        if args.command == "export":
            from mcmap.export.service import export_world

            result = export_world(project, str(project_dir), args.out)
            if result.get("spawn"):
                project["world"]["spawn"] = result["spawn"]
                from mcmap.model import now_iso

                project["updatedAt"] = now_iso()
                store.save(project)
            _print({"ok": True, "result": result})
            return 0
        if args.command == "sample":
            from mcmap.generate.service import sample_column

            _print({"ok": True, "column": sample_column(project, str(project_dir), args.x, args.z)})
            return 0
    except ModuleNotFoundError as exc:
        _print({"ok": False, "errors": [{"code": "unavailable", "message": f"Required module is not installed yet: {exc}"}]})
        return 1
    except json.JSONDecodeError as exc:
        _print({"ok": False, "errors": [{"code": "schema", "message": f"Invalid JSON: {exc}"}]})
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports the failure as JSON
        code = "not_generated" if "not_generated" in str(exc) else "runtime"
        _print({"ok": False, "errors": [{"code": code, "message": str(exc)}]})
        return 2 if code == "not_generated" else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
