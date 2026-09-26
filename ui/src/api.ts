import type {
  AgentInfo,
  AgentSession,
  ApiErrorItem,
  BlockInfo,
  Health,
  Job,
  MeshData,
  Project,
  ProjectSummary,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly errors: ApiErrorItem[];

  constructor(status: number, errors: ApiErrorItem[]) {
    super(errors[0]?.message || `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.errors = errors;
  }
}

function errorItems(payload: unknown, fallback: string): ApiErrorItem[] {
  if (payload && typeof payload === "object" && "errors" in payload) {
    const errors = (payload as { errors?: unknown }).errors;
    if (Array.isArray(errors) && errors.length > 0) {
      return errors.map((item) => {
        if (item && typeof item === "object" && "message" in item) {
          const row = item as ApiErrorItem;
          return { code: row.code, message: String(row.message), path: row.path };
        }
        return { message: String(item) };
      });
    }
  }
  return [{ message: fallback || "Request failed." }];
}

async function send<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  const failed =
    !response.ok ||
    (payload !== null &&
      typeof payload === "object" &&
      "ok" in payload &&
      (payload as { ok?: boolean }).ok === false);
  if (failed) {
    throw new ApiError(response.status, errorItems(payload, response.statusText));
  }
  return payload as T;
}

function projectPath(projectId: string, suffix = ""): string {
  return `/api/projects/${encodeURIComponent(projectId)}${suffix}`;
}

export interface Operation {
  op: string;
  args: Record<string, unknown>;
}

export const api = {
  health(): Promise<Health> {
    return send<Health>("/api/health");
  },

  blocks(): Promise<{ blocks: BlockInfo[] }> {
    return send("/api/blocks");
  },

  listProjects(): Promise<{ projects: ProjectSummary[] }> {
    return send("/api/projects");
  },

  createProject(body: {
    name: string;
    width: number;
    depth: number;
    seed: number;
    spawn: { x: number; z: number };
  }): Promise<{ project: Project }> {
    return send("/api/projects", { method: "POST", body: JSON.stringify(body) });
  },

  importExample(): Promise<{ project: Project }> {
    return send("/api/projects/import-example", { method: "POST" });
  },

  getProject(projectId: string): Promise<{ project: Project }> {
    return send(projectPath(projectId));
  },

  operate(
    projectId: string,
    operations: Operation[],
  ): Promise<{ project: Project; results: { op: string; regionId?: string }[] }> {
    return send(projectPath(projectId, "/operations"), {
      method: "POST",
      body: JSON.stringify({ operations }),
    });
  },

  async uploadAsset(
    projectId: string,
    file: File,
    caption: string,
  ): Promise<{ asset: { id: string }; thumbnailUrl: string }> {
    const body = new FormData();
    body.append("file", file);
    body.append("caption", caption);
    return send(projectPath(projectId, "/assets"), { method: "POST", body });
  },

  startJob(
    projectId: string,
    body: { type: "generate"; scope: { kind: "all" } } | { type: "export" },
  ): Promise<{ job: Job }> {
    return send(projectPath(projectId, "/jobs"), { method: "POST", body: JSON.stringify(body) });
  },

  job(projectId: string, jobId: string): Promise<{ job: Job }> {
    return send(projectPath(projectId, `/jobs/${encodeURIComponent(jobId)}`));
  },

  cancelJob(projectId: string, jobId: string): Promise<{ job: Job }> {
    return send(projectPath(projectId, `/jobs/${encodeURIComponent(jobId)}/cancel`), { method: "POST" });
  },

  generation(projectId: string): Promise<{ generated?: boolean; stale?: boolean; warnings?: unknown }> {
    return send(projectPath(projectId, "/generation"));
  },

  exportStatus(projectId: string): Promise<{
    export: { worldDir?: string; validation?: unknown } | null;
  }> {
    return send(projectPath(projectId, "/export"));
  },

  async mesh(projectId: string): Promise<MeshData | null> {
    try {
      return await send<MeshData>(projectPath(projectId, "/mesh"));
    } catch (error) {
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) return null;
      throw error;
    }
  },

  agents(): Promise<{ agents: AgentInfo[] }> {
    return send("/api/agents");
  },

  startSession(body: {
    agentId: string;
    projectId: string;
    permissionMode: string;
  }): Promise<{ session: AgentSession }> {
    return send("/api/agent-sessions", { method: "POST", body: JSON.stringify(body) });
  },

  session(sessionId: string): Promise<{ session: AgentSession }> {
    return send(`/api/agent-sessions/${encodeURIComponent(sessionId)}`);
  },

  prompt(
    sessionId: string,
    body: { text: string; includeImages: boolean },
  ): Promise<{ session: AgentSession }> {
    return send(`/api/agent-sessions/${encodeURIComponent(sessionId)}/prompt`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  cancel(sessionId: string): Promise<{ session: AgentSession }> {
    return send(`/api/agent-sessions/${encodeURIComponent(sessionId)}/cancel`, { method: "POST" });
  },

  resolvePermission(
    sessionId: string,
    requestId: string,
    outcome: "allow" | "deny",
  ): Promise<{ session: AgentSession }> {
    return send(
      `/api/agent-sessions/${encodeURIComponent(sessionId)}/permissions/${encodeURIComponent(requestId)}`,
      { method: "POST", body: JSON.stringify({ outcome }) },
    );
  },

  closeSession(sessionId: string): Promise<{ ok: boolean }> {
    return send(`/api/agent-sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  },
};
