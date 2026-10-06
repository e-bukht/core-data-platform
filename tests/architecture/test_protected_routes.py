from pathlib import Path


def test_platform_routes_declare_capability_dependencies() -> None:
    api_root = (
        Path(__file__).parents[2]
        / "src"
        / "core_platform"
        / "host"
        / "api"
    )

    context_source = (
        api_root / "context_trust.py"
    ).read_text(
        encoding="utf-8"
    )

    required = {
        "platform.context.read",
        "platform.tenant.read",
        "platform.actor.read.self",
        "platform.capability.read.self",
    }

    for capability in required:
        assert (
            f'require_capability("{capability}")'
            in context_source
        )

    break_glass_source = (
        api_root / "break_glass.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "BREAK_GLASS_MANAGEMENT_CAPABILITY"
        in break_glass_source
    )
    assert (
        "require_capability("
        in break_glass_source
    )

    assert (
        break_glass_source.count(
            "BREAK_GLASS_MANAGEMENT_CAPABILITY"
        )
        >= 3
    )

    assert (
        '"/grants/{grant_id}/suspend"'
        in break_glass_source
    )

    assert (
        '"/grants/{grant_id}/resume"'
        in break_glass_source
    )

    assert (
        '"/grants/{grant_id}/revoke"'
        in break_glass_source
    )

    assert (
        break_glass_source.count(
            "BREAK_GLASS_MANAGEMENT_CAPABILITY"
        )
        >= 5
    )

    assert (
        break_glass_source.count(
            "BREAK_GLASS_MANAGEMENT_CAPABILITY"
        )
        >= 4
    )
