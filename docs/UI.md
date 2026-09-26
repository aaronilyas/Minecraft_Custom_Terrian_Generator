# UI contract

Build a Vite + React + TypeScript app in `ui/`. The dev server is `127.0.0.1:5173` and proxies `/api` to `http://127.0.0.1:8765`. Do not start that server; the lead will. `npm run build` must succeed.

Visual direction: a cartographer's desk. Background `#1c1915`, panels `#2a241c`, text `#f3ead7`, brass `#d4a017`, map paper `#cbb892`, danger `#c4523a`. Titles use Palatino, Iowan Old Style, or Georgia. Controls use system-ui. No purple gradient and no generic card grid.

## Screens

Home (`data-testid=home`):

- Create form: `project-name`, `world-width`, `world-depth`, `world-seed`, `spawn-x`, `spawn-z`, submit `submit-project`. Defaults 128, 128, a seed, spawn 0,0. Helper text says the border is the square of the larger side and both sides must be multiples of 16.
- `open-example` calls `POST /api/projects/import-example`.
- `project-list` lists saved projects. Each open control is `open-project` with `data-project-id`.

Editor:

- `project-title`, `back-home`, `save-status` (`Saved` or the error text), `error-banner` when the last request failed.
- `map-canvas` is a canvas with `data-min-x`, `data-min-z`, and `data-size` for the border square. Paper background, 16-block grid, region rectangles in their colors with names, and a brass border. `coord-readout` shows `x, z` under the pointer using block coordinates. North (`-Z`) is up.
- Tools `tool-draw`, `tool-move`, `tool-select`. Draw drags a rectangle and on mouseup calls `region.create` (minimum 4 blocks). Select loads the inspector. Move drags the selected region and calls `region.move`.
- Exact fallback so automation is not pixel-dependent: `exact-x`, `exact-z`, `exact-width`, `exact-depth`, button `add-region-exact`. Move fields `move-x`, `move-z`, button `apply-move`.
- `region-list` buttons `region-item` with `data-region-id`.
- Inspector: `region-name`, `region-color`, `brief-text`, file input `brief-image`, thumbnail `brief-thumb`, `palette-surface`, `palette-subsurface`, `palette-stone`, `terrain-base`, `terrain-amplitude`, `terrain-roughness`, `terrain-water`, `feature-trees`, `feature-vegetation`, `feature-ores`, `feature-caves`, `vanilla-biome`. `apply-region` sends `region.update`. Palette `<select>` options come from `GET /api/blocks`. Show the asset thumbnail from the thumb URL.
- `generate-all` posts a generate job and polls every 500ms. `generate-status` shows the job message or error. Warnings from the result render in `generate-warnings`.
- Previews: `preview-topdown` and `preview-isometric` images from the preview endpoint, refreshed after generation. `preview-3d` is a Three.js canvas. Load `GET /api/projects/{id}/mesh`. Build one `PlaneGeometry` (or a grid of heights) in a Y-up right-handed scene: world `x` → Three `x`, height → Three `y`, world `z` → Three `z`. Orbit the mesh. Color vertices from the block RGB catalog. `mesh-readout` shows the block coordinate nearest the pointer. Before writing this view, read `/Users/aaronilyas/.grok/bundled/skills/threejs-frame-conventions/SKILL.md`. There is no walking character; the only frame rule that applies is that the mesh axes match the top-down map (north is `-Z`) and the ground faces upward.
- Agent panel: `agent-select`, `agent-prompt`, `agent-send`, `agent-cancel`, `agent-log`, `permission-allow`, `permission-deny`. Poll the session every 500ms. Hide the permission buttons until `pendingPermission` is set. Include images on send.
- `export-world` starts an export job. `export-result` shows the world folder, validation summary, and a link `export-download` to the download URL.

Persist by calling the API. Reloading the page at `/?project=<id>` reopens that project. Do not keep a second copy of the plan that can disagree with the server.

## Layout

Desktop: list column, map, inspector column. Below 800px, stack those regions in that order and keep every control reachable. Set `data-testid=app-ready` on the root once the first health check succeeds.

## Check

`npm install` and `npm run build` in `ui/`. Do not run Vite or the Python API.
