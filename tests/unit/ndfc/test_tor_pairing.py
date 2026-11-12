"""TorPairing: leaf/ToR pairings, read with one leaf serial of the fabric.

The ToR API returns the fabric-wide pairing list for any leaf serial, so the
collector resolves one leaf from the already-collected Discovered_Switches.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from nac_collector.controller.ndfc import CiscoClientNDFC

pytestmark = pytest.mark.unit

ENDPOINT = (
    "/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/tor/fabrics/%v"
    "/switches/{{leafSerialNumber}}"
)
TOR_ENDPOINT = {"name": "TorPairing", "endpoint": ENDPOINT}
PAIRINGS = [{"leafSN": "SN-LEAF1", "torSN": "SN-TOR1", "torName": "tor1"}]


@pytest.fixture
def ndfc_client() -> CiscoClientNDFC:
    return CiscoClientNDFC(
        username="admin",
        password="admin_pass",
        base_url="https://nd.example.com",
        max_retries=1,
        retry_after=0,
        timeout=5,
        ssl_verify=False,
        fabric_name="FAB1",
        domain="local",
    )


def _switches(*switches: dict[str, Any], fabric: str = "FAB1") -> dict[str, Any]:
    return {"Discovered_Switches": [{"fabric": fabric, "data": list(switches)}]}


def test_uses_a_leaf_serial_of_the_fabric(ndfc_client: CiscoClientNDFC) -> None:
    ndfc_client.fetch_data = MagicMock(return_value=PAIRINGS)  # type: ignore[method-assign]
    result = _switches(
        {"switchRole": "spine", "serialNumber": "SN-SPINE1"},
        {"switchRole": "leaf", "serialNumber": "SN-LEAF1"},
    )

    ndfc_client._process_endpoint_single_site(TOR_ENDPOINT, result)

    url = "/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/tor/fabrics/FAB1/switches/SN-LEAF1"
    ndfc_client.fetch_data.assert_called_once_with(url)
    assert result["TorPairing"] == [
        {"data": PAIRINGS, "endpoint": url, "fabric": "FAB1"}
    ]


def test_leaf_of_other_fabric_is_not_used(ndfc_client: CiscoClientNDFC) -> None:
    ndfc_client.fetch_data = MagicMock()  # type: ignore[method-assign]
    result = _switches({"switchRole": "leaf", "serialNumber": "SN-X"}, fabric="FAB2")

    ndfc_client._process_endpoint_single_site(TOR_ENDPOINT, result)

    ndfc_client.fetch_data.assert_not_called()
    assert result["TorPairing"] == [
        {"data": {}, "endpoint": ENDPOINT, "fabric": "FAB1"}
    ]


@pytest.mark.parametrize(
    "switches",
    [
        [{"switchRole": "spine", "serialNumber": "SN-S"}],
        [{"switchRole": "leaf"}],  # leaf without serial
        ["not-a-dict"],
    ],
)
def test_no_usable_leaf_skips_the_call(
    ndfc_client: CiscoClientNDFC, switches: list[Any]
) -> None:
    ndfc_client.fetch_data = MagicMock()  # type: ignore[method-assign]
    result = _switches(*switches)

    ndfc_client._process_endpoint_single_site(TOR_ENDPOINT, result)

    ndfc_client.fetch_data.assert_not_called()
    assert result["TorPairing"][0]["data"] == {}


def test_missing_discovered_switches_records_an_error(
    ndfc_client: CiscoClientNDFC,
) -> None:
    ndfc_client.fetch_data = MagicMock()  # type: ignore[method-assign]
    result: dict[str, Any] = {}

    ndfc_client._process_endpoint_single_site(TOR_ENDPOINT, result)

    ndfc_client.fetch_data.assert_not_called()
    assert result["TorPairing"][0]["error"] == "Discovered_Switches data not available"


@pytest.mark.parametrize("response", [None, RuntimeError("boom")])
def test_failed_fetch_keeps_an_empty_entry(
    ndfc_client: CiscoClientNDFC, response: Any
) -> None:
    ndfc_client.fetch_data = MagicMock(  # type: ignore[method-assign]
        side_effect=[response] if isinstance(response, Exception) else None,
        return_value=response,
    )
    result = _switches({"switchRole": "leaf", "serialNumber": "SN-LEAF1"})

    ndfc_client._process_endpoint_single_site(TOR_ENDPOINT, result)

    entry = result["TorPairing"][0]
    assert entry["data"] == {}
    assert ("error" in entry) == isinstance(response, Exception)


def test_msd_root_skips_tor_pairing() -> None:
    assert "TorPairing" in CiscoClientNDFC.MSD_ROOT_SKIPPED_ENDPOINTS
