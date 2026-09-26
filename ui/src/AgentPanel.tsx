import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { agentLabel, defaultAgentId, errorMessage, isAgentAvailable } from "./plan";
import type { AgentInfo, AgentSession, PendingPermission } from "./types";

interface AgentPanelProps {
  projectId: string;
  onProjectChanged: () => Promise<void>;
  onError: (message: string) => void;
}

function permissionRequestId(pending: PendingPermission | null | undefined): string {
  return pending?.requestId || pending?.id || "";
}

export function AgentPanel({ projectId, onProjectChanged, onError }: AgentPanelProps) {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [agentId, setAgentId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [session, setSession] = useState<AgentSession | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const onErrorRef = useRef(onError);
  const onProjectRef = useRef(onProjectChanged);
  onErrorRef.current = onError;
  onProjectRef.current = onProjectChanged;

  useEffect(() => {
    let cancel = false;
    void api
      .agents()
      .then((body) => {
        if (cancel) return;
        setAgents(body.agents);
        setAgentId((current) => current || defaultAgentId(body.agents));
      })
      .catch((error) => {
        if (!cancel) onErrorRef.current(errorMessage(error));
      });
    return () => {
      cancel = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!sessionId) return;
    let cancel = false;
    let previous = "";
    const tick = async () => {
      if (cancel) return;
      try {
        const body = await api.session(sessionId);
        if (cancel) return;
        setSession(body.session);
        const last = body.session.messages?.at(-1);
        const signature = [
          body.session.status,
          body.session.messages?.length ?? 0,
          last?.text ?? last?.content ?? "",
          permissionRequestId(body.session.pendingPermission),
          body.session.error ?? "",
        ].join("|");
        const settled = body.session.status !== "running" && body.session.status !== "starting";
        if (previous && previous !== signature && settled) {
          await onProjectRef.current();
        }
        previous = signature;
      } catch (error) {
        if (cancel) return;
        if (error instanceof ApiError && error.status === 404) {
          setSessionId(null);
          setSession(null);
          return;
        }
        onErrorRef.current(errorMessage(error));
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 500);
    return () => {
      cancel = true;
      window.clearInterval(timer);
    };
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const id = sessionId;
    return () => {
      void api.closeSession(id).catch(() => undefined);
    };
  }, [sessionId]);

  async function send() {
    if (!agentId) {
      onErrorRef.current("Choose an agent.");
      return;
    }
    setSending(true);
    try {
      let id = sessionId;
      if (!id || session?.agentId !== agentId) {
        if (id) await api.closeSession(id).catch(() => undefined);
        const started = await api.startSession({ agentId, projectId, permissionMode: "ask" });
        id = started.session.id;
        setSessionId(id);
        setSession(started.session);
      }
      const prompted = await api.prompt(id, { text: prompt, includeImages: true });
      setSession(prompted.session);
      setPrompt("");
      if (prompted.session.status !== "running" && prompted.session.status !== "starting") {
        await onProjectRef.current();
      }
    } catch (error) {
      onErrorRef.current(errorMessage(error));
    } finally {
      setSending(false);
    }
  }

  async function cancel() {
    if (!sessionId) return;
    try {
      const body = await api.cancel(sessionId);
      setSession(body.session);
    } catch (error) {
      onErrorRef.current(errorMessage(error));
    }
  }

  async function resolve(outcome: "allow" | "deny") {
    const requestId = permissionRequestId(session?.pendingPermission);
    if (!sessionId || !requestId) return;
    try {
      const body = await api.resolvePermission(sessionId, requestId, outcome);
      setSession(body.session);
    } catch (error) {
      onErrorRef.current(errorMessage(error));
    }
  }

  const pending = session?.pendingPermission ?? null;
  const messages = session?.messages ?? [];
  const chosen = agents.find((agent) => agent.id === agentId);
  const canSend = Boolean(chosen && isAgentAvailable(chosen) && !sending);

  return (
    <section className="panel">
      <h2>Agent</h2>
      <p className="note">The agent edits this map only through the studio command. Reference images are included.</p>
      <label>
        Agent
        <select data-testid="agent-select" value={agentId} onChange={(event) => setAgentId(event.target.value)}>
          {agents.length === 0 ? <option value="">No agents</option> : null}
          {agents.map((agent) => {
            const available = isAgentAvailable(agent);
            const reason = !available && agent.reason ? ` — ${agent.reason}` : "";
            return (
              <option key={agent.id} value={agent.id} disabled={!available}>
                {agentLabel(agent)}
                {reason}
              </option>
            );
          })}
        </select>
      </label>
      <label>
        Prompt
        <textarea
          data-testid="agent-prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </label>
      <div className="actions">
        <button type="button" data-testid="agent-send" onClick={() => void send()} disabled={!canSend}>
          Send
        </button>
        <button type="button" data-testid="agent-cancel" onClick={() => void cancel()} disabled={!sessionId}>
          Cancel
        </button>
      </div>
      {pending ? (
        <div className="permission">
          <h3>{pending.title || "Permission"}</h3>
          {pending.detail ? <p>{pending.detail}</p> : null}
          <div className="actions">
            <button type="button" data-testid="permission-allow" onClick={() => void resolve("allow")}>
              Allow
            </button>
            <button type="button" className="danger-button" data-testid="permission-deny" onClick={() => void resolve("deny")}>
              Deny
            </button>
          </div>
        </div>
      ) : null}
      <div data-testid="agent-log" className="agent-log" aria-live="polite">
        {session ? <p className="note">Status: {session.status}</p> : null}
        {messages.map((message, index) => (
          <p key={`${message.at ?? "m"}-${index}`}>
            <span className="role">{message.role}</span>
            {message.text || message.content || ""}
          </p>
        ))}
        {session?.error ? <p className="danger-text">{session.error}</p> : null}
      </div>
    </section>
  );
}
