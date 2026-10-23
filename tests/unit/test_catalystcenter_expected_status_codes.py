"""Catalyst Center per-endpoint expected_status_codes handling."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ruamel.yaml import YAML

from nac_collector.controller.catalystcenter import CiscoClientCATALYSTCENTER

pytestmark = pytest.mark.unit

RESOURCES = Path(__file__).parents[2] / "nac_collector" / "resources"

BENIGN_ENDPOINTS = {
    "device_detail": [500],
    "fabric_authentication_profile": [400],
    "virtual_network_ip_pool": [400],
    "wireless_controller_primary_managed_ap_locations": [400],
    "wireless_controller_secondary_managed_ap_locations": [400],
}


@pytest.fixture
def catalyst_client():
    client = CiscoClientCATALYSTCENTER(
        username="admin",
        password="secret",
        base_url="https://catc.example.com",
        max_retries=1,
        retry_after=0,
        timeout=5,
        ssl_verify=False,
    )
    client.db = MagicMock()
    client.db.get.return_value = None
    return client


def _flatten(endpoints: list[dict]) -> dict[str, dict]:
    result = {}
    for endpoint in endpoints:
        result[endpoint["name"]] = endpoint
        result.update(_flatten(endpoint.get("children", [])))
    return result


@pytest.mark.parametrize("name,codes", BENIGN_ENDPOINTS.items())
def test_expected_status_codes_in_overrides_and_generated_file(name, codes) -> None:
    """The generated endpoints file must stay in sync with the overrides."""
    yaml = YAML(typ="safe")
    overrides = yaml.load(RESOURCES / "endpoint_overrides" / "catalystcenter.yaml")
    override = next(
        item for item in overrides["extra_endpoints"] if item["name"] == name
    )
    generated = _flatten(yaml.load(RESOURCES / "endpoints" / "catalystcenter.yaml"))

    assert override["expected_status_codes"] == codes
    assert generated[name]["expected_status_codes"] == codes


def test_direct_endpoint_passes_expected_status_codes(catalyst_client) -> None:
    endpoint = {
        "name": "device_detail",
        "endpoint": "/dna/intent/api/v1/device-detail",
        "expected_status_codes": [500],
    }

    with patch.object(
        catalyst_client, "fetch_data_pagination", return_value=None
    ) as mock_fetch:
        catalyst_client.process_endpoint(endpoint)

    mock_fetch.assert_called_once_with("/dna/intent/api/v1/device-detail", [500])


def test_lookup_endpoint_applies_codes_to_target_not_source(catalyst_client) -> None:
    """The source (inventory) request stays strict; only per-item targets are lenient."""
    endpoint = {
        "name": "wireless_controller_primary_managed_ap_locations",
        "endpoint": "/dna/intent/api/v1/wirelessControllers/%v/primaryManagedApLocations",
        "expected_status_codes": [400],
    }
    source = {"response": [{"id": "dev-1"}]}

    with patch.object(
        catalyst_client, "fetch_data_pagination", side_effect=[source, None]
    ) as mock_fetch:
        catalyst_client.fetch_data_alternate(endpoint)

    source_call, target_call = mock_fetch.call_args_list
    assert source_call.args == ("/dna/intent/api/v1/network-device",)
    assert target_call.args == (
        "/dna/intent/api/v1/wirelessControllers/dev-1/primaryManagedApLocations",
        [400],
    )


def test_child_endpoint_passes_its_own_expected_status_codes(catalyst_client) -> None:
    endpoint = {
        "name": "parent",
        "endpoint": "/dna/intent/api/v1/parent",
        "children": [
            {
                "name": "child",
                "endpoint": "/child",
                "expected_status_codes": [400],
            }
        ],
    }
    parent = {"response": [{"id": "p1"}]}

    with patch.object(
        catalyst_client, "fetch_data_pagination", side_effect=[parent, None]
    ) as mock_fetch:
        catalyst_client.process_endpoint(endpoint)

    parent_call, child_call = mock_fetch.call_args_list
    assert parent_call.args == ("/dna/intent/api/v1/parent", ())
    assert child_call.args == ("/dna/intent/api/v1/parent/p1/child", [400])
