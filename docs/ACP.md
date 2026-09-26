# ACP client

The app is an ACP **client**. It spawns local agent processes and speaks JSON-RPC 2.0 as **newline-delimited JSON** (one object per line, no `Content-Length` framing). A live probe of this machine's Grok on 2026-09-26 accepted NDJSON and returned `protocolVersion: 1`.

## Discovery

`AgentManager.list_agents()` returns:

| id | Launch | Available when |
| --- | --- | --- |
| `grok` | `grok agent --no-leader stdio` | `grok` is on `PATH` |
| `codex` | `npx -y @agentclientprotocol/codex-acp` | only after `data/agents.json` sets `codex.enabled` true and `npx` exists |
| `test` | `<python> -m mcmap.acp.test_agent` | always |

Do not download packages during discovery. Codex is shown with a reason when it is not enabled. `data/agents.json` may override `command`, `args`, and `enabled` per id.

## Manager

```python
class AgentManager:
    def __init__(self, repo_root: str, projects_root: str, python_executable: str): ...
    def list_agents(self) -> list[dict]: ...
    def start(self, agent_id: str, project_id: str, permission_mode: str = "ask") -> dict: ...
    def get(self, session_id: str) -> dict: ...
    def prompt(self, session_id: str, text: str, include_images: bool = True) -> dict: ...
    def cancel(self, session_id: str) -> dict: ...
    def resolve_permission(self, session_id: str, request_id: str, outcome: str) -> dict: ...
    def close(self, session_id: str) -> None: ...
```

`start` performs `initialize` and `session/new` before returning. Raise `RuntimeError` with a useful message on failure (missing binary, timeout, auth). `prompt` returns the snapshot immediately and completes the turn on a background thread. A second prompt while `status == "running"` raises. Snapshots contain:

```text
id, agentId, projectId, status (starting|idle|running|error|closed),
messages [{role: user|agent|tool|system, text, at}],
pendingPermission or null, error, capabilities
```

`pendingPermission` is `{requestId, title, detail, options:[{optionId,name,kind}]}`. Coalesce consecutive agent text chunks into one message.

## Protocol

Initialize:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": 1,
    "clientCapabilities": {"fs": {"readTextFile": true, "writeTextFile": true}, "terminal": true},
    "clientInfo": {"name": "mcmap-studio", "title": "Minecraft Map Studio", "version": "1.0.0"}
  }
}
```

Then `session/new` with `cwd` set to the project directory and `mcpServers: []`. Grok advertises HTTP/SSE MCP, not stdio MCP, and `promptCapabilities.image` was false. Always send image **paths** and `resource_link` blocks. Send a base64 `image` block only when `promptCapabilities.image` is true and the file is under 1.5 MB. The agent list and the live session both expose `imageUnderstanding` and `imageNote`. When the capability is false, the prompt says the pixels were not sent and the agent must not claim it inspected the images. Briefs and captions remain the text interpretation.

Every prompt's first text block is:

```text
You edit a Minecraft Java 1.21.4 survival map. Change the plan, generate terrain, or export only by running this argv, not a shell string:

<python> -m mcmap.cli --root <projects_root> --project <project_id> <command>

Read docs/OPERATIONS.md in the repo. Do not write project.json yourself. Invalid blocks and coordinates are rejected by the CLI. Reference images are listed below as absolute paths.
```

Then the user text, then one `resource_link` per attached image (`uri` is a `file://` absolute URI, plus `name`, `mimeType`, `title`).

Handle agent requests on a reader thread so a blocked `session/prompt` cannot deadlock:

- `session/update`: record agent text, tool titles, and plans.
- `session/request_permission`: set `pendingPermission` and wait for `resolve_permission`. Reply `{"outcome":{"outcome":"selected","optionId":...}}`. `allow` selects the first option whose `kind` or `optionId` contains `allow`. `deny` selects the reject option. `allow` also sets `mapctl_allowed` for the rest of the session.
- `session/cancel` is a notification. Record it and surface `stopReason` when the prompt returns.
- `fs/read_text_file`: allow only paths inside the project directory or `docs/` and `schema/`. Return `{"content": "..."}`.
- `fs/write_text_file`: JSON-RPC error message `Direct writes are disabled. Use python -m mcmap.cli apply.`
- `terminal/create` / `terminal/output` / `terminal/wait_for_exit` / `terminal/kill` / `terminal/release`: run `command` plus `args` with `subprocess` without a shell. `cwd` must stay inside the repo. Output is capped by `outputByteLimit` when present, otherwise 1 MB.

A terminal command is safe mapctl only when the executable is the configured Python, the args start with `-m mcmap.cli`, and `--root` plus `--project` match this session. In `allow-mapctl` mode those commands run immediately. In `ask` mode they run only after `mapctl_allowed` is set. Every other command returns a JSON-RPC error `Command is not allowed`.

Timeouts: initialize 20 seconds, `session/new` 30 seconds. Do not time out an in-flight prompt; cancellation covers that. Capture stderr. If the process exits, set `status` to `error`.

## Test agent

`python -m mcmap.acp.test_agent` speaks the same NDJSON protocol.

- `initialize` returns protocol 1, `promptCapabilities.image` true, `embeddedContext` true, no MCP transports, and `loadSession` false.
- `session/new` returns a session id.
- Prompt text containing `CANCEL_ME`: send an agent text update `working`, wait until `session/cancel`, then finish the prompt with `stopReason` `cancelled`.
- Prompt text containing `NEED_PERMISSION`: send `session/request_permission` for a mapctl `get`, wait for the result, then say `allowed` or `denied`.
- Prompt text containing `APPLY_JSON:` plus a JSON object: after a permission request is allowed (or immediately if you want the client policy to refuse), call `terminal/create` with the mapctl `apply --json <object>` argv and report stdout.
- Any other prompt: reply with the user text length and the counts of `image` and `resource_link` blocks.

## Tests

`tests/test_acp.py` must cover, without network and without Grok:

- discovery lists `test` as available and does not mark Codex available just because `npx` exists
- test-agent session starts, answers a normal prompt, and reports image or resource-link counts
- `CANCEL_ME` ends the turn
- `ask` mode surfaces a permission and `deny` is observed
- `allow-mapctl` can apply a valid `region.create` through the CLI and the project reloads with that region
- an apply with `minecraft:not_a_block` or an out-of-bounds shape leaves the project unchanged and returns a validation error
- `fs/write_text_file` is rejected if the test agent is asked to issue it (`WRITE_FILE:` in the prompt is enough)

Do not start the API server. A live Grok test is optional and must skip unless `MCMAP_LIVE_ACP=1`.
