import { useEffect, useState } from "react";
import { api } from "./api";
import { Editor } from "./Editor";
import { Home } from "./Home";
import { errorMessage } from "./plan";
import type { BlockInfo, Health, Project, ProjectSummary } from "./types";

function projectQuery(): string | null {
  const id = new URLSearchParams(window.location.search).get("project");
  return id || null;
}

function writeProjectQuery(projectId: string | null, mode: "push" | "replace") {
  const url = new URL(window.location.href);
  if (projectId) url.searchParams.set("project", projectId);
  else url.searchParams.delete("project");
  const next = `${url.pathname}${url.search}`;
  if (mode === "push") window.history.pushState({ project: projectId }, "", next);
  else window.history.replaceState({ project: projectId }, "", next);
}

export function App() {
  const [ready, setReady] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [blocks, setBlocks] = useState<BlockInfo[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [homeError, setHomeError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refreshList() {
    const listed = await api.listProjects();
    setProjects(listed.projects);
  }

  useEffect(() => {
    let cancel = false;
    const boot = async () => {
      for (;;) {
        if (cancel) return;
        try {
          const pulse = await api.health();
          if (cancel) return;
          setHealth(pulse);
          try {
            const [listed, catalog] = await Promise.all([api.listProjects(), api.blocks()]);
            if (cancel) return;
            setProjects(listed.projects);
            setBlocks(catalog.blocks);
          } catch (caught) {
            if (!cancel) setHomeError(errorMessage(caught));
          }
          const id = projectQuery();
          if (id) {
            try {
              const body = await api.getProject(id);
              if (!cancel) setProject(body.project);
            } catch (caught) {
              if (!cancel) setHomeError(errorMessage(caught));
            }
          }
          if (!cancel) setReady(true);
          return;
        } catch {
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
      }
    };
    void boot();
    return () => {
      cancel = true;
    };
  }, []);

  useEffect(() => {
    const onPop = () => {
      const id = projectQuery();
      if (!id) {
        setProject(null);
        void refreshList().catch((caught) => setHomeError(errorMessage(caught)));
        return;
      }
      void api
        .getProject(id)
        .then((body) => {
          setProject(body.project);
          setHomeError(null);
        })
        .catch((caught) => {
          setProject(null);
          setHomeError(errorMessage(caught));
        });
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  async function openProject(id: string) {
    setBusy(true);
    try {
      const body = await api.getProject(id);
      setProject(body.project);
      setHomeError(null);
      writeProjectQuery(id, "push");
    } catch (caught) {
      setHomeError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function createProject(body: {
    name: string;
    width: number;
    depth: number;
    seed: number;
    spawn: { x: number; z: number };
  }) {
    setBusy(true);
    try {
      const created = await api.createProject(body);
      setProject(created.project);
      setHomeError(null);
      writeProjectQuery(created.project.id, "push");
      await refreshList();
    } catch (caught) {
      setHomeError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function openExample() {
    setBusy(true);
    try {
      const imported = await api.importExample();
      setProject(imported.project);
      setHomeError(null);
      writeProjectQuery(imported.project.id, "push");
      await refreshList();
    } catch (caught) {
      setHomeError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function backHome() {
    setProject(null);
    writeProjectQuery(null, "push");
    void refreshList().catch((caught) => setHomeError(errorMessage(caught)));
  }

  return (
    <div className="desk" data-testid={ready ? "app-ready" : undefined}>
      <header className="masthead">
        <svg className="compass" viewBox="0 0 64 64" aria-hidden="true">
          <circle cx="32" cy="32" r="28" fill="none" stroke="#d4a017" strokeWidth="2" />
          <path d="M32 8 L37 32 L32 27 L27 32 Z" fill="#d4a017" />
          <path d="M32 56 L27 32 L32 37 L37 32 Z" fill="#c4523a" />
          <path d="M8 32 L32 27 L27 32 L32 37 Z" fill="#8a7350" />
          <path d="M56 32 L32 37 L37 32 L32 27 Z" fill="#8a7350" />
        </svg>
        <div>
          <p className="brand">Map Studio</p>
          <p className="edition">{health ? `Minecraft Java ${health.minecraftVersion}` : "Checking the map service…"}</p>
        </div>
      </header>
      {!ready ? <p className="boot">The desk is waiting for the local map service.</p> : null}
      {ready && project ? (
        <Editor key={project.id} project={project} blocks={blocks} onProject={setProject} onBack={backHome} />
      ) : null}
      {ready && !project ? (
        <Home
          projects={projects}
          error={homeError}
          busy={busy}
          onCreate={(body) => void createProject(body)}
          onExample={() => void openExample()}
          onOpen={(id) => void openProject(id)}
        />
      ) : null}
    </div>
  );
}
