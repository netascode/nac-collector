"""MSD root: member-fabric copies of the MSD VRFs / networks nested as child_fabrics.

Only VXLAN members hold a copy of the overlay; External / ISN members
(NON_OVERLAY_FABRIC_TEMPLATES) are not queried.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from nac_collector.controller.ndfc import CiscoClientNDFC

pytestmark = pytest.mark.unit

BASE = "/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/fabrics"
VRF_ENDPOINT = {
    "name": "VRF_Configuration",
    "endpoint": f"{BASE}/%v/vrfs",
    "children": [
        {
            "name": "VRF_Child_Fabric_Configuration",
            "endpoint": f"{BASE}/{{{{child_fabric}}}}/vrfs",
        }
    ],
}


@pytest.fixture
def msd_root() -> CiscoClientNDFC:
    client = CiscoClientNDFC(
        username="admin",
        password="admin_pass",
        base_url="https://nd.example.com",
        max_retries=1,
        retry_after=0,
        timeout=5,
        ssl_verify=False,
        fabric_name="MSD",
        domain="local",
    )
    client.is_msd_fabric = True
    client.msd_topology = {
        "msd_root": "MSD",
        "member_fabrics": ["SITE1", "SITE2", "ISN"],
    }
    return client


def _endpoint_dict(vrfs: list[Any]) -> dict[str, Any]:
    return {
        "Fabric_Configuration": [
            {"data": {"fabricName": "SITE1", "templateName": "Easy_Fabric"}},
            {"data": {"fabricName": "SITE2", "templateName": "Easy_Fabric"}},
            {"data": {"fabricName": "ISN", "templateName": "External_Fabric"}},
        ],
        "VRF_Configuration": [{"fabric": "MSD", "data": vrfs}],
    }


def _serve(per_fabric: dict[str, Any]) -> MagicMock:
    def fetch_data(url: str) -> Any:
        fabric = url[len(BASE) + 1 :].split("/")[0]
        value = per_fabric[fabric]
        if isinstance(value, Exception):
            raise value
        return value

    return MagicMock(side_effect=fetch_data)


def _run(client: CiscoClientNDFC, endpoint_dict: dict[str, Any]) -> None:
    client._process_child_fabric_overlay(
        VRF_ENDPOINT, endpoint_dict, "VRF_Child_Fabric_Configuration", "vrfName"
    )


def test_overlay_members_exclude_external_fabrics(msd_root: CiscoClientNDFC) -> None:
    assert msd_root._msd_overlay_member_fabrics(_endpoint_dict([])) == [
        "SITE1",
        "SITE2",
    ]


def test_member_copies_are_nested_per_vrf(msd_root: CiscoClientNDFC) -> None:
    msd_root.fetch_data = _serve(  # type: ignore[method-assign]
        {
            "SITE2": [{"vrfName": "V1", "site": 2}],
            "SITE1": [{"vrfName": "V1", "site": 1}, {"vrfName": "V2", "site": 1}],
        }
    )
    vrfs = [{"vrfName": "V1"}, {"vrfName": "V2"}, {"vrfName": "V3"}]

    _run(msd_root, _endpoint_dict(vrfs))

    urls = [c.args[0] for c in msd_root.fetch_data.call_args_list]
    assert urls == [f"{BASE}/SITE1/vrfs", f"{BASE}/SITE2/vrfs"]
    assert vrfs[0]["child_fabrics"] == [
        {"vrfName": "V1", "site": 1, "fabric": "SITE1"},
        {"vrfName": "V1", "site": 2, "fabric": "SITE2"},
    ]
    assert vrfs[1]["child_fabrics"] == [{"vrfName": "V2", "site": 1, "fabric": "SITE1"}]
    assert vrfs[2]["child_fabrics"] == []


@pytest.mark.parametrize("failure", [None, RuntimeError("down")])
def test_failing_member_does_not_drop_the_others(
    msd_root: CiscoClientNDFC, failure: Any
) -> None:
    msd_root.fetch_data = _serve(  # type: ignore[method-assign]
        {"SITE1": failure, "SITE2": [{"vrfName": "V1"}]}
    )
    vrfs = [{"vrfName": "V1"}]

    _run(msd_root, _endpoint_dict(vrfs))

    assert vrfs[0]["child_fabrics"] == [{"vrfName": "V1", "fabric": "SITE2"}]


def test_member_fabric_run_does_nothing(msd_root: CiscoClientNDFC) -> None:
    msd_root.fabric_name = "SITE1"
    msd_root.fetch_data = MagicMock()  # type: ignore[method-assign]
    vrfs = [{"vrfName": "V1"}]
    endpoint_dict = _endpoint_dict(vrfs)
    endpoint_dict["VRF_Configuration"][0]["fabric"] = "SITE1"

    _run(msd_root, endpoint_dict)

    msd_root.fetch_data.assert_not_called()
    assert "child_fabrics" not in vrfs[0]


def test_single_site_does_nothing(msd_root: CiscoClientNDFC) -> None:
    msd_root.is_msd_fabric = False
    msd_root.fetch_data = MagicMock()  # type: ignore[method-assign]

    _run(msd_root, _endpoint_dict([{"vrfName": "V1"}]))

    msd_root.fetch_data.assert_not_called()
