"""Own and restart one local API process; no shell or unrelated-process signals."""

from __future__ import annotations

import argparse
import http.client
import logging
import math
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupervisorConfig:
    health_url: str | None = "http://127.0.0.1:8000/api/health"
    startup_grace: float = 60.0
    health_interval: float = 10.0
    health_timeout: float = 3.0
    unhealthy_threshold: int = 3
    terminate_timeout: float = 15.0
    kill_timeout: float = 5.0
    backoff_initial: float = 1.0
    backoff_max: float = 60.0
    backoff_reset_after: float = 300.0
    poll_interval: float = 0.2

    def __post_init__(self) -> None:
        durations = (
            self.health_interval,
            self.health_timeout,
            self.terminate_timeout,
            self.kill_timeout,
            self.backoff_initial,
            self.backoff_max,
            self.backoff_reset_after,
            self.poll_interval,
        )
        if any(not math.isfinite(value) or value <= 0 for value in durations):
            raise ValueError("Supervisor intervals must be finite and positive")
        if not math.isfinite(self.startup_grace) or self.startup_grace < 0:
            raise ValueError("Startup grace must be finite and nonnegative")
        if self.unhealthy_threshold < 1 or self.backoff_max < self.backoff_initial:
            raise ValueError("Invalid failure threshold or backoff limits")
        if self.health_url:
            parsed = urlsplit(self.health_url)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError("Health URL must be local HTTP without credentials")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


def probe_health(url: str, timeout: float) -> bool:
    """Check local response status without proxies, redirects, or body consumption."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(url, timeout=timeout) as response:
            return bool(response.status == 200)
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
        return False


def stop_child(child: subprocess.Popen[bytes], config: SupervisorConfig) -> bool:
    """Never restart until this specific child is confirmed dead and reaped."""
    if child.poll() is not None:
        return True
    try:
        child.terminate()
        child.wait(timeout=config.terminate_timeout)
        return True
    except subprocess.TimeoutExpired:
        pass
    except OSError:
        if child.poll() is not None:
            return True
    try:
        child.kill()
        child.wait(timeout=config.kill_timeout)
        return True
    except (OSError, subprocess.TimeoutExpired):
        LOGGER.error("supervisor_child_cleanup_failed pid=%s", child.pid)
        return False


def supervise(
    command: Sequence[str],
    *,
    config: SupervisorConfig | None = None,
    stop_event: threading.Event | None = None,
    on_start: Callable[[subprocess.Popen[bytes]], None] | None = None,
    health_probe: Callable[[str, float], bool] = probe_health,
) -> int:
    """Block until stopped; callbacks exist for controlled local fault drills."""
    if not command:
        raise ValueError("Child command must not be empty")
    settings = config or SupervisorConfig()
    stopped = stop_event if stop_event is not None else threading.Event()
    delay = settings.backoff_initial
    child: subprocess.Popen[bytes] | None = None
    try:
        while not stopped.is_set():
            started = time.monotonic()
            try:
                child = subprocess.Popen(
                    list(command),
                    shell=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except OSError:
                # Do not expose command arguments, environment, or exception strings.
                LOGGER.error("supervisor_child_start_failed")
            else:
                LOGGER.info("supervisor_child_started pid=%s", child.pid)
                if on_start:
                    on_start(child)
                next_probe = started + settings.startup_grace
                failures = 0
                while not stopped.is_set() and child.poll() is None:
                    now = time.monotonic()
                    if settings.health_url and now >= next_probe:
                        healthy = health_probe(settings.health_url, settings.health_timeout)
                        failures = 0 if healthy else failures + 1
                        next_probe = time.monotonic() + settings.health_interval
                        if failures >= settings.unhealthy_threshold:
                            LOGGER.warning("supervisor_child_unhealthy pid=%s", child.pid)
                            break
                    stopped.wait(settings.poll_interval)
                if not stop_child(child, settings):
                    child = None  # Cleanup was attempted; fail without starting a replacement.
                    return 1
                LOGGER.info("supervisor_child_exited pid=%s code=%s", child.pid, child.returncode)
                child = None
            if stopped.is_set():
                break
            if time.monotonic() - started >= settings.backoff_reset_after:
                delay = settings.backoff_initial
            LOGGER.warning("supervisor_restart_wait seconds=%s", delay)
            stopped.wait(delay)
            delay = min(settings.backoff_max, delay * 2)
    finally:
        if child is not None and not stop_child(child, settings):
            # A caller must not mistake a cleanup failure for a clean shutdown.
            raise RuntimeError("Unable to terminate owned child")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/api/health")
    parser.add_argument("--no-health-check", action="store_true")
    parser.add_argument("--startup-grace", type=float, default=60)
    parser.add_argument("--health-interval", type=float, default=10)
    parser.add_argument("--health-timeout", type=float, default=3)
    parser.add_argument("--unhealthy-threshold", type=int, default=3)
    parser.add_argument("--terminate-timeout", type=float, default=15)
    parser.add_argument("--kill-timeout", type=float, default=5)
    parser.add_argument("--backoff-initial", type=float, default=1)
    parser.add_argument("--backoff-max", type=float, default=60)
    parser.add_argument("--backoff-reset-after", type=float, default=300)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        config = SupervisorConfig(
            health_url=None if args.no_health_check else args.health_url,
            startup_grace=args.startup_grace,
            health_interval=args.health_interval,
            health_timeout=args.health_timeout,
            unhealthy_threshold=args.unhealthy_threshold,
            terminate_timeout=args.terminate_timeout,
            kill_timeout=args.kill_timeout,
            backoff_initial=args.backoff_initial,
            backoff_max=args.backoff_max,
            backoff_reset_after=args.backoff_reset_after,
        )
    except ValueError as exc:
        parser.error(str(exc))
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        command = [sys.executable, "-m", "marketpulse.investigation.server"]
    logging.basicConfig(level=logging.INFO)
    stopped = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        stopped.set()

    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    previous = {sig: signal.signal(sig, request_stop) for sig in signals}
    try:
        return supervise(command, config=config, stop_event=stopped)
    except RuntimeError:
        LOGGER.error("supervisor_shutdown_failed")
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
