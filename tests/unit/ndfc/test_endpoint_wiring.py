import pytest

from nac_collector.controller.ndfc import CiscoClientNDFC
from nac_collector.resource_manager import ResourceManager

pytestmark = pytest.mark.unit


def _endpoint_by_interface_type() -> dict[str, dict]:
    """Map each interface type (child of Discovered_Switches) to its yaml entry."""
    endpoints = ResourceManager.get_packaged_endpoint_data("ndfc")
    assert endpoints, "ndfc.yaml failed to load"

    discovered = next(
        (e for e in endpoints if e.get("name") == "Discovered_Switches"), None
    )
    assert discovered is not None, "Discovered_Switches key missing from ndfc.yaml"

    return {child["name"]: child for child in discovered.get("children", [])}


ENDPOINT_BY_INTERFACE_TYPE = _endpoint_by_interface_type()


def _child_urls_for_interface_type(interface_type: str) -> list[str]:
    entry = ENDPOINT_BY_INTERFACE_TYPE.get(interface_type)
    assert entry is not None, f"{interface_type} not wired into Discovered_Switches"
    child_urls = [c["endpoint"] for c in entry.get("children", [])]
    assert child_urls, f"{interface_type} has no child endpoints"
    return child_urls


@pytest.mark.parametrize(
    "interface_type", CiscoClientNDFC.VPC_PORT_CHANNEL_INTERFACE_TYPES
)
def test_vpc_interfaces_use_vpc_placeholders_in_children_endpoint_urls(interface_type):
    urls = _child_urls_for_interface_type(interface_type)
    assert all("{{vpcPair}}" in url and "{{vPC_name}}" in url for url in urls)


@pytest.mark.parametrize("interface_type", CiscoClientNDFC.SERIAL_INTERFACE_TYPES)
def test_serial_interfaces_use_serial_placeholders_in_children_endpoint_urls(
    interface_type,
):
    urls = _child_urls_for_interface_type(interface_type)
    assert all("{{serialNumber}}" in url and "{{ifName}}" in url for url in urls)


def test_vpc_interfaces_and_serial_interfaces_do_not_overlap():
    overlap = set(CiscoClientNDFC.SERIAL_INTERFACE_TYPES) & set(
        CiscoClientNDFC.VPC_PORT_CHANNEL_INTERFACE_TYPES
    )
    assert not overlap, f"Interface types must be disjoint, but both contain: {overlap}"


def test_routed_ethernet_ports_excludes_numbered_fabric_underlay_links():
    """RoutedEthernetPorts must exclude interfaces carrying the auto-generated
    numbered fabric underlay link policy (int_fabric_num_11_1).
    """
    entry = ENDPOINT_BY_INTERFACE_TYPE.get("RoutedEthernetPorts")
    assert entry is not None, "RoutedEthernetPorts not wired into Discovered_Switches"
    assert "underlayPolicies%21%3Dint_fabric_num_11_1" in entry["endpoint"], (
        "RoutedEthernetPorts endpoint must exclude underlayPolicies=="
        "int_fabric_num_11_1 (numbered fabric underlay p2p links)"
    )


# Port-channel member interface types: parent-endpoint filter template ->
# child nvpairs policyName. Members carry their own per-member policy whose
# CONF holds the physical-port freeform (e.g. "no cdp enable").
MEMBER_INTERFACE_POLICIES = {
    "TrunkPortChannelMembers": "int_port_channel_trunk_member_11_1",
    "vPCTrunkPortChannelMembers": "int_vpc_trunk_po_member_11_1",
    "AccessPortChannelMembers": "int_port_channel_access_member_11_1",
    "vPCAccessPortChannelMembers": "int_vpc_access_po_member_11_1",
}


@pytest.mark.parametrize(
    ("interface_type", "policy_name"), sorted(MEMBER_INTERFACE_POLICIES.items())
)
def test_port_channel_member_endpoints_wired_to_member_policy(
    interface_type, policy_name
):
    """Each member interface type must filter its parent globalInterface query on
    the member policy template and fetch that same policy's nvpairs as its child."""
    entry = ENDPOINT_BY_INTERFACE_TYPE.get(interface_type)
    assert entry is not None, f"{interface_type} not wired into Discovered_Switches"

    # Parent endpoint filters on underlayPolicies==<member policy> (URL-encoded ==).
    assert f"underlayPolicies%3D%3D{policy_name}" in entry["endpoint"], (
        f"{interface_type} parent endpoint must filter on underlayPolicies=={policy_name}"
    )

    # Child nvpairs endpoint must request the same member policy by name.
    child_urls = _child_urls_for_interface_type(interface_type)
    assert all(f"policyName={policy_name}" in url for url in child_urls), (
        f"{interface_type} child nvpairs must use policyName={policy_name}"
    )


def test_port_channel_member_types_are_serial_based():
    """Member policies use a single serialNumber in their nvpairs endpoint, so all
    member interface types must be registered as serial-based (not vpcEntityId)."""
    for interface_type in MEMBER_INTERFACE_POLICIES:
        assert interface_type in CiscoClientNDFC.SERIAL_INTERFACE_TYPES
        assert interface_type not in CiscoClientNDFC.VPC_PORT_CHANNEL_INTERFACE_TYPES
