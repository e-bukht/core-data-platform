from pathlib import Path


def test_platform_routes_declare_capability_dependencies() -> None:
    source = (
        Path(__file__).parents[2] / "src" / "core_platform" / "host" / "api" / "context_trust.py"
    ).read_text(encoding="utf-8")
    required = {
        "platform.context.read",
        "platform.tenant.read",
        "platform.actor.read.self",
        "platform.capability.read.self",
    }
    for capability in required:
        assert f'require_capability("{capability}")' in source
