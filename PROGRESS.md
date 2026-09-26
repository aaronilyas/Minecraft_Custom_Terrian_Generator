# Progress

## Decisions

- One local app: Vite/React on port 5173 and a Python API on port 8765. Electron was not used because this session has collaborative browser tools and no desktop window-control API.
- Minecraft Java 1.21.4, data version 4189. Java 21 is installed. Minecraft.app is installed, but the only local game versions are 26.3 and a 26.4 snapshot, so a 1.21.4 in-game load is still outstanding.
- Grok ACP probe: `grok agent --no-leader stdio` speaks NDJSON, protocol version 1, image prompts false, embedded context true, MCP http/sse only. Codex is installed, but the ACP adapter is opt-in so the app does not download it.
- Agents use disjoint directories, not git worktrees. The contract is uncommitted, and a worktree from HEAD would not contain it.
- Shared kernel (schema, store, operations, HTTP, CLI), generator, UI, and ACP are implemented.

## Milestone

All five slices are implemented. The automated suite is green. The editor was exercised in the collaborative browser, including the stale-preview path after a region move.

## Evidence

- `.venv/bin/pytest -q` — 37 passed, 1 skipped (live Grok, unless `MCMAP_LIVE_ACP=1`).
- `npm run build` in `ui/` succeeds.
- Browser, desktop 1280×800: created Cleanup Trial (32×32), generated, kept the preview after a brief-only edit, then moved the region. Status became "Out of date", both preview images dropped their sources, and the 3D note said to generate again. Reload kept that stale state. Generating again restored the top-down image (32×32), the isometric image, and a lit terrain pixel on the canvas.
- After that move, `GET /generation` was `{generated:false, stale:true}`, and preview and mesh returned 409. After regeneration both returned 200.
- Phone viewport 390×844: the editor is one column, the generate status stays on screen, and the page does not scroll sideways.
- Stopping `npm run dev` stops both port 5173 and port 8765.

## Run

```bash
.venv/bin/pytest -q
npm run dev
```

Stopping `npm run dev` stops the API and the UI.
