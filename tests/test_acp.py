import json
import os
import shutil
import sys
import time
from io import BytesIO

import pytest
from PIL import Image

from mcmap.acp.manager import AgentManager, MAX_INLINE_IMAGE_BYTES
from mcmap.model import new_project
from mcmap.paths import repo_root
from mcmap.store import ProjectStore


def _manager(projects):
    return AgentManager(str(repo_root()), str(projects), sys.executable)


def _project(tmp_path, name="ACP"):
    store = ProjectStore(tmp_path / "projects")
    project = new_project(name, 64, 64, 1)
    store.save(project)
    return store, project


def _wait(manager, session_id, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = manager.get(session_id)
        if predicate(last):
            return last
        if last["status"] == "error":
            raise AssertionError(last["error"] or last)
        time.sleep(0.02)
    raise AssertionError(last)


def _idle(manager, session_id, timeout=8):
    return _wait(manager, session_id, lambda snap: snap["status"] == "idle", timeout)


def _last_agent(snap) -> str:
    texts = [item["text"] for item in snap["messages"] if item["role"] == "agent"]
    return texts[-1] if texts else ""


def _apply_prompt(name, shape, palette=None):
    args = {"name": name, "color": "#336699", "shape": shape}
    if palette is not None:
        args["palette"] = palette
    return "APPLY_JSON:" + json.dumps({"operations": [{"op": "region.create", "args": args}]})


def test_discovery_lists_test_and_keeps_codex_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("mcmap.acp.manager.shutil.which", lambda command: f"/usr/bin/{command}")
    isolated = AgentManager(str(tmp_path / "repo"), str(tmp_path / "projects"), sys.executable)
    (tmp_path / "repo").mkdir()
    agents = {item["id"]: item for item in isolated.list_agents()}
    assert set(agents) == {"grok", "codex", "test"}
    assert agents["test"]["available"] is True
    assert agents["test"]["args"] == ["-m", "mcmap.acp.test_agent"]
    assert agents["test"]["command"] == sys.executable
    assert agents["grok"]["available"] is True
    assert agents["grok"]["command"] == "grok"
    assert agents["grok"]["args"] == ["agent", "--no-leader", "stdio"]
    assert agents["codex"]["available"] is False
    assert agents["codex"]["args"] == ["-y", "@agentclientprotocol/codex-acp"]
    assert "agents.json" in agents["codex"]["reason"]

    real = {item["id"]: item for item in _manager(tmp_path / "projects").list_agents()}
    assert real["test"]["available"] is True
    assert real["codex"]["available"] is False


def test_codex_opt_in_still_needs_npx(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "data" / "agents.json").write_text(json.dumps({"codex": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setattr("mcmap.acp.manager.shutil.which", lambda command: None)
    hidden = {item["id"]: item for item in AgentManager(str(root), str(tmp_path / "projects"), sys.executable).list_agents()}
    assert hidden["codex"]["available"] is False
    assert "npx" in hidden["codex"]["reason"]

    monkeypatch.setattr("mcmap.acp.manager.shutil.which", lambda command: "/usr/bin/npx" if command == "npx" else None)
    shown = {item["id"]: item for item in AgentManager(str(root), str(tmp_path / "projects"), os.sys.executable).list_agents()}
    assert shown["codex"]["available"] is True
    assert shown["codex"]["reason"] is None


def test_prompt_reports_blocks_and_coalesces_text(tmp_path):
    store, project = _project(tmp_path, "Blocks")
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buffer, format="PNG")
    store.save_asset(project, buffer.getvalue(), "coast")
    project = store.load(project["id"])
    assets = store.project_dir(project["id"]) / "assets"
    (assets / "big.bin").write_bytes(b"\0" * MAX_INLINE_IMAGE_BYTES)
    project["assets"].extend(
        [
            {
                "id": "44444444-4444-4444-8444-444444444444",
                "filename": "big.bin",
                "caption": "big",
                "mime": "image/png",
                "width": 1,
                "height": 1,
            },
            {
                "id": "55555555-5555-4555-8555-555555555555",
                "filename": "../project.json",
                "caption": "escape",
                "mime": "image/png",
                "width": 1,
                "height": 1,
            },
        ]
    )
    store.save(project)
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "ask")
    try:
        assert session["status"] == "idle"
        assert session["capabilities"]["loadSession"] is False
        assert session["capabilities"]["promptCapabilities"]["image"] is True
        assert session["capabilities"]["promptCapabilities"]["embeddedContext"] is True
        assert session["capabilities"]["mcpCapabilities"] == {"http": False, "sse": False}
        manager.prompt(session["id"], "hello")
        done = _idle(manager, session["id"])
        assert _last_agent(done) == "text_length=5 image=1 resource_link=2"
        manager.prompt(session["id"], "CHUNK_ME")
        chunked = _idle(manager, session["id"])
        agent_messages = [item["text"] for item in chunked["messages"] if item["role"] == "agent"]
        assert agent_messages[-1] == "hello"
        assert agent_messages.count("hello") == 1
        assert "hel" not in agent_messages
    finally:
        manager.close(session["id"])


def test_image_blocks_follow_prompt_capability(tmp_path, monkeypatch):
    store, project = _project(tmp_path, "No Image")
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (9, 8, 7)).save(buffer, format="PNG")
    store.save_asset(project, buffer.getvalue(), "map")
    monkeypatch.setenv("MCMAP_TEST_AGENT_IMAGE", "0")
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "ask")
    try:
        assert session["capabilities"]["promptCapabilities"]["image"] is False
        manager.prompt(session["id"], "hello")
        done = _idle(manager, session["id"])
        assert _last_agent(done) == "text_length=5 image=0 resource_link=1"
    finally:
        manager.close(session["id"])


def test_cancel_ends_the_turn_and_rejects_a_second_prompt(tmp_path):
    store, project = _project(tmp_path)
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "ask")
    try:
        started = manager.prompt(session["id"], "please CANCEL_ME")
        assert started["status"] == "running"
        _wait(manager, session["id"], lambda snap: any(item["text"] == "working" for item in snap["messages"]))
        with pytest.raises(RuntimeError, match="already running"):
            manager.prompt(session["id"], "again")
        manager.cancel(session["id"])
        done = _wait(
            manager,
            session["id"],
            lambda snap: snap["status"] == "idle" and snap.get("stopReason") == "cancelled",
        )
        assert done["pendingPermission"] is None
        assert any(item["text"] == "working" for item in done["messages"])
    finally:
        manager.close(session["id"])


def test_ask_mode_deny_is_observed_and_blocks_mapctl(tmp_path):
    store, project = _project(tmp_path, "Ask")
    before = (store.project_dir(project["id"]) / "project.json").read_bytes()
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "ask")
    try:
        manager.prompt(session["id"], "NEED_PERMISSION")
        pending = _wait(manager, session["id"], lambda snap: snap["pendingPermission"])
        request = pending["pendingPermission"]
        assert request["title"] == "mapctl get"
        assert request["requestId"]
        assert [item["kind"] for item in request["options"]] == ["allow_once", "reject_once"]
        manager.resolve_permission(session["id"], request["requestId"], "deny")
        denied = _idle(manager, session["id"])
        assert denied["pendingPermission"] is None
        assert _last_agent(denied) == "denied"
        prompt = _apply_prompt("Should Not Land", {"x": -8, "z": -8, "width": 8, "depth": 8})
        manager.prompt(session["id"], prompt)
        blocked = _idle(manager, session["id"])
        assert _last_agent(blocked) == "Command is not allowed"
        assert (store.project_dir(project["id"]) / "project.json").read_bytes() == before
        assert store.load(project["id"])["regions"] == []
    finally:
        manager.close(session["id"])


def test_allow_mapctl_applies_region(tmp_path):
    store, project = _project(tmp_path, "Open")
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "allow-mapctl")
    try:
        prompt = _apply_prompt("Cedar Stand", {"x": -16, "z": -16, "width": 16, "depth": 16})
        manager.prompt(session["id"], prompt)
        done = _idle(manager, session["id"])
        assert done["error"] is None
        reloaded = store.load(project["id"])
        assert [region["name"] for region in reloaded["regions"]] == ["Cedar Stand"]
    finally:
        manager.close(session["id"])


def test_ask_allow_then_mapctl_applies(tmp_path):
    store, project = _project(tmp_path, "Granted")
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "ask")
    try:
        manager.prompt(session["id"], "NEED_PERMISSION")
        pending = _wait(manager, session["id"], lambda snap: snap["pendingPermission"])
        manager.resolve_permission(session["id"], pending["pendingPermission"]["requestId"], "allow")
        allowed = _idle(manager, session["id"])
        assert _last_agent(allowed) == "allowed"
        prompt = _apply_prompt("Allowed Glen", {"x": -12, "z": -12, "width": 12, "depth": 12})
        manager.prompt(session["id"], prompt)
        done = _idle(manager, session["id"])
        assert done["error"] is None, _last_agent(done)
        assert [region["name"] for region in store.load(project["id"])["regions"]] == ["Allowed Glen"]
    finally:
        manager.close(session["id"])


def test_invalid_apply_leaves_the_project_unchanged(tmp_path):
    store, project = _project(tmp_path, "Reject")
    path = store.project_dir(project["id"]) / "project.json"
    before = path.read_bytes()
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "allow-mapctl")
    try:
        bad_block = _apply_prompt(
            "Bad Blocks",
            {"x": -8, "z": -8, "width": 8, "depth": 8},
            {"allowed": ["minecraft:not_a_block"]},
        )
        manager.prompt(session["id"], bad_block)
        blocked = _idle(manager, session["id"])
        assert "minecraft:not_a_block" in _last_agent(blocked)
        assert "invalid_block" in _last_agent(blocked)
        assert path.read_bytes() == before

        outside = _apply_prompt("Too Far", {"x": 30, "z": -8, "width": 8, "depth": 8})
        manager.prompt(session["id"], outside)
        bounded = _idle(manager, session["id"])
        assert "out_of_bounds" in _last_agent(bounded)
        assert path.read_bytes() == before
        assert store.load(project["id"])["regions"] == []
    finally:
        manager.close(session["id"])


def test_filesystem_reads_are_scoped_and_writes_are_rejected(tmp_path):
    store, project = _project(tmp_path, "Read Me")
    project_file = store.project_dir(project["id"]) / "project.json"
    before = project_file.read_bytes()
    secret = tmp_path / "secret.txt"
    secret.write_text("SENTINEL-SECRET", encoding="utf-8")
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "ask")
    try:
        manager.prompt(session["id"], f"READ_FILE:{project_file}")
        own = _idle(manager, session["id"])
        assert "Read Me" in _last_agent(own)

        docs = repo_root() / "docs" / "OPERATIONS.md"
        manager.prompt(session["id"], f"READ_FILE:{docs}")
        guide = _idle(manager, session["id"])
        assert "World-plan operations" in _last_agent(guide)

        api = repo_root() / "server" / "mcmap" / "api.py"
        manager.prompt(session["id"], f"READ_FILE:{api}")
        hidden = _idle(manager, session["id"])
        assert _last_agent(hidden) == "Reading that path is not allowed."
        assert "def create_app" not in _last_agent(hidden)

        manager.prompt(session["id"], f"READ_FILE:{secret}")
        outside = _idle(manager, session["id"])
        assert _last_agent(outside) == "Reading that path is not allowed."
        assert "SENTINEL-SECRET" not in _last_agent(outside)

        manager.prompt(session["id"], "WRITE_FILE:project.json")
        rejected = _idle(manager, session["id"])
        assert _last_agent(rejected) == "Direct writes are disabled. Use python -m mcmap.cli apply."
        assert project_file.read_bytes() == before
    finally:
        manager.close(session["id"])


def test_terminal_rejects_commands_that_are_not_mapctl(tmp_path):
    store, project = _project(tmp_path)
    manager = _manager(store.root)
    session = manager.start("test", project["id"], "allow-mapctl")
    try:
        manager.prompt(session["id"], "UNSAFE_COMMAND")
        done = _idle(manager, session["id"])
        assert _last_agent(done) == "Command is not allowed"
    finally:
        manager.close(session["id"])


@pytest.mark.skipif(os.environ.get("MCMAP_LIVE_ACP") != "1", reason="Set MCMAP_LIVE_ACP=1 to talk to Grok.")
def test_live_grok_session_uses_protocol_one(tmp_path):
    if shutil.which("grok") is None:
        pytest.skip("grok is not on PATH")
    store, project = _project(tmp_path, "Live")
    manager = _manager(store.root)
    session = manager.start("grok", project["id"], "ask")
    try:
        assert session["status"] == "idle"
        assert session["capabilities"]["promptCapabilities"]["image"] is False
    finally:
        manager.close(session["id"])
