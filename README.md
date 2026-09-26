# Minecraft Map Studio

A local app for painting finite Minecraft Java survival maps. You set the world size, seed, and spawn, draw custom regions, attach reference images and short briefs, choose real Minecraft blocks, then generate a reproducible terrain and export a Java Edition 1.21.4 world.

Custom regions are map areas with their own shape, materials, and scenery. The exporter does not register new biome ids. It uses a small set of existing vanilla biomes for tint only.

## Run

Requirements: Python 3.12, Node 20+, and Java 21 or newer (already used to read the exported world; the game itself is optional).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install --prefix ui
npm run dev
```

Open http://127.0.0.1:5173. The API listens on http://127.0.0.1:8765. Projects are stored in `data/projects/`.

```bash
.venv/bin/pytest -q
```

## Agents

The agent panel speaks the Agent Client Protocol over stdio.

- Grok Build, when `grok` is on `PATH`: `grok agent --no-leader stdio`
- Codex, only after you opt in through `data/agents.json`
- A bundled test agent that needs no account

Agents change the map by running `python -m mcmap.cli`. The command rejects unknown blocks and edits outside the world. See `docs/OPERATIONS.md`.

## World version

Exports target Minecraft Java **1.21.4** (data version 4189): a world folder plus a zip with `level.dat`, a square world border, survival mode, and Anvil chunks. Copy the unzipped folder into Minecraft's `saves` directory.

## Layout

- `ui/` map editor
- `server/mcmap/` project store, operations, generator, exporter, ACP client
- `examples/coastal-vale/` a small example with an original painted reference
- `docs/` contracts for the format, generator, UI, and ACP client
