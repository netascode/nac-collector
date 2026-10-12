"""Regression coverage for the Catalyst Center wireless profile endpoint path."""

from pathlib import Path

from ruamel.yaml import YAML

RESOURCES = Path(__file__).parents[2] / "nac_collector" / "resources"


def _load(path: Path) -> object:
    return YAML(typ="safe").load(path)


def _endpoint(path: Path, name: str) -> dict:
    data = _load(path)
    return next(item for item in data if item["name"] == name)


def test_wireless_profile_uses_dna_prefix() -> None:
    """Catalyst Center 3.2.x serves the un-prefixed path as the HTML UI shell."""
    wireless_profile = _endpoint(
        RESOURCES / "endpoints" / "catalystcenter.yaml", "wireless_profile"
    )

    assert wireless_profile["endpoint"] == "/dna/intent/api/v1/wirelessProfiles"
    assert [child["name"] for child in wireless_profile["children"]] == [
        "wireless_profile_policy_tag"
    ]


def test_wireless_profile_not_overridden() -> None:
    """The provider definition is correct; an override would pin a stale path."""
    overrides = _load(RESOURCES / "endpoint_overrides" / "catalystcenter.yaml")

    assert isinstance(overrides, dict)
    assert all(
        item["name"] != "wireless_profile" for item in overrides.get("overrides", [])
    )
