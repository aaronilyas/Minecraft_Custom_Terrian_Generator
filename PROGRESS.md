# Progress

## Decisions

- Empty repo. One local app: Vite/React on port 5173 and a Python API on port 8765. Electron was not used because this session has collaborative browser tools and no desktop window-control API.
- Minecraft Java 1.21.4, data version 4189. Java 21 is installed. No Minecraft app or `~/Library/Application Support/minecraft` directory was found, so opening the save in the game is outstanding.
- Grok ACP probe: `grok agent --no-leader stdio` speaks NDJSON, protocol version 1, image prompts false, embedded context true, MCP http/sse only. Codex is installed, but the ACP adapter is opt-in so the app does not download it.
- Agents use disjoint directories, not git worktrees. The contract is uncommitted, and a worktree from HEAD would not contain it.
- Shared kernel (schema, store, operations, HTTP, CLI) is implemented by the lead. Generation, UI, and ACP are delegated.

## Milestone

All five slices are implemented. Automated suite is green. The UI was exercised in the collaborative browser on desktop and a phone-sized viewport.

## Evidence

- `.venv/bin/pytest -q` — 32 passed, 1 skipped (live Grok, unless `MCMAP_LIVE_ACP=1`).
- Browser, desktop 1280×800: created Harbor Trial (64×64, seed 4242, spawn 2,-2), added Meadow, edited the brief, moved it to -8,4, rejected an out-of-bounds move, reloaded `/?project=` and the brief was still there.
- Browser: opened Coastal Vale. Meadow and Dunes showed distinct palettes. The painted reference thumbnail loaded (160px). Agent list: Grok available, Codex disabled until `data/agents.json`, test agent available.
- Test agent in the UI: `text_length=27 image=1 resource_link=1`, then `NEED_PERMISSION` showed Allow/Deny and Deny produced `denied`.
- Generate on Coastal Vale: 16384 columns, spawn adjusted to -1,69,-1. Top-down and isometric previews show meadow trees, dunes, flowers, and a later pond (84 water pixels, reader samples include `minecraft:water` at y=62).
- Column -30,0 was unchanged after adding the pond region and regenerating.
- Export folder and zip `data/projects/add23914-23db-4667-aff2-3b8c4210317c/export/coastal-vale.zip`. Independent reader: ok, dataVersion 4189, 64 chunks, border 128, no errors. Zip contains `level.dat` and four region files.
- Phone viewport 390×844: editor stacks to one column, no horizontal overflow. Desktop grid after resize: `300px 509px 380px`.
- 3D canvas pixel reads were green and sand, not the clear color. WebGL screenshots from the browser tool stayed blank; `readPixels` confirmed the mesh.
- Screenshots saved by the browser tool:
  - `/Users/aaronilyas/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-muiltafq-2ce1bc6f.png`
  - `/Users/aaronilyas/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-muiltkex-337102ed.png`
  - `/Users/aaronilyas/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-muiltpst-cbf65d82.png`
- Preview images: `/tmp/mcmap-logs/topdown2.png`, `/tmp/mcmap-logs/iso.png`.

## Failures fixed during verification

- Map canvas had no CSS size (default 300×150). Added the `map-canvas` class.
- Previews colored only the heightmap, so trees and water disappeared. The visible top block is used now.
- React strict mode plus `forceContextLoss()` left the 3D canvas dead in dev. Context loss was removed and the drawing buffer is preserved.
- A restarted API left the agent panel polling a dead session. A 404 now clears that session.

## Not verified

- Minecraft is not installed, so the save was not opened in the game.
- Codex ACP adapter was not launched. It stays off until `data/agents.json` enables it, so npx does not download it.
- Live Grok ACP: `grok agent --no-leader stdio` started a session and replied `PONG` with no tool calls (about 40s). Codex was not given a live turn.

## Run

```bash
.venv/bin/pytest -q
npm run dev
```

## Evidence

- ` .venv/bin/pytest -q tests/test_ops.py tests/test_api.py` — 9 passed after the example-project test (re-run after adding it).
- Grok initialize response captured during the probe (protocol 1, NDJSON).

## Failures

- None in the kernel tests.
- Content-Length ACP framing was rejected by Grok; the client must use NDJSON.

## Next

Delegate the three owned areas, integrate, then run the browser slices.
