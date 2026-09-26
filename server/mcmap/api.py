from __future__ import annotations

import json
import sys
import threading
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from mcmap.blocks import load_registry
from mcmap.model import (
    DATA_VERSION,
    FORMAT_VERSION,
    MINECRAFT_VERSION,
    coerce_int,
    err,
    generation_fingerprint,
    new_id,
    new_project,
    now_iso,
    validate_project,
)
from mcmap.ops import apply_operations
from mcmap.paths import examples_dir
from mcmap.store import ProjectStore, StoreError


def _fail(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "errors": [err(code, message)]})


def _public_project(project: dict) -> dict:
    body = dict(project)
    body["generationFingerprint"] = generation_fingerprint(project)
    return body


def _cached_generation(project: dict, directory: Path) -> dict | None:
    path = directory / "cache" / "last_generate.json"
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("generated") and document.get("fingerprint") == generation_fingerprint(project):
        return document
    return None


def create_app(repo: Path, projects_root: Path | str) -> FastAPI:
    registry = load_registry()
    store = ProjectStore(Path(projects_root))
    app = FastAPI(title="Minecraft Map Studio")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.repo = Path(repo)
    app.state.store = store
    app.state.registry = registry
    app.state.locks = defaultdict(threading.Lock)
    app.state.jobs = {}
    app.state.agent_manager = None

    def lock_for(project_id: str) -> threading.Lock:
        return app.state.locks[project_id]

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "formatVersion": FORMAT_VERSION,
            "minecraftVersion": MINECRAFT_VERSION,
            "dataVersion": DATA_VERSION,
        }

    @app.get("/api/blocks")
    def blocks(q: str = ""):
        rows = registry.public_blocks()
        if q:
            needle = q.casefold()
            rows = [row for row in rows if needle in row["id"].casefold() or needle in row["name"].casefold()]
        return {"ok": True, "blocks": rows}

    @app.get("/api/projects")
    def list_projects():
        return {"ok": True, "projects": store.list_summaries()}

    @app.post("/api/projects")
    def create_project(body: dict):
        spawn = body.get("spawn") or {}
        if not isinstance(spawn, dict):
            spawn = {}
        project = new_project(
            str(body.get("name") or "Untitled map"),
            coerce_int(body.get("width", 128)) if body.get("width", 128) is not None else 128,
            coerce_int(body.get("depth", 128)) if body.get("depth", 128) is not None else 128,
            coerce_int(body.get("seed", 1)) if body.get("seed", 1) is not None else 1,
            coerce_int(spawn.get("x", 0)) or 0,
            coerce_int(spawn.get("z", 0)) or 0,
        )
        if "y" in spawn:
            coerced_y = coerce_int(spawn["y"])
            if coerced_y is not None:
                project["world"]["spawn"]["y"] = coerced_y
        if "seaLevel" in body:
            project["world"]["seaLevel"] = body["seaLevel"]
        errors = validate_project(project, registry)
        if errors:
            return JSONResponse(status_code=422, content={"ok": False, "errors": errors})
        store.save(project)
        return {"ok": True, "project": _public_project(project)}

    @app.post("/api/projects/import-example")
    def import_example():
        try:
            project = store.import_example(examples_dir() / "coastal-vale")
        except StoreError as exc:
            return _fail(404, exc.code, exc.message)
        errors = validate_project(project, registry)
        if errors:
            store.delete(project["id"])
            return JSONResponse(status_code=422, content={"ok": False, "errors": errors})
        return {"ok": True, "project": _public_project(project)}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        try:
            return {"ok": True, "project": _public_project(store.load(project_id))}
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 400
            return _fail(status, exc.code, exc.message)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str):
        try:
            store.delete(project_id)
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 400
            return _fail(status, exc.code, exc.message)
        return {"ok": True}

    @app.post("/api/projects/{project_id}/operations")
    def operate(project_id: str, body: dict):
        try:
            with lock_for(project_id):
                project = store.load(project_id)
                result = apply_operations(project, body.get("operations"), registry)
                if not result["ok"]:
                    return JSONResponse(status_code=422, content={"ok": False, "errors": result["errors"]})
                for asset in result["removedAssets"]:
                    store.delete_asset_files(project_id, asset)
                store.save(result["project"])
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 400
            return _fail(status, exc.code, exc.message)
        return {"ok": True, "project": _public_project(result["project"]), "results": result["results"]}

    @app.post("/api/projects/{project_id}/assets")
    async def upload_asset(project_id: str, file: UploadFile = File(...), caption: str = Form("")):
        raw = await file.read()
        try:
            with lock_for(project_id):
                project = store.load(project_id)
                record = store.save_asset(project, raw, caption)
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 422
            return _fail(status, exc.code, exc.message)
        return {"ok": True, "asset": record, "thumbnailUrl": f"/api/projects/{project_id}/assets/{record['id']}/thumb"}

    @app.get("/api/projects/{project_id}/assets/{asset_id}")
    def get_asset(project_id: str, asset_id: str):
        try:
            path = store.asset_file(project_id, asset_id)
        except StoreError as exc:
            status = 404 if exc.code in {"not_found", "unknown_asset"} else 400
            return _fail(status, exc.code, exc.message)
        if not path.is_file():
            return _fail(404, "unknown_asset", "Reference image file is missing.")
        return FileResponse(path)

    @app.get("/api/projects/{project_id}/assets/{asset_id}/thumb")
    def get_thumb(project_id: str, asset_id: str):
        try:
            path = store.asset_file(project_id, asset_id, thumb=True)
        except StoreError as exc:
            status = 404 if exc.code in {"not_found", "unknown_asset"} else 400
            return _fail(status, exc.code, exc.message)
        if not path.is_file():
            return _fail(404, "unknown_asset", "Thumbnail is missing.")
        return FileResponse(path, media_type="image/png")

    def _run_job(project_id: str, job: dict, body: dict) -> None:
        try:
            with lock_for(project_id):
                project = store.load(project_id)
                project_dir = str(store.project_dir(project_id))
                if job["type"] == "generate":
                    from mcmap.generate.service import generate

                    result = generate(project, project_dir, body.get("scope") or {"kind": "all"})
                else:
                    from mcmap.export.service import export_world

                    destination = str(store.project_dir(project_id) / "export")
                    result = export_world(project, project_dir, destination)
                if result.get("spawn"):
                    fresh = store.load(project_id)
                    fresh["world"]["spawn"] = result["spawn"]
                    fresh["updatedAt"] = now_iso()
                    store.save(fresh)
                    result["projectSpawn"] = fresh["world"]["spawn"]
                job["result"] = result
                job["status"] = "done"
                job["progress"] = 1
                job["message"] = "Finished"
        except ModuleNotFoundError as exc:
            job["status"] = "error"
            job["error"] = f"Required module is not available yet: {exc}"
        except Exception as exc:  # noqa: BLE001 - job status is the user-visible error channel
            job["status"] = "error"
            job["error"] = str(exc)

    @app.post("/api/projects/{project_id}/jobs")
    def start_job(project_id: str, body: dict):
        kind = body.get("type")
        if kind not in {"generate", "export"}:
            return _fail(422, "schema", "Job type must be generate or export.")
        try:
            store.load(project_id)
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 400
            return _fail(status, exc.code, exc.message)
        job = {
            "id": new_id(),
            "projectId": project_id,
            "type": kind,
            "status": "running",
            "progress": 0,
            "message": "Running",
            "error": None,
            "result": None,
        }
        app.state.jobs[job["id"]] = job
        threading.Thread(target=_run_job, args=(project_id, job, body), daemon=True).start()
        return {"ok": True, "job": job}

    @app.get("/api/projects/{project_id}/jobs/{job_id}")
    def get_job(project_id: str, job_id: str):
        job = app.state.jobs.get(job_id)
        if not job or job["projectId"] != project_id:
            return _fail(404, "not_found", "Job not found.")
        return {"ok": True, "job": job}

    @app.get("/api/projects/{project_id}/generation")
    def generation_status(project_id: str):
        try:
            project = store.load(project_id)
            directory = store.project_dir(project_id)
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 400
            return _fail(status, exc.code, exc.message)
        document = _cached_generation(project, directory)
        if document is None:
            stale = (directory / "cache" / "last_generate.json").is_file()
            return {"ok": True, "generated": False, "stale": stale}
        return {"ok": True, **document, "stale": False}

    @app.get("/api/projects/{project_id}/preview")
    def preview(project_id: str, mode: str = "topdown"):
        if mode not in {"topdown", "isometric"}:
            return _fail(422, "schema", "Preview mode must be topdown or isometric.")
        try:
            project = store.load(project_id)
            from mcmap.generate.preview import render_preview
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 400
            return _fail(status, exc.code, exc.message)
        except ModuleNotFoundError as exc:
            return _fail(503, "unavailable", f"Preview is not available yet: {exc}")
        out = store.project_dir(project_id) / "cache" / f"{mode}.png"
        try:
            render_preview(project, str(store.project_dir(project_id)), mode, str(out))
        except Exception as exc:  # noqa: BLE001
            if "not_generated" in str(exc):
                return _fail(409, "not_generated", "Generate the map before opening a preview.")
            return _fail(500, "runtime", str(exc))
        return FileResponse(out, media_type="image/png")

    @app.get("/api/projects/{project_id}/mesh")
    def mesh(project_id: str):
        try:
            project = store.load(project_id)
            directory = store.project_dir(project_id)
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 400
            return _fail(status, exc.code, exc.message)
        path = directory / "cache" / "mesh.json"
        if _cached_generation(project, directory) is None or not path.is_file():
            return _fail(409, "not_generated", "Generate the map before opening the 3D preview.")
        return FileResponse(path, media_type="application/json")

    @app.get("/api/projects/{project_id}/columns/{x}/{z}")
    def column(project_id: str, x: int, z: int):
        try:
            project = store.load(project_id)
            from mcmap.generate.service import sample_column
        except StoreError as exc:
            status = 404 if exc.code == "not_found" else 400
            return _fail(status, exc.code, exc.message)
        except ModuleNotFoundError as exc:
            return _fail(503, "unavailable", f"Sampler is not available yet: {exc}")
        try:
            return {"ok": True, "column": sample_column(project, str(store.project_dir(project_id)), x, z)}
        except Exception as exc:  # noqa: BLE001
            code = "not_generated" if "not_generated" in str(exc) else "runtime"
            status = 409 if code == "not_generated" else 500
            return _fail(status, code, str(exc))

    @app.get("/api/projects/{project_id}/export/download")
    def download_export(project_id: str):
        try:
            path = store.project_dir(project_id) / "cache" / "last_export.json"
        except StoreError as exc:
            return _fail(400, exc.code, exc.message)
        if not path.is_file():
            return _fail(404, "not_found", "Export the world before downloading it.")
        meta = json.loads(path.read_text(encoding="utf-8"))
        zip_path = Path(meta["zipPath"])
        if not zip_path.is_file():
            return _fail(404, "not_found", "Export archive is missing.")
        return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)

    def agents():
        if app.state.agent_manager is None:
            from mcmap.acp.manager import AgentManager

            app.state.agent_manager = AgentManager(str(app.state.repo), str(store.root), sys.executable)
        return app.state.agent_manager

    @app.get("/api/agents")
    def list_agents():
        try:
            return {"ok": True, "agents": agents().list_agents()}
        except ModuleNotFoundError as exc:
            return _fail(503, "unavailable", f"Agent support is not available yet: {exc}")

    @app.post("/api/agent-sessions")
    def start_session(body: dict):
        try:
            session = agents().start(body.get("agentId"), body.get("projectId"), body.get("permissionMode") or "ask")
        except ModuleNotFoundError as exc:
            return _fail(503, "unavailable", f"Agent support is not available yet: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _fail(422, "agent", str(exc))
        return {"ok": True, "session": session}

    @app.get("/api/agent-sessions/{session_id}")
    def get_session(session_id: str):
        try:
            return {"ok": True, "session": agents().get(session_id)}
        except ModuleNotFoundError as exc:
            return _fail(503, "unavailable", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _fail(404, "not_found", str(exc))

    @app.post("/api/agent-sessions/{session_id}/prompt")
    def prompt_session(session_id: str, body: dict):
        try:
            session = agents().prompt(session_id, body.get("text") or "", bool(body.get("includeImages", True)))
        except ModuleNotFoundError as exc:
            return _fail(503, "unavailable", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _fail(422, "agent", str(exc))
        return {"ok": True, "session": session}

    @app.post("/api/agent-sessions/{session_id}/cancel")
    def cancel_session(session_id: str):
        try:
            return {"ok": True, "session": agents().cancel(session_id)}
        except Exception as exc:  # noqa: BLE001
            return _fail(422, "agent", str(exc))

    @app.post("/api/agent-sessions/{session_id}/permissions/{request_id}")
    def resolve_permission(session_id: str, request_id: str, body: dict):
        try:
            session = agents().resolve_permission(session_id, request_id, body.get("outcome") or "deny")
        except Exception as exc:  # noqa: BLE001
            return _fail(422, "agent", str(exc))
        return {"ok": True, "session": session}

    @app.delete("/api/agent-sessions/{session_id}")
    def close_session(session_id: str):
        try:
            agents().close(session_id)
        except Exception as exc:  # noqa: BLE001
            return _fail(422, "agent", str(exc))
        return {"ok": True}

    return app
