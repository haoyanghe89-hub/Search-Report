"""Small metadata capture; does not execute quantitative calculations."""

import hashlib
import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path

from ..contracts import canonical, digest


def runtime_environment() -> dict:
    return {
        "python": sys.version,
        "platform": platform.system(),
        "machine": platform.machine(),
        "implementation": platform.python_implementation(),
        "byteorder": sys.byteorder,
        "pointer_bits": sys.maxsize.bit_length() + 1,
        "dependencies": sorted(
            (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
        ),
    }


def environment(root: Path) -> str:
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()

    sha = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=all"))
    paths = sorted((root / "src" / "marketpulse").rglob("*.py"))
    tree = digest(
        [
            (p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in paths
        ]
    )
    return canonical(
        {
            "git_sha": sha,
            "dirty": dirty,
            "source_tree_hash": tree,
            "lock_hash": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
            **runtime_environment(),
        }
    )
