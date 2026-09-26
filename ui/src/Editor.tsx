import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "./api";
import { AgentPanel } from "./AgentPanel";
import { Inspector } from "./Inspector";
import { MapCanvas } from "./MapCanvas";
import { Preview3D } from "./Preview3D";
import {
  allowedForDraft,
  errorMessage,
  nextRegionColor,
  nextRegionName,
  parseInteger,
  parseNumber,
  textList,
  validationSummary,
} from "./plan";
import type { BlockInfo, Job, Project, RegionDraft, Shape, Tool } from "./types";

interface EditorProps {
  project: Project;
  blocks: BlockInfo[];
  onProject: (project: Project) => void;
  onBack: () => void;
}

export function Editor({ project, blocks, onProject, onBack }: EditorProps) {
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState("Saved");
  const [tool, setTool] = useState<Tool>("draw");
  const [selectedId, setSelectedId] = useState<string | null>(project.regions[0]?.id ?? null);
  const [formVersion, setFormVersion] = useState(0);
  const [exactX, setExactX] = useState("");
  const [exactZ, setExactZ] = useState("");
  const [exactWidth, setExactWidth] = useState("");
  const [exactDepth, setExactDepth] = useState("");
  const [moveX, setMoveX] = useState("");
  const [moveZ, setMoveZ] = useState("");
  const [generateStatus, setGenerateStatus] = useState("Not generated yet");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [previewsReady, setPreviewsReady] = useState(false);
  const [previewToken, setPreviewToken] = useState(0);
  const [shownFingerprint, setShownFingerprint] = useState<string | null>(null);
  const [mesh, setMesh] = useState<Awaited<ReturnType<typeof api.mesh>>>(null);
  const [meshNote, setMeshNote] = useState("Generate the map to raise the relief.");
  const [exportJob, setExportJob] = useState<Job | null>(null);
  const [exportView, setExportView] = useState<{ worldDir: string; summary: string } | null>(null);
  const busy = useRef(false);
  const mounted = useRef(true);
  const generateWatch = useRef(0);
  const exportWatch = useRef(0);
  const generateTimer = useRef<number | null>(null);
  const exportTimer = useRef<number | null>(null);
  const generationEpoch = useRef(0);

  const selected = project.regions.find((region) => region.id === selectedId) ?? null;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (generateTimer.current !== null) window.clearTimeout(generateTimer.current);
      if (exportTimer.current !== null) window.clearTimeout(exportTimer.current);
    };
  }, []);

  const selectedOriginX = selected?.shape.x;
  const selectedOriginZ = selected?.shape.z;
  useEffect(() => {
    if (!selectedId || selectedOriginX === undefined || selectedOriginZ === undefined) return;
    setMoveX(String(selectedOriginX));
    setMoveZ(String(selectedOriginZ));
  }, [selectedId, selectedOriginX, selectedOriginZ]);

  useEffect(() => {
    let cancel = false;
    const epoch = generationEpoch.current;
    void (async () => {
      try {
        const generation = await api.generation(project.id);
        if (cancel || epoch !== generationEpoch.current) return;
        if (!generation.generated) {
          setPreviewsReady(false);
          setShownFingerprint(null);
          setMesh(null);
          setWarnings([]);
          setGenerateStatus(generation.stale ? "Out of date" : "Not generated yet");
          setMeshNote(
            generation.stale
              ? "Terrain is out of date. Generate again to refresh the preview."
              : "Generate the map to raise the relief.",
          );
          return;
        }
        setWarnings(textList(generation.warnings));
        setGenerateStatus("Finished");
        setPreviewsReady(true);
        setShownFingerprint(project.generationFingerprint ?? null);
        setPreviewToken((token) => token + 1);
        const meshData = await api.mesh(project.id);
        if (cancel || epoch !== generationEpoch.current) return;
        setMesh(meshData);
        setMeshNote(meshData ? "" : "The height mesh is not available yet.");
      } catch (caught) {
        if (cancel) return;
        const message = errorMessage(caught);
        setError(message);
        setSaveStatus(message);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [project.id, project.generationFingerprint]);

  function fail(message: string) {
    setError(message);
    setSaveStatus(message);
  }

  async function run(action: () => Promise<void>): Promise<boolean> {
    if (busy.current) return false;
    busy.current = true;
    try {
      await action();
      setSaveStatus("Saved");
      setError(null);
      return true;
    } catch (caught) {
      fail(errorMessage(caught));
      return false;
    } finally {
      busy.current = false;
    }
  }

  async function createShape(shape: Shape) {
    await run(async () => {
      const body = await api.operate(project.id, [
        {
          op: "region.create",
          args: {
            name: nextRegionName(project.regions),
            color: nextRegionColor(project.regions),
            shape,
          },
        },
      ]);
      onProject(body.project);
      const created = body.results.find((result) => result.regionId)?.regionId;
      if (created) setSelectedId(created);
      setFormVersion((version) => version + 1);
    });
  }

  async function moveRegion(regionId: string, x: number, z: number) {
    await run(async () => {
      const body = await api.operate(project.id, [{ op: "region.move", args: { id: regionId, x, z } }]);
      onProject(body.project);
    });
  }

  async function applyRegion(draft: RegionDraft) {
    const region = project.regions.find((item) => item.id === selectedId);
    if (!region) {
      fail("Select a region to apply.");
      return;
    }
    const name = draft.name.trim();
    if (name.length < 1 || name.length > 48) {
      fail("Region name must be 1 to 48 characters.");
      return;
    }
    if (!/^#[0-9A-Fa-f]{6}$/.test(draft.color)) {
      fail("Region color must be #RRGGBB.");
      return;
    }
    const baseHeight = parseInteger(draft.baseHeight);
    const amplitude = parseInteger(draft.amplitude);
    const roughness = parseNumber(draft.roughness);
    const density = parseNumber(draft.density);
    if (baseHeight === null || baseHeight < 8 || baseHeight > 180) {
      fail("Base height must be an integer from 8 to 180.");
      return;
    }
    if (amplitude === null || amplitude < 0 || amplitude > 48) {
      fail("Amplitude must be an integer from 0 to 48.");
      return;
    }
    if (roughness === null || roughness < 0 || roughness > 1) {
      fail("Roughness must be a number from 0 to 1.");
      return;
    }
    if (density === null || density < 0 || density > 1) {
      fail("Tree density must be a number from 0 to 1.");
      return;
    }
    await run(async () => {
      const body = await api.operate(project.id, [
        {
          op: "region.update",
          args: {
            id: region.id,
            name,
            color: draft.color,
            vanillaBiome: draft.biome,
            brief: { text: draft.text, assetIds: draft.assetIds },
            palette: {
              surface: draft.surface,
              subsurface: draft.subsurface,
              stone: draft.stone,
              allowed: allowedForDraft(region, draft),
            },
            terrain: { baseHeight, amplitude, roughness, water: draft.water },
            features: {
              trees: { kind: draft.trees, density },
              vegetation: draft.vegetation,
              ores: draft.ores,
              caves: draft.caves,
            },
          },
        },
      ]);
      onProject(body.project);
      setFormVersion((version) => version + 1);
    });
  }

  async function uploadImage(file: File, draft: RegionDraft): Promise<string | null> {
    const regionId = selectedId;
    if (!regionId) {
      fail("Select a region before attaching a reference image.");
      return null;
    }
    let savedAssetId: string | null = null;
    const ok = await run(async () => {
      const uploaded = await api.uploadAsset(project.id, file, file.name.slice(0, 200));
      const nextAssetId = uploaded.asset.id;
      savedAssetId = nextAssetId;
      const body = await api.operate(project.id, [
        {
          op: "region.update",
          args: {
            id: regionId,
            brief: { text: draft.text, assetIds: [...new Set([...draft.assetIds, nextAssetId])] },
          },
        },
      ]);
      onProject(body.project);
    });
    return ok ? savedAssetId : null;
  }

  async function removeRegion(regionId: string) {
    await run(async () => {
      const body = await api.operate(project.id, [{ op: "region.delete", args: { id: regionId } }]);
      onProject(body.project);
      setSelectedId((current) => (current === regionId ? null : current));
      setFormVersion((version) => version + 1);
    });
  }

  function addExact(event: FormEvent) {
    event.preventDefault();
    const x = parseInteger(exactX);
    const z = parseInteger(exactZ);
    const width = parseInteger(exactWidth);
    const depth = parseInteger(exactDepth);
    if (x === null || z === null || width === null || depth === null) {
      fail("Enter integer x, z, width, and depth.");
      return;
    }
    if (width < 4 || depth < 4) {
      fail("Regions must be at least 4 blocks on each side.");
      return;
    }
    void createShape({ x, z, width, depth });
  }

  function applyMove(event: FormEvent) {
    event.preventDefault();
    if (!selected) {
      fail("Select a region to move.");
      return;
    }
    const x = parseInteger(moveX);
    const z = parseInteger(moveZ);
    if (x === null || z === null) {
      fail("Enter integer x and z.");
      return;
    }
    void moveRegion(selected.id, x, z);
  }

  function watchJob(kind: "generate" | "export", jobId: string) {
    const token = kind === "generate" ? ++generateWatch.current : ++exportWatch.current;
    const timerRef = kind === "generate" ? generateTimer : exportTimer;
    const poll = async () => {
      const current = kind === "generate" ? generateWatch.current : exportWatch.current;
      if (!mounted.current || current !== token) return;
      try {
        const body = await api.job(project.id, jobId);
        if (!mounted.current || current !== token) return;
        if (kind === "generate") {
          const job = body.job;
          setGenerateStatus(job.status === "error" ? job.error || job.message : job.message || "Running");
          if (job.status === "running") {
            timerRef.current = window.setTimeout(() => void poll(), 500);
            return;
          }
          await finishGenerate(job);
          return;
        }
        setExportJob(body.job);
        if (body.job.status === "running") {
          timerRef.current = window.setTimeout(() => void poll(), 500);
          return;
        }
        finishExport(body.job);
      } catch (caught) {
        if (mounted.current) fail(errorMessage(caught));
      }
    };
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => void poll(), 500);
  }

  async function finishGenerate(job: Job) {
    if (job.status === "error") {
      fail(job.error || job.message || "Generate failed.");
      return;
    }
    generationEpoch.current += 1;
    setGenerateStatus(job.message || "Finished");
    setWarnings(textList(job.result?.warnings));
    setError(null);
    setSaveStatus("Saved");
    try {
      const [fresh, meshData] = await Promise.all([api.getProject(project.id), api.mesh(project.id)]);
      if (!mounted.current) return;
      onProject(fresh.project);
      setShownFingerprint(fresh.project.generationFingerprint ?? null);
      setPreviewsReady(true);
      setPreviewToken((token) => token + 1);
      setMesh(meshData);
      setMeshNote(meshData ? "" : "The height mesh is not available yet.");
    } catch (caught) {
      if (mounted.current) fail(errorMessage(caught));
    }
  }

  function finishExport(job: Job) {
    if (job.status === "error") {
      fail(job.error || job.message || "Export failed.");
      return;
    }
    setExportView({
      worldDir: job.result?.worldDir ?? "",
      summary: validationSummary(job.result?.validation),
    });
    setError(null);
    setSaveStatus("Saved");
    void api
      .getProject(project.id)
      .then((body) => {
        if (mounted.current) onProject(body.project);
      })
      .catch((caught) => {
        if (mounted.current) fail(errorMessage(caught));
      });
  }

  async function generateAll() {
    setWarnings([]);
    setGenerateStatus("Running");
    try {
      const started = await api.startJob(project.id, { type: "generate", scope: { kind: "all" } });
      setGenerateStatus(started.job.message || "Running");
      watchJob("generate", started.job.id);
    } catch (caught) {
      const message = errorMessage(caught);
      setGenerateStatus(message);
      fail(message);
    }
  }

  async function exportWorld() {
    setExportJob(null);
    try {
      const started = await api.startJob(project.id, { type: "export" });
      setExportJob(started.job);
      watchJob("export", started.job.id);
    } catch (caught) {
      const message = errorMessage(caught);
      setExportJob({
        id: "",
        projectId: project.id,
        type: "export",
        status: "error",
        progress: 0,
        message,
        error: message,
        result: null,
      });
      fail(message);
    }
  }

  async function refreshFromAgent() {
    const body = await api.getProject(project.id);
    if (!mounted.current) return;
    onProject(body.project);
    setFormVersion((version) => version + 1);
    setSaveStatus("Saved");
    setError(null);
  }

  const previewsVisible =
    previewsReady && shownFingerprint !== null && shownFingerprint === (project.generationFingerprint ?? null);
  const outOfDate = shownFingerprint !== null && shownFingerprint !== (project.generationFingerprint ?? null);
  const visibleMesh = previewsVisible ? mesh : null;
  const previewSrc = (mode: "topdown" | "isometric") =>
    `/api/projects/${project.id}/preview?mode=${mode}&v=${previewToken}`;

  return (
    <div>
      <div className="editor-bar">
        <button type="button" data-testid="back-home" onClick={onBack}>
          All maps
        </button>
        <h1 data-testid="project-title">{project.name}</h1>
        <span className="save-status" data-testid="save-status">
          {saveStatus}
        </span>
      </div>
      {error ? (
        <p className="alert" data-testid="error-banner" role="alert">
          {error}
        </p>
      ) : null}
      <div className="editor-grid">
        <aside className="panel column-list">
          <h2>Index</h2>
          <dl className="facts">
            <dt>World</dt>
            <dd>
              {project.world.width}×{project.world.depth}
            </dd>
            <dt>Border</dt>
            <dd>{project.world.border.size}</dd>
            <dt>Seed</dt>
            <dd>{project.world.seed}</dd>
            <dt>Spawn</dt>
            <dd>
              {project.world.spawn.x}, {project.world.spawn.z}
            </dd>
          </dl>
          <div className="tool-row" role="group" aria-label="Map tools">
            <button type="button" data-testid="tool-draw" aria-pressed={tool === "draw"} onClick={() => setTool("draw")}>
              Draw
            </button>
            <button type="button" data-testid="tool-move" aria-pressed={tool === "move"} onClick={() => setTool("move")}>
              Move
            </button>
            <button type="button" data-testid="tool-select" aria-pressed={tool === "select"} onClick={() => setTool("select")}>
              Select
            </button>
          </div>
          <h3>Place by numbers</h3>
          <form onSubmit={addExact}>
            <div className="fields">
              <label>
                X
                <input data-testid="exact-x" type="number" step={1} value={exactX} onChange={(event) => setExactX(event.target.value)} />
              </label>
              <label>
                Z
                <input data-testid="exact-z" type="number" step={1} value={exactZ} onChange={(event) => setExactZ(event.target.value)} />
              </label>
              <label>
                Width
                <input
                  data-testid="exact-width"
                  type="number"
                  step={1}
                  value={exactWidth}
                  onChange={(event) => setExactWidth(event.target.value)}
                />
              </label>
              <label>
                Depth
                <input
                  data-testid="exact-depth"
                  type="number"
                  step={1}
                  value={exactDepth}
                  onChange={(event) => setExactDepth(event.target.value)}
                />
              </label>
            </div>
            <div className="actions">
              <button type="submit" data-testid="add-region-exact">
                Add region
              </button>
            </div>
          </form>
          <h3>Move selected</h3>
          <form onSubmit={applyMove}>
            <div className="fields">
              <label>
                X
                <input data-testid="move-x" type="number" step={1} value={moveX} onChange={(event) => setMoveX(event.target.value)} />
              </label>
              <label>
                Z
                <input data-testid="move-z" type="number" step={1} value={moveZ} onChange={(event) => setMoveZ(event.target.value)} />
              </label>
            </div>
            <div className="actions">
              <button type="submit" data-testid="apply-move">
                Move region
              </button>
            </div>
          </form>
          <h3>Regions</h3>
          <p className="note">Later regions cover earlier ones where they overlap.</p>
          <ul className="region-list" data-testid="region-list">
            {project.regions.length === 0 ? <li className="note">No regions yet.</li> : null}
            {project.regions.map((region) => (
              <li key={region.id}>
                <button
                  type="button"
                  className="region-item"
                  data-testid="region-item"
                  data-region-id={region.id}
                  aria-pressed={region.id === selectedId}
                  onClick={() => setSelectedId(region.id)}
                >
                  <span className="swatch" style={{ background: region.color }} />
                  {region.name}
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <section className="panel column-map">
          <h2>Sheet</h2>
          <MapCanvas
            project={project}
            selectedId={selectedId}
            tool={tool}
            onSelect={setSelectedId}
            onCreate={(shape) => void createShape(shape)}
            onMove={(regionId, x, z) => void moveRegion(regionId, x, z)}
            onReject={fail}
          />
          <div className="actions">
            <button type="button" className="primary" data-testid="generate-all" onClick={() => void generateAll()}>
              Generate terrain
            </button>
            <button type="button" data-testid="export-world" onClick={() => void exportWorld()}>
              Export world
            </button>
          </div>
          <p data-testid="generate-status">{outOfDate ? "Out of date" : generateStatus}</p>
          <ul data-testid="generate-warnings" className="warnings">
            {warnings.map((warning, index) => (
              <li key={`${warning}-${index}`}>{warning}</li>
            ))}
          </ul>
          <div className="preview-row">
            <figure>
              <img
                data-testid="preview-topdown"
                alt="Top-down preview"
                {...(previewsVisible ? { src: previewSrc("topdown") } : {})}
              />
              <figcaption className="note">Top down</figcaption>
            </figure>
            <figure>
              <img
                data-testid="preview-isometric"
                alt="Isometric preview"
                {...(previewsVisible ? { src: previewSrc("isometric") } : {})}
              />
              <figcaption className="note">Isometric</figcaption>
            </figure>
          </div>
          <Preview3D
            mesh={visibleMesh}
            blocks={blocks}
            note={
              outOfDate ? "Terrain is out of date. Generate again to refresh the preview." : meshNote
            }
          />
          <div data-testid="export-result">
            {exportJob?.status === "running" ? <p>{exportJob.message || "Running"}</p> : null}
            {exportJob?.status === "error" ? <p>{exportJob.error || exportJob.message}</p> : null}
            {exportView ? (
              <>
                <p className="export-path">World folder: {exportView.worldDir}</p>
                <p>{exportView.summary}</p>
                <a data-testid="export-download" href={`/api/projects/${project.id}/export/download`}>
                  Download world
                </a>
              </>
            ) : (
              <p>No export yet.</p>
            )}
          </div>
        </section>
        <aside className="column-inspector">
          <Inspector
            key={`${selected?.id ?? "none"}:${formVersion}`}
            project={project}
            region={selected}
            blocks={blocks}
            onApply={(draft) => void applyRegion(draft)}
            onUpload={uploadImage}
            onDelete={(regionId) => void removeRegion(regionId)}
          />
          <AgentPanel projectId={project.id} onProjectChanged={refreshFromAgent} onError={fail} />
        </aside>
      </div>
    </div>
  );
}
