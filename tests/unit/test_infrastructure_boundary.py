from __future__ import annotations

import ast
from pathlib import Path


def test_generic_infrastructure_does_not_import_market_business() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "marketpulse" / "infrastructure"
    files = list(root.rglob("*.py"))
    assert files, "generic infrastructure must exist"
    violations: list[str] = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                # Relative imports are deliberately forbidden for a visible boundary.
                assert node.level == 0, f"Use absolute infrastructure imports: {path.name}"
                imports = [node.module or ""]
            for name in imports:
                if name == "marketpulse" or (
                    name.startswith("marketpulse.")
                    and not name.startswith("marketpulse.infrastructure.")
                ):
                    violations.append(f"{path.name}:{node.lineno}: {name}")
    assert not violations, "Market dependency leaked into infrastructure: " + "; ".join(violations)
