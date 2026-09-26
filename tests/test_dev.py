import os
import signal
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _listeners(port: int) -> list[int]:
    output = subprocess.check_output(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        text=True,
    ) if _port_open(port) else ""
    return [int(line) for line in output.split() if line.strip()]


def _port_open(port: int) -> bool:
    probe = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return probe.returncode == 0


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_npm_run_dev_shutdown_stops_api():
    api_port = _free_port()
    ui_port = _free_port()
    env = os.environ.copy()
    env["MCMAP_API_PORT"] = str(api_port)
    env["MCMAP_UI_PORT"] = str(ui_port)
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.time() + 40
        while time.time() < deadline:
            if _port_open(api_port) and _port_open(ui_port):
                break
            if proc.poll() is not None:
                raise AssertionError(f"npm run dev exited early with status {proc.returncode}")
            time.sleep(0.25)
        else:
            raise AssertionError(f"dev servers did not listen on {api_port} and {ui_port}")
        os.kill(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            raise AssertionError("npm run dev did not exit after SIGTERM") from None
        time.sleep(0.8)
        assert not _port_open(api_port), f"API still listening on {api_port} after npm run dev stopped"
        assert not _port_open(ui_port), f"UI still listening on {ui_port} after npm run dev stopped"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        for port in (api_port, ui_port):
            for pid in _listeners(port):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
