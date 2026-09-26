# Map Studio contracts

This file is the ownership and acceptance contract. Normative details live in the linked docs. Do not redesign them in parallel.

## Stack

- One local app: Vite + React UI on `127.0.0.1:5173`, Python API on `127.0.0.1:8765`.
- One project format: `formatVersion` 1, folder per project under `data/projects/<uuid>/`.
- One generator and one Anvil exporter, both Python, pinned to Minecraft Java **1.21.4** (`dataVersion` **4189**).
- One ACP client. Agents edit the plan only through `python -m mcmap.cli`.
- No cloud accounts, no custom biome registry, no plugin system, no microservices.

Java 21 is installed and matches 1.21.4. Newer 26.x worlds changed biome cells and moved world-gen settings; they are out of scope.

## Module ownership

| Owner | Paths | Must not edit |
| --- | --- | --- |
| Lead | `docs/`, `schema/`, `server/mcmap/*.py` except packages below, `tests/test_ops.py`, `tests/test_api.py`, `examples/`, `scripts/`, `PROGRESS.md`, root config | generator, acp, ui internals after delegation |
| Generator | `server/mcmap/generate/`, `server/mcmap/export/`, `tests/test_generate.py`, `tests/test_export.py` | everything else |
| ACP | `server/mcmap/acp/`, `tests/test_acp.py` | everything else |
| UI | `ui/` | everything else |

Public Python imports the lead API already calls:

- `mcmap.generate.service.generate(project, project_dir, scope) -> dict`
- `mcmap.generate.service.sample_column(project, project_dir, x, z) -> dict`
- `mcmap.generate.preview.render_preview(project, project_dir, mode, out_path) -> dict`
- `mcmap.export.service.export_world(project, project_dir, dest_dir) -> dict`
- `mcmap.export.service.validate_world(world_dir) -> dict`
- `mcmap.acp.manager.AgentManager`

`project` is the dict stored in `project.json`. `project_dir` and `dest_dir` are strings. See `docs/GENERATOR.md` and `docs/ACP.md` for return values.

## Acceptance

1. Project and canvas: create, reopen, and save dimensions, seed, spawn, and border. Draw, move, and edit named regions. Values survive an API and page restart.
2. Region briefs: text, reference images with thumbnails, palettes, terrain, features. Unknown blocks and out-of-bounds shapes are rejected. `examples/coastal-vale` opens.
3. Generation: reproducible chunks, blended edges, surface layers, water, caves, ores, vegetation, safe spawn, distributed resources. Top-down PNG, isometric PNG, and a 3D mesh. Editing one region does not change a column farther than `blendRadius` outside that region.
4. ACP: discover Grok (`grok agent --no-leader stdio`, NDJSON, protocol 1) and show Codex as present but not auto-enabled. Sessions, progress, errors, cancel, and permission prompts work. The bundled test agent proves the command path. Invalid blocks and out-of-bounds edits never change the file.
5. Export: a Java 1.21.4 world folder and zip with spawn and border. An independent reader (separate module from the writer) checks `level.dat` and at least one chunk. In-game play is outstanding unless Minecraft is installed.

Run checks from the repo root:

```bash
.venv/bin/pytest -q
npm run dev
```

The lead owns the dev servers and the browser. Other work must not bind ports 5173 or 8765.
