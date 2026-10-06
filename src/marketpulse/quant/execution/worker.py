from __future__ import annotations

import asyncio
import json
import os
import socket
import sys

from ..domain import ArtifactBundle, ComputeInput

INPUT_CAP = 24 * 1024 * 1024
OUTPUT_CAP = 8 * 1024 * 1024


async def bounded_read(stream, cap):
    chunks, size = [], 0
    while chunk := await stream.read(65536):
        size += len(chunk)
        if size > cap:
            raise ValueError("compute output limit exceeded")
        chunks.append(chunk)
    return b"".join(chunks)


class ComputeWorker:
    def __init__(self, python: str | None = None):
        self.python = python or sys.executable
        self.active_pids: set[int] = set()
        self.started = asyncio.Event()

    async def run(self, request: ComputeInput, *, timeout: float = 30) -> ArtifactBundle:  # noqa: ASYNC109
        if not 0 < timeout <= 120:
            raise ValueError("bounded compute timeout required")
        data = request.model_dump_json().encode()
        if len(data) > INPUT_CAP:
            raise ValueError("compute input limit exceeded")
        # Do not propagate model/provider credentials into the offline worker.
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "SYSTEMROOT",
                "WINDIR",
                "PATH",
                "TEMP",
                "TMP",
                "PYTHONPATH",
                "PROCESSOR_ARCHITECTURE",
                "PROCESSOR_ARCHITEW6432",
            }
        }
        env.update(PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0", OMP_NUM_THREADS="1")
        child = await asyncio.create_subprocess_exec(
            self.python,
            "-m",
            "marketpulse.quant.execution.worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self.active_pids.add(child.pid)
        self.started.set()
        try:
            async with asyncio.timeout(timeout):
                child.stdin.write(data)
                await child.stdin.drain()
                child.stdin.close()
                stdout, _ = await asyncio.gather(
                    bounded_read(child.stdout, OUTPUT_CAP), bounded_read(child.stderr, 65536)
                )
                await child.wait()
            if child.returncode:
                raise ValueError("offline computation failed")
            return ArtifactBundle.model_validate_json(stdout)
        finally:
            if child.returncode is None:
                child.kill()
            await child.wait()
            self.active_pids.discard(child.pid)


def main():
    from .limits import apply_limits

    limit_handle = apply_limits()
    data = sys.stdin.buffer.read(INPUT_CAP + 1)
    if len(data) > INPUT_CAP:
        raise ValueError("input limit")

    # No networking, SDK, SQL or model in this process.
    def denied(*args, **kwargs):
        raise PermissionError("offline computation forbids network")

    socket.socket = denied
    from ..compute.engine import execute
    from .environment import runtime_environment

    request = ComputeInput.model_validate_json(data)
    actual = json.loads(json.dumps(runtime_environment()))
    pinned = json.loads(request.environment_json)
    if any(pinned.get(key) != value for key, value in actual.items()):
        raise ValueError("actual worker environment differs from manifest")
    result = execute(request).model_dump_json().encode()
    if len(result) > OUTPUT_CAP:
        raise ValueError("output limit")
    sys.stdout.buffer.write(result)
    _ = limit_handle


if __name__ == "__main__":
    main()
