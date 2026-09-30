"""A real API process crash after recording, supervised restart, and automatic continuation."""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from marketpulse.investigation.operations.supervisor import SupervisorConfig, supervise


def test_real_api_crash_recovers_same_run_without_repeating_saved_model_call(
    tmp_path: Path,
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    helper = tmp_path / "crash_worker.py"
    helper.write_text(
        """
import os
from pathlib import Path
import uvicorn
from pydantic import SecretStr
from marketpulse.config import Settings
from marketpulse.investigation.server import create_app
from marketpulse.investigation.live_runtime import LivePorts
from marketpulse.investigation.harness.persistence import HarnessStore
from marketpulse.investigation.domain.runtime import ExecutionStep
from marketpulse.investigation.domain.enums import StepType
from tests.integration.investigation.test_live_runtime import OutagePorts
ROOT = Path(__file__).parent
os.environ['INVESTIGATION_BLOB_ROOT'] = str(ROOT / 'blobs')
class Ports(OutagePorts):
    async def generate(self, request):
        with (ROOT / 'calls.txt').open('a') as out:
            out.write(request.response_model.__name__ + '\\n')
        return await super().generate(request)
original = HarnessStore.complete_step
def complete(self, **kwargs):
    step = self.repository.get(ExecutionStep, kwargs['step_id'])
    if step.step_type is StepType.PLANNING and not (ROOT / 'crashed').exists():
        (ROOT / 'crashed').write_text(str(os.getpid()))
        os._exit(23)
    return original(self, **kwargs)
HarnessStore.complete_step = complete
ports = Ports()
settings = Settings(
    database_url=SecretStr('sqlite:///' + (ROOT / 'db.sqlite3').as_posix()),
                    max_research_rounds=1, recovery_scan_seconds=0.1, auto_resume_backoff_seconds=0)
app = create_app(settings=settings, live_ports=LivePorts(ports, ports, ports))
uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='critical')
""".replace("PORT,", str(port) + ","),
        encoding="utf-8",
    )
    # Import test ports in the subprocess without using any provider credentials.
    root = Path(__file__).resolve().parents[3]
    command = [
        sys.executable,
        "-c",
        "import runpy,sys; sys.path.insert(0,sys.argv[1]); "
        "runpy.run_path(sys.argv[2],run_name='__main__')",
        str(root),
        str(helper),
    ]
    stopped = threading.Event()
    children: list[subprocess.Popen[bytes]] = []
    outcomes: list[int] = []
    config = SupervisorConfig(
        health_url=f"http://127.0.0.1:{port}/api/health",
        startup_grace=30,
        backoff_initial=0.1,
        backoff_max=0.5,
        poll_interval=0.05,
        terminate_timeout=2,
        kill_timeout=2,
    )
    thread = threading.Thread(
        target=lambda: outcomes.append(
            supervise(command, config=config, stop_event=stopped, on_start=children.append)
        )
    )
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=1, trust_env=False
        ) as client:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                try:
                    if client.get("/api/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("API did not become healthy")
            investigation = client.post(
                "/api/investigations",
                json={
                    "title": "CrowdStrike outage",
                    "event_description": "CrowdStrike July 2024 outage",
                    "investigation_goal": "Establish facts",
                    "questions": ["What happened?"],
                },
            ).json()["investigation_id"]
            # Crash may race HTTP response. Recover the persisted run ID by listing, never re-POST.
            try:
                client.post(f"/api/investigations/{investigation}/runs")
            except httpx.HTTPError:
                pass
            finished = None
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    runs = client.get(f"/api/investigations/{investigation}/runs").json()
                    if runs and runs[0]["status"] == "BLOCKED":
                        finished = runs
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(0.1)
            assert finished and len(finished) == 1
            assert (tmp_path / "crashed").exists()
            assert len(children) >= 2
            calls = (tmp_path / "calls.txt").read_text().splitlines()
            assert calls.count("PlanProposal") == 1
            assert "VerificationProposal" in calls
    finally:
        stopped.set()
        thread.join(timeout=10)
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        assert not thread.is_alive()
    assert outcomes == [0]
