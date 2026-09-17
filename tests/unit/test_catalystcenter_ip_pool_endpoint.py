"""Regression coverage for Catalyst Center global IP pool pagination."""

from pathlib import Path

from ruamel.yaml import YAML

RESOURCES = Path(__file__).parents[2] / "nac_collector" / "resources"


def _endpoint(path: Path, name: str) -> str:
    data = YAML(typ="safe").load(path)
    sections = data.get("overrides", []) if isinstance(data, dict) else data
    return next(item["endpoint"] for item in sections if item["name"] == name)


def test_ip_pool_requests_explicit_page_limit() -> None:
    """The API defaults to 25 items while the paginator assumes 500."""
    expected = "/api/v2/ippool?limit=500"

    assert (
        _endpoint(RESOURCES / "endpoint_overrides" / "catalystcenter.yaml", "ip_pool")
        == expected
    )
    assert (
        _endpoint(RESOURCES / "endpoints" / "catalystcenter.yaml", "ip_pool")
        == expected
    )
