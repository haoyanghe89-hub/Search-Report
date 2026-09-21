from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INVESTIGATION = ROOT / "src" / "marketpulse" / "investigation"

FORBIDDEN_LEGACY_PREFIXES = (
    "marketpulse.agents",
    "marketpulse.domain",
    "marketpulse.services",
    "marketpulse.workflow",
)
FORBIDDEN_DOMAIN_PREFIXES = (
    "sqlalchemy",
    "alembic",
    "fastapi",
    "agents",
    "openai",
    "pathlib",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_investigation_package_has_no_market_specific_dependencies() -> None:
    violations: list[str] = []
    for path in INVESTIGATION.rglob("*.py"):
        for imported in _imports(path):
            if imported.startswith(FORBIDDEN_LEGACY_PREFIXES):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert not violations, "\n".join(violations)


def test_domain_has_no_framework_provider_or_filesystem_dependency() -> None:
    violations: list[str] = []
    for path in (INVESTIGATION / "domain").glob("*.py"):
        for imported in _imports(path):
            if imported.startswith(FORBIDDEN_DOMAIN_PREFIXES):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert not violations, "\n".join(violations)


def test_evidence_and_claim_are_declared_in_different_modules() -> None:
    evidence = (INVESTIGATION / "domain" / "sources.py").read_text(encoding="utf-8")
    claims = (INVESTIGATION / "domain" / "claims.py").read_text(encoding="utf-8")
    assert "class Evidence(" in evidence
    assert "class Claim(" not in evidence
    assert "class Claim(" in claims
    assert "class Evidence(" not in claims


def test_validation_core_does_not_depend_on_agents_or_harness() -> None:
    violations: list[str] = []
    for path in (INVESTIGATION / "validation").glob("*.py"):
        for imported in _imports(path):
            if imported.startswith(
                (
                    "marketpulse.investigation.agents",
                    "marketpulse.investigation.harness",
                )
            ):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert not violations, "\n".join(violations)
