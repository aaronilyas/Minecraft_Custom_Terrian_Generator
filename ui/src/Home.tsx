import { useMemo, useState, type FormEvent } from "react";
import type { ProjectSummary } from "./types";
import { createProjectError, parseInteger } from "./plan";

interface HomeProps {
  projects: ProjectSummary[];
  error: string | null;
  busy: boolean;
  onCreate: (body: { name: string; width: number; depth: number; seed: number; spawn: { x: number; z: number } }) => void;
  onExample: () => void;
  onOpen: (projectId: string) => void;
}

export function Home({ projects, error, busy, onCreate, onExample, onOpen }: HomeProps) {
  const [name, setName] = useState("");
  const [width, setWidth] = useState("128");
  const [depth, setDepth] = useState("128");
  const [seed, setSeed] = useState("12091");
  const [spawnX, setSpawnX] = useState("0");
  const [spawnZ, setSpawnZ] = useState("0");
  const [localError, setLocalError] = useState<string | null>(null);

  const borderSize = useMemo(() => {
    const w = parseInteger(width);
    const d = parseInteger(depth);
    if (w === null || d === null) return null;
    return Math.max(w, d);
  }, [width, depth]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const message = createProjectError({ name, width, depth, seed, spawnX, spawnZ });
    if (message) {
      setLocalError(message);
      return;
    }
    setLocalError(null);
    onCreate({
      name: name.trim(),
      width: Number(width),
      depth: Number(depth),
      seed: Number(seed),
      spawn: { x: Number(spawnX), z: Number(spawnZ) },
    });
  }

  const shown = localError || error;

  return (
    <section data-testid="home" className="home-layout">
      <form className="panel" onSubmit={submit} noValidate autoComplete="off">
        <h2>New chart</h2>
        <p className="lede">Lay out a finite survival world, then paint the regions on the sheet.</p>
        {shown ? (
          <p className="alert" role="alert">
            {shown}
          </p>
        ) : null}
        <div className="fields">
          <label className="wide">
            Name
            <input
              id="project-name"
              data-testid="project-name"
              value={name}
              maxLength={60}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Width
            <input
              id="world-width"
              data-testid="world-width"
              type="number"
              min={32}
              max={512}
              step={16}
              value={width}
              onChange={(event) => setWidth(event.target.value)}
            />
          </label>
          <label>
            Depth
            <input
              id="world-depth"
              data-testid="world-depth"
              type="number"
              min={32}
              max={512}
              step={16}
              value={depth}
              onChange={(event) => setDepth(event.target.value)}
            />
          </label>
          <label>
            Seed
            <input
              id="world-seed"
              data-testid="world-seed"
              type="number"
              min={0}
              step={1}
              value={seed}
              onChange={(event) => setSeed(event.target.value)}
            />
          </label>
          <label>
            Spawn X
            <input
              id="spawn-x"
              data-testid="spawn-x"
              type="number"
              step={1}
              value={spawnX}
              onChange={(event) => setSpawnX(event.target.value)}
            />
          </label>
          <label>
            Spawn Z
            <input
              id="spawn-z"
              data-testid="spawn-z"
              type="number"
              step={1}
              value={spawnZ}
              onChange={(event) => setSpawnZ(event.target.value)}
            />
          </label>
        </div>
        <p className="helper">The border is the square of the larger side, and both sides must be multiples of 16.</p>
        <p className="note">Border square: {borderSize ?? "—"} blocks. Spawn starts at 0, 0.</p>
        <div className="actions">
          <button className="primary" type="submit" data-testid="submit-project" disabled={busy}>
            Create map
          </button>
        </div>
      </form>
      <section className="panel">
        <h2>Saved maps</h2>
        <button type="button" data-testid="open-example" onClick={onExample} disabled={busy}>
          Open Coastal Vale
        </button>
        <ul className="ledger" data-testid="project-list">
          {projects.length === 0 ? <li><p>No saved maps yet.</p></li> : null}
          {projects.map((project) => (
            <li key={project.id}>
              <div>
                <p>{project.name}</p>
                <p className="meta">
                  {project.width}×{project.depth} · seed {project.seed} · {project.regionCount} regions
                </p>
              </div>
              <button
                type="button"
                data-testid="open-project"
                data-project-id={project.id}
                onClick={() => onOpen(project.id)}
                disabled={busy}
              >
                Open
              </button>
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}
