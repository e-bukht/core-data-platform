from core_platform.foundation.identifiers import DomainId, new_uuid7


def test_uuid7_has_expected_version_and_variant() -> None:
    value = new_uuid7(timestamp_ms=1_700_000_000_000)
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_domain_id_round_trips() -> None:
    value = DomainId.new()
    assert DomainId.parse(str(value)) == value
