from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = {
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "structlog",
    "jwt",
    "httpx",
    "core_platform.application",
    "core_platform.infrastructure",
    "core_platform.host",
}


def test_platform_kernel_has_no_framework_or_adapter_imports() -> None:
    root = Path(__file__).parents[2] / "src" / "core_platform" / "platform_kernel"
    violations: list[str] = []
    for source_file in root.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                forbidden = any(
                    name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES
                )
                if forbidden:
                    violations.append(f"{source_file.relative_to(root)} -> {name}")
    assert violations == []
