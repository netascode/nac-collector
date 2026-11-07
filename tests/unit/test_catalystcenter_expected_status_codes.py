"""Catalyst Center per-endpoint expected_status_codes handling."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ruamel.yaml import YAML

from nac_collector.controller.catalystcenter import CiscoClientCATALYSTCENTER

pytestmark = pytest.mark.unit

RESOURCES = Path(__file__).parents[2] / "nac_collector" / "resources"

BENIGN_ENDPOINTS = {
    "wireless_controller_primary_managed_ap_locations": [400],
    "wireless_controller_secondary_managed_ap_locations": [400],
}

# Lookups that only query items the target applies to, so any non-success
# response is a real failure and must not be exempted.
STRICT_ENDPOINTS = ["device_detail", "fabric_authentication_profile"]

FABRIC_DEVICES_URL = (
    "/dna/intent/api/v1/sda/fabricDevices?fabricId={}"
    "&deviceRoles=WIRELESS_CONTROLLER_NODE"
)


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


@pytest.mark.parametrize("name", STRICT_ENDPOINTS)
def test_filtered_lookups_have_no_exemption(name) -> None:
    """These lookups only query items that apply, so a 4xx/5xx is a real failure."""
    yaml = YAML(typ="safe")
    overrides = yaml.load(RESOURCES / "endpoint_overrides" / "catalystcenter.yaml")
    override = next(
        item for item in overrides["extra_endpoints"] if item["name"] == name
    )
    generated = _flatten(yaml.load(RESOURCES / "endpoints" / "catalystcenter.yaml"))

    assert "expected_status_codes" not in override
    assert "expected_status_codes" not in generated[name]


def test_direct_endpoint_passes_expected_status_codes(catalyst_client) -> None:
    endpoint = {
        "name": "example_direct",
        "endpoint": "/dna/intent/api/v1/example",
        "expected_status_codes": [400],
    }
    assert endpoint["endpoint"] not in catalyst_client.id_lookup

    with patch.object(
        catalyst_client, "fetch_data_pagination", return_value=None
    ) as mock_fetch:
        catalyst_client.process_endpoint(endpoint)

    mock_fetch.assert_called_once_with("/dna/intent/api/v1/example", [400])


def test_lookup_endpoint_applies_codes_to_target_only(catalyst_client) -> None:
    """Source and filter requests stay strict; only managed-AP targets are lenient."""
    endpoint = {
        "name": "wireless_controller_primary_managed_ap_locations",
        "endpoint": "/dna/intent/api/v1/wirelessControllers/%v/primaryManagedApLocations",
        "expected_status_codes": [400],
    }
    target = "/dna/intent/api/v1/wirelessControllers/wlc-1/primaryManagedApLocations"
    responses = {
        "/dna/intent/api/v1/network-device": {
            "response": [{"id": "wlc-1", "family": "Wireless Controller"}]
        },
        "/dna/intent/api/v1/sda/fabricSites?limit=500": {
            "response": [{"id": "fabric-1"}]
        },
        FABRIC_DEVICES_URL.format("fabric-1"): {"response": []},
        target: None,
    }

    def fetch(url, expected_status_codes=()):
        return responses.get(url)

    with patch.object(
        catalyst_client, "fetch_data_pagination", side_effect=fetch
    ) as mock_fetch:
        catalyst_client.fetch_data_alternate(endpoint)

    lenient = {}
    for call in mock_fetch.call_args_list:
        codes = call.args[1] if len(call.args) > 1 else ()
        if codes:
            lenient[call.args[0]] = list(codes)
    requested = {call.args[0] for call in mock_fetch.call_args_list}

    assert lenient == {target: [400]}
    assert {
        "/dna/intent/api/v1/network-device",
        "/dna/intent/api/v1/sda/fabricSites?limit=500",
        FABRIC_DEVICES_URL.format("fabric-1"),
    } <= requested


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
