# World-plan operations

The plan is changed by one implementation: `mcmap.ops.apply_operations`. The HTTP API and the CLI both call it. A failed batch changes nothing.

## CLI

```bash
PYTHONPATH=server .venv/bin/python -m mcmap.cli --root data/projects --project <uuid> get
PYTHONPATH=server .venv/bin/python -m mcmap.cli --root data/projects --project <uuid> blocks
PYTHONPATH=server .venv/bin/python -m mcmap.cli --root data/projects --project <uuid> apply --json '{"operations":[...]}'
PYTHONPATH=server .venv/bin/python -m mcmap.cli --root data/projects --project <uuid> generate
PYTHONPATH=server .venv/bin/python -m mcmap.cli --root data/projects --project <uuid> generate --region <regionUuid>
PYTHONPATH=server .venv/bin/python -m mcmap.cli --root data/projects --project <uuid> preview --mode topdown --out /tmp/top.png
PYTHONPATH=server .venv/bin/python -m mcmap.cli --root data/projects --project <uuid> sample --x 0 --z 0
PYTHONPATH=server .venv/bin/python -m mcmap.cli --root data/projects --project <uuid> export --out data/projects/<uuid>/export
```

`--json -` reads stdin. `--json @file` reads a file. Stdout is one JSON object. Exit `0` success, `2` validation, `1` runtime or missing project. `generate`, `preview`, `sample`, and `export` return `unavailable` until those modules exist.

## HTTP

| Method | Path | Body / result |
| --- | --- | --- |
| GET | `/api/health` | version pins |
| GET | `/api/blocks?q=` | placeable blocks |
| GET | `/api/projects` | summaries |
| POST | `/api/projects` | `{name,width,depth,seed,spawn:{x,z}}` |
| POST | `/api/projects/import-example` | copies Coastal Vale |
| GET | `/api/projects/{id}` | full project |
| DELETE | `/api/projects/{id}` | delete |
| POST | `/api/projects/{id}/operations` | `{operations:[...]}` |
| POST | `/api/projects/{id}/assets` | multipart `file` + `caption` |
| GET | `/api/projects/{id}/assets/{assetId}` | image |
| GET | `/api/projects/{id}/assets/{assetId}/thumb` | PNG thumbnail |
| POST | `/api/projects/{id}/jobs` | `{type:"generate",scope}` or `{type:"export"}` |
| GET | `/api/projects/{id}/jobs/{jobId}` | `{status,progress,message,error,result}` |
| GET | `/api/projects/{id}/generation` | `cache/last_generate.json` or `{generated:false}` |
| GET | `/api/projects/{id}/preview?mode=topdown\|isometric` | PNG, 409 if not generated |
| GET | `/api/projects/{id}/mesh` | `cache/mesh.json`, 409 if missing |
| GET | `/api/projects/{id}/columns/{x}/{z}` | sampler |
| GET | `/api/projects/{id}/export/download` | zip from `cache/last_export.json` |
| GET | `/api/agents` | discovery |
| POST | `/api/agent-sessions` | `{agentId,projectId,permissionMode}` |
| GET | `/api/agent-sessions/{sid}` | snapshot |
| POST | `/api/agent-sessions/{sid}/prompt` | `{text,includeImages}` |
| POST | `/api/agent-sessions/{sid}/cancel` | |
| POST | `/api/agent-sessions/{sid}/permissions/{reqId}` | `{outcome:"allow"\|"deny"}` |
| DELETE | `/api/agent-sessions/{sid}` | |

Validation errors are HTTP 422: `{"ok":false,"errors":[{"index":0,"code":"...","message":"...","path":"..."}]}`.

## Operations

`world.set_meta` args may include `name`, `seed`, `width`, `depth`, `seaLevel`, `blendRadius`, `spawn` (`x`,`y`,`z`), and `border` warning fields. `border.size` must stay `max(width, depth)` and the center stays `0,0`. Resizing fails if a region or the spawn would leave the rectangle.

`region.create` requires `name`, `color` (`#RRGGBB`), and `shape` `{x,z,width,depth}`. Optional `id`, `vanillaBiome`, `brief`, `palette`, `terrain`, `features`. Omitted profile fields copy `defaultTerrain`. `surface`, `subsurface`, `stone`, and `water` are added to `allowed` if missing.

`region.update` requires `id` and any of those fields. `brief`, `palette`, `terrain`, and `features.trees` merge.

`region.move` requires `id`, `x`, `z` (new minimum corner).

`region.delete` and `asset.delete` require `id`.

## Rules

- World width and depth are multiples of 16, from 32 to 512. The painted rectangle is `[-width/2, width/2)` by `[-depth/2, depth/2)`.
- The world border is the square of side `max(width, depth)` centered at the origin. Generation fills that whole square. Columns outside the painted rectangle use `defaultTerrain`.
- Regions are at least 4×4 and must lie inside the painted rectangle. Overlaps are allowed; the later region wins the interior.
- Spawn `x,z` must lie in the painted rectangle. Seed is an integer from 0 through `2^53-1`.
- Placeable blocks come from `schema/blocks.json`. Structural blocks (`surface`, `subsurface`, `stone`) must be solid and in `allowed`. Tree and vegetation kinds require their blocks in `allowed`.
- Vanilla biome ids are only the allow-list in `mcmap.model.VANILLA_BIOMES`. They tint chunks. They are not new biome registrations.
- Brief text and images do not change `generation_fingerprint`.
- Block property maps in `schema/blocks.json` are the properties the exporter writes.
