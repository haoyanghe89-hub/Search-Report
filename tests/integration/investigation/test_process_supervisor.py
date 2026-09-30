from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from marketpulse.investigation.operations import supervisor
from marketpulse.investigation.operations.supervisor import (
    SupervisorConfig,
    main,
    probe_health,
    stop_child,
    supervise,
)


def _config(**overrides: object) -> SupervisorConfig:
    config = SupervisorConfig(
        health_url=None,
        startup_grace=0,
        health_interval=0.02,
        health_timeout=0.1,
        unhealthy_threshold=2,
        terminate_timeout=0.2,
        kill_timeout=1,
        backoff_initial=0.02,
        backoff_max=0.1,
        poll_interval=0.01,
    )
    return replace(config, **overrides)


def _wait_for(predicate: object, timeout: float = 10) -> None:
    from collections.abc import Callable

    check = cast(Callable[[], bool], predicate)
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() >= deadline:
            pytest.fail("Timed out waiting for subprocess state")
        time.sleep(0.01)


def _child_command(path: Path, *, exit_code: int | None = None) -> list[str]:
    script = (
        "import os, pathlib, sys, time; "
        "p=pathlib.Path(sys.argv[1]); "
        "f=p.open('a'); f.write(str(os.getpid())+'\\n'); f.close(); "
    )
    script += "time.sleep(60)" if exit_code is None else f"sys.exit({exit_code})"
    return [sys.executable, "-c", script, str(path)]


def test_killed_child_restarts_with_new_pid_and_stop_never_respawns(tmp_path: Path) -> None:
    stopped = threading.Event()
    children: list[subprocess.Popen[bytes]] = []
    results: list[int] = []
    pid_file = tmp_path / "children.txt"
    thread = threading.Thread(
        target=lambda: results.append(
            supervise(
                _child_command(pid_file),
                config=_config(),
                stop_event=stopped,
                on_start=children.append,
            )
        )
    )
    thread.start()
    try:
        _wait_for(lambda: pid_file.exists() and bool(pid_file.read_text().strip()))
        children[0].kill()
        _wait_for(lambda: pid_file.exists() and len(pid_file.read_text().splitlines()) >= 2)
        assert children[0].poll() is not None
        assert children[0].pid != children[1].pid
    finally:
        stopped.set()
        thread.join(timeout=5)
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    assert not thread.is_alive()
    assert results == [0]
    assert len(children) == 2
    assert all(child.poll() is not None for child in children)


@pytest.mark.parametrize("exit_code", [0, 3])
def test_unexpected_exit_restarts_even_when_exit_code_zero(
    tmp_path: Path,
    exit_code: int,
) -> None:
    stopped = threading.Event()
    children: list[subprocess.Popen[bytes]] = []

    def started(child: subprocess.Popen[bytes]) -> None:
        children.append(child)
        if len(children) == 2:
            stopped.set()

    assert (
        supervise(
            _child_command(tmp_path / "pid", exit_code=exit_code),
            config=_config(),
            stop_event=stopped,
            on_start=started,
        )
        == 0
    )
    assert len(children) == 2
    assert children[0].returncode == exit_code
    assert all(child.poll() is not None for child in children)


def test_health_failure_streak_resets_then_restarts_only_owned_child(tmp_path: Path) -> None:
    stopped = threading.Event()
    children: list[subprocess.Popen[bytes]] = []
    health_results = iter([False, True, False, False])
    probes: list[bool] = []

    def health(url: str, timeout: float) -> bool:
        result = next(health_results)
        probes.append(result)
        return result

    def started(child: subprocess.Popen[bytes]) -> None:
        if children:
            assert children[-1].poll() is not None
            stopped.set()
        children.append(child)

    assert (
        supervise(
            _child_command(tmp_path / "pid"),
            config=_config(health_url="http://127.0.0.1:8000/api/health"),
            stop_event=stopped,
            on_start=started,
            health_probe=health,
        )
        == 0
    )
    assert probes == [False, True, False, False]
    assert len(children) == 2
    assert all(child.poll() is not None for child in children)


def test_stop_interrupts_long_restart_backoff(tmp_path: Path) -> None:
    stopped = threading.Event()
    children: list[subprocess.Popen[bytes]] = []
    thread = threading.Thread(
        target=lambda: supervise(
            _child_command(tmp_path / "pid", exit_code=1),
            config=_config(backoff_initial=30, backoff_max=60),
            stop_event=stopped,
            on_start=children.append,
        )
    )
    thread.start()
    try:
        _wait_for(lambda: bool(children) and children[0].poll() is not None)
        stopped.set()
        thread.join(timeout=2)
    finally:
        stopped.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(children) == 1


def test_cleanup_failure_is_bounded_and_does_not_claim_success() -> None:
    class Unkillable:
        pid = 123
        waits: list[float] = []
        terminated = False
        killed = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float) -> None:
            self.waits.append(timeout)
            raise subprocess.TimeoutExpired("child", timeout)

    fake = Unkillable()
    config = _config()
    assert not stop_child(cast(subprocess.Popen[bytes], fake), config)
    assert fake.terminated and fake.killed
    assert fake.waits == [config.terminate_timeout, config.kill_timeout]


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGTERM refusal test")
def test_sigterm_refusal_escalates_to_kill(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    command = [
        sys.executable,
        "-c",
        (
            "import signal, pathlib, sys, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "pathlib.Path(sys.argv[1]).touch(); time.sleep(60)"
        ),
        str(ready),
    ]
    child = subprocess.Popen(command)
    try:
        _wait_for(ready.exists)
        assert stop_child(child, _config())
        assert child.returncode is not None and child.returncode < 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/health",
        "http://user:secret@localhost/",
        "file:///tmp/foo",
    ],
)
def test_health_configuration_refuses_nonlocal_or_credential_urls(url: str) -> None:
    with pytest.raises(ValueError):
        SupervisorConfig(health_url=url)


def test_health_probe_checks_http_status_without_following_redirects() -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200 if self.path == "/healthy" else 302)
            self.send_header("Location", "/healthy")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert probe_health(base + "/healthy", 1)
        assert not probe_health(base + "/redirect", 1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cli_rejects_nonfinite_or_negative_timings() -> None:
    for value in ["nan", "inf", "-1", "0"]:
        with pytest.raises(SystemExit) as exc:
            main(["--health-timeout", value])
        assert exc.value.code == 2


def test_cli_signal_handler_requests_stop_and_restores_previous_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = signal.getsignal(signal.SIGINT)
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> int:
        commands.append(command)
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)
        assert cast(threading.Event, kwargs["stop_event"]).is_set()
        return 0

    monkeypatch.setattr(supervisor, "supervise", run)
    assert main(["--no-health-check"]) == 0
    assert commands == [[sys.executable, "-m", "marketpulse.investigation.server"]]
    assert signal.getsignal(signal.SIGINT) is original
    assert main(["--no-health-check", "--", "python", "-m", "example"]) == 0
    assert commands[-1] == ["python", "-m", "example"]


def test_start_failure_backoff_doubles_to_cap_and_stop_prevents_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Stopped:
        waits: list[float] = []

        def is_set(self) -> bool:
            return len(self.waits) >= 5

        def wait(self, timeout: float) -> bool:
            self.waits.append(timeout)
            return self.is_set()

    def unavailable(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("not logged")

    monkeypatch.setattr(supervisor.subprocess, "Popen", unavailable)
    stopped = Stopped()
    assert (
        supervise(
            ["unavailable"],
            config=_config(),
            stop_event=cast(threading.Event, stopped),
        )
        == 0
    )
    assert stopped.waits == [0.02, 0.04, 0.08, 0.1, 0.1]
