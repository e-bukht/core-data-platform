from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = {
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "httpx",
    "jwt",
    "structlog",
    "core_platform.application",
    "core_platform.host",
    "core_platform.infrastructure",
}


def test_transaction_kernel_is_framework_independent() -> None:
    root = Path(__file__).parents[2] / "src" / "core_platform" / "transaction_kernel"
    violations: list[str] = []

    for source_file in root.rglob("*.py"):
        tree = ast.parse(
            source_file.read_text(encoding="utf-8-sig"),
            filename=str(source_file),
        )

        for node in ast.walk(tree):
            names: list[str] = []

            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)

            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES
                ):
                    violations.append(f"{source_file.relative_to(root)} -> {name}")

    assert violations == []
