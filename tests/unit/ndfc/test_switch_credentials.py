"""Switch_Credentials: discovery credentials (SNMPv3 auth protocol) per fabric.

lanConfig/getLanSwitchCredentials returns the records of every fabric and ignores
query filters (verified on NDFC 12.6). The record shape below is a real response from
that endpoint (values anonymised): the masked sshPassword and sshUserName must never
be collected; v3Protocol feeds NAC vxlan.global.<type>.auth_proto.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from nac_collector.controller.ndfc import CiscoClientNDFC

pytestmark = pytest.mark.unit

ENDPOINT = (
    "/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/lanConfig/getLanSwitchCredentials"
)

RESPONSE: list[dict[str, Any]] = [
    {
        "credentialStore": "local",
        "sshUserName": "admin",
        "groupName": "FAB1",
        "v3Protocol": "0",
        "credType": "Custom",
        "switchName": "leaf1",
        "switchDbID": "100",
        "ipAddress": "192.0.2.11",
        "sshPassword": "*****",
    },
    {
        "credentialStore": "local",
        "sshUserName": "admin",
        "groupName": "OTHER",
        "v3Protocol": "1",
        "credType": "Custom",
        "switchName": "other1",
        "switchDbID": "200",
        "ipAddress": "192.0.2.21",
        "sshPassword": "*****",
    },
    {
        "credentialStore": "local",
        "sshUserName": "",
        "groupName": "FAB1",
        "v3Protocol": "N/A",
        "credType": "",
        "switchName": "preprov1",
        "switchDbID": "101",
        "ipAddress": "192.0.2.12",
    },
]


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


def test_filter_keeps_fabric_records_without_secrets(
    ndfc_client: CiscoClientNDFC,
) -> None:
    records = ndfc_client._filter_switch_credentials(RESPONSE, "FAB1")

    assert [r["switchName"] for r in records] == ["leaf1", "preprov1"]
    assert records[0] == {
        "groupName": "FAB1",
        "switchName": "leaf1",
        "switchDbID": "100",
        "ipAddress": "192.0.2.11",
        "credType": "Custom",
        "v3Protocol": "0",
    }
    for record in records:
        assert "sshPassword" not in record
        assert "sshUserName" not in record
        assert "credentialStore" not in record


@pytest.mark.parametrize("data", [None, {}, {"error": "x"}, "text"])
def test_filter_unexpected_response(ndfc_client: CiscoClientNDFC, data: Any) -> None:
    assert ndfc_client._filter_switch_credentials(data, "FAB1") == []


def test_single_site_endpoint_collects_filtered_records(
    ndfc_client: CiscoClientNDFC,
) -> None:
    ndfc_client.fetch_data = MagicMock(return_value=RESPONSE)  # type: ignore[method-assign]
    result: dict[str, Any] = {"Switch_Credentials": []}

    ndfc_client._process_endpoint_single_site(
        {"name": "Switch_Credentials", "endpoint": ENDPOINT}, result
    )

    ndfc_client.fetch_data.assert_called_once_with(ENDPOINT)
    entry = result["Switch_Credentials"][0]
    assert entry["fabric"] == "FAB1"
    assert [r["switchName"] for r in entry["data"]] == ["leaf1", "preprov1"]
    assert all("sshPassword" not in r for r in entry["data"])


def test_msd_root_skips_switch_credentials() -> None:
    assert "Switch_Credentials" in CiscoClientNDFC.MSD_ROOT_SKIPPED_ENDPOINTS
