"""Import-ID contracts required by the current Catalyst Center model."""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from nac_collector.controller.catalystcenter import CiscoClientCATALYSTCENTER

RESOURCES = Path(__file__).parents[2] / "nac_collector/resources"


def endpoints():
    return YAML(typ="safe").load(RESOURCES / "endpoints/catalystcenter.yaml")


def find(name, nodes=None):
    for node in endpoints() if nodes is None else nodes:
        if node["name"] == name:
            return node
        result = find(name, node.get("children", []))
        if result:
            return result
    return None


def test_packaged_site_ssid_keeps_import_endpoint_from_pr():
    node = find("wireless_ssid")
    assert node is not None, "PR import collection must retain the site SSID child"
    assert node["endpoint"] == "/wirelessSettings/ssids"


def test_zone_site_identity_is_available_to_import_keys():
    raw = {
        "fabric_site": [{"data": [{"id": "fabric", "siteId": "area"}]}],
        "fabric_zone": [
            {"data": [{"id": "zone", "siteId": "building", "fabricId": "fabric"}]}
        ],
    }
    assert CiscoClientCATALYSTCENTER._build_fabric_to_site_index(raw) == {
        "fabric": "area",
        "zone": "building",
    }


def test_l2_virtual_network_key_uses_vlan_name_not_associated_l3_vn():
    node = find("fabric_l2_virtual_network")
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    raw = {
        "site": [{"data": [{"id": "site", "nameHierarchy": "Global/Campus"}]}],
        "fabric_site": [{"data": [{"id": "fabric", "siteId": "site"}]}],
        "fabric_l2_virtual_network": [
            {
                "data": [
                    {
                        "fabricId": "fabric",
                        "vlanName": "Data-L2",
                        "associatedLayer3VirtualNetworkName": "Data-L3",
                    }
                ]
            }
        ],
    }
    client.attach_keyed_import_ids(raw, [node])
    assert raw["fabric_l2_virtual_network"][0]["terraform_import_ids"] == {
        "Data-L2#_#Global/Campus": "fabric,Data-L2"
    }


@pytest.mark.parametrize(
    "name",
    [
        "floor",
        "planned_access_point_position",
        "wireless_ssid",
        "ap_profile",
        "dot11be_profile",
        "power_profile",
        "anchor_group",
        "wireless_preauth_acl",
        "wireless_profile_policy_tag",
        "wireless_profile_site_tag",
        "fabric_port_channel",
        "fabric_multicast_replication_mode",
        "fabric_multicast_virtual_network",
        "wireless_fabric_multicast",
    ],
)
def test_current_collected_resource_has_a_natural_import_key(name):
    assert find(name).get("import_id_key"), name


def test_provision_variants_keep_bulk_and_individual_ids_distinct():
    endpoint = {
        "name": "provision",
        "import_id_key": {"join": [{"site_hierarchy": "siteId"}]},
        "import_id_attributes": [{"field": "siteId"}],
        "import_id_variants": [
            {
                "import_id_key": {"join": [{"device_hostname": "networkDeviceId"}]},
                "import_id_attributes": [
                    {"field": "siteId"},
                    {"field": "networkDeviceId"},
                ],
            }
        ],
    }
    raw = {
        "site": [{"data": [{"id": "site", "nameHierarchy": "Global/Campus"}]}],
        "network_devices": [
            {"data": [{"id": "device", "hostname": "EDGE.example.test"}]}
        ],
        "provision": [{"data": [{"siteId": "site", "networkDeviceId": "device"}]}],
    }
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    client.attach_keyed_import_ids(raw, [endpoint])
    assert raw["provision"][0]["terraform_import_ids"] == {
        "Global/Campus": "site",
        "EDGE": "site,device",
    }


def test_anycast_parent_zone_and_bulk_ids_do_not_overwrite_each_other():
    raw = {
        "site": [
            {
                "data": [
                    {"id": "area", "nameHierarchy": "Global/Campus"},
                    {"id": "bld", "nameHierarchy": "Global/Campus/Bld"},
                ]
            }
        ],
        "fabric_site": [{"data": [{"id": "fabric", "siteId": "area"}]}],
        "fabric_zone": [{"data": [{"id": "zone", "siteId": "bld"}]}],
        "anycast_gateway": [
            {
                "data": [
                    {"fabricId": f, "virtualNetworkName": "VN", "ipPoolName": "Pool"}
                    for f in ("fabric", "zone")
                ]
            }
        ],
    }
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    client.attach_keyed_import_ids(raw, [find("anycast_gateway")])
    ids = raw["anycast_gateway"][0]["terraform_import_ids"]
    assert ids["Pool"] == "fabric,VN,Pool"
    assert ids["Global/Campus/Bld#_#Pool"] == "zone,VN,Pool"
    assert ids["Global/Campus"] == "fabric"
    assert ids["Global/Campus/Bld"] == "zone"


def test_current_handoff_key_keeps_vlan_prefix():
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    raw = {
        "network_devices": [
            {"data": [{"id": "device", "hostname": "BR.example.test"}]}
        ],
        "fabric_l2_handoff": [
            {
                "data": [
                    {
                        "externalVlanId": 701,
                        "networkDeviceId": "device",
                        "fabricId": "fabric",
                        "interfaceName": "Gi1/0/1",
                        "id": "handoff",
                    }
                ]
            }
        ],
    }
    client.attach_keyed_import_ids(raw, [find("fabric_l2_handoff")])
    assert raw["fabric_l2_handoff"][0]["terraform_import_ids"] == {
        "vlan701/BR/Gi1/0/1": "device,fabric,handoff"
    }


def test_profile_child_key_resolves_parent_name():
    child = {
        "name": "tag",
        "import_id_attributes": [{"source": "parent"}, {"field": "id"}],
        "import_id_key": {
            "join": [{"parent_name": "wireless_profile"}, {"field": "name"}],
            "sep": "/",
        },
    }
    parent = {"name": "wireless_profile", "children": [child]}
    raw = {
        "wireless_profile": [
            {
                "data": [{"id": "profile", "wirelessProfileName": "Campus"}],
                "children": {
                    "tag": [
                        [{"id": "profile", "data": [{"id": "tag", "name": "Policy"}]}]
                    ]
                },
            }
        ]
    }
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    client.attach_keyed_import_ids(raw, [parent])
    assert raw["wireless_profile"][0]["children"]["tag"][0][0][
        "terraform_import_ids"
    ] == {"Campus/Policy": "profile,tag"}


def test_bulk_ip_handoffs_use_device_fabric_id_not_one_member_id():
    raw = {
        "network_devices": [
            {"data": [{"id": "device", "hostname": "BR.example.test"}]}
        ],
        "fabric_l3_handoff_ip_transit": [
            {
                "data": [
                    {"networkDeviceId": "device", "fabricId": "fabric", "id": ident}
                    for ident in ("handoff1", "handoff2")
                ]
            }
        ],
    }
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    client.attach_keyed_import_ids(raw, [find("fabric_l3_handoff_ip_transit")])
    assert raw["fabric_l3_handoff_ip_transit"][0]["terraform_import_ids"] == {
        "BR": "device,fabric"
    }


def test_credential_assignment_import_uses_wrapper_site_for_both_segments():
    raw = {
        "site": [{"data": [{"id": "site", "nameHierarchy": "Global/Campus"}]}],
        "assign_credentials": [
            {
                "data": [
                    {
                        "siteId": "site",
                        "response": [{"key": "credential.cli", "value": []}],
                    }
                ]
            }
        ],
    }
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    client.attach_keyed_import_ids(raw, [find("assign_credentials")])
    assert raw["assign_credentials"][0]["terraform_import_ids"] == {
        "Global/Campus": "site,site"
    }


def test_vn_assignment_expands_each_fabric_and_zone_into_its_own_import():
    raw = {
        "site": [
            {
                "data": [
                    {"id": "area", "nameHierarchy": "Global/Campus"},
                    {"id": "bld", "nameHierarchy": "Global/Campus/Bld"},
                ]
            }
        ],
        "fabric_site": [{"data": [{"id": "fabric", "siteId": "area"}]}],
        "fabric_zone": [{"data": [{"id": "zone", "siteId": "bld"}]}],
        "virtual_network_to_fabric_site": [
            {"data": [{"virtualNetworkName": "VN", "fabricIds": ["fabric", "zone"]}]}
        ],
    }
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    client.attach_keyed_import_ids(raw, [find("virtual_network_to_fabric_site")])
    assert raw["virtual_network_to_fabric_site"][0]["terraform_import_ids"] == {
        "VN#_#Global/Campus": "VN,fabric",
        "VN#_#Global/Campus/Bld": "VN,zone",
    }


def test_list_cannot_be_stringified_into_a_scalar_import_id():
    endpoint = {"name": "test", "import_id_attributes": [{"field": "id"}]}
    assert (
        CiscoClientCATALYSTCENTER.build_terraform_import_ids(
            endpoint, {"id": ["a", "b"]}, None
        )
        is None
    )


@pytest.mark.parametrize(
    "name",
    [
        "banner_settings",
        "dhcp_settings",
        "dns_settings",
        "ntp_settings",
        "telemetry_settings",
        "timezone_settings",
    ],
)
def test_site_settings_retain_parent_import_id_after_generation(name):
    node = find(name)
    assert CiscoClientCATALYSTCENTER.build_terraform_import_ids(node, {}, "site") == [
        "site"
    ]


@pytest.mark.parametrize("name", ["anchor_group", "wireless_preauth_acl"])
def test_wireless_uuid_import_matches_provider_read_lookup(name):
    assert CiscoClientCATALYSTCENTER.build_terraform_import_ids(
        find(name),
        {"id": "uuid", "anchorGroupName": "Guests", "aclName": "GuestsACL"},
        None,
    ) == ["uuid"]


def test_vlan_ssid_bulk_import_uses_collected_wrapper_fabric_id():
    assert CiscoClientCATALYSTCENTER.build_terraform_import_ids(
        find("vlanToSsids"), {"siteId": "fabric"}, None
    ) == ["fabric"]


def test_zone_device_import_collection_fetches_parent_and_zone_sources():
    from unittest.mock import Mock

    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    endpoint = "/fabricDevices"
    client.id_lookup = {
        endpoint: {
            "source_endpoint": "/fabricSites",
            "additional_source_endpoints": ["/fabricZones"],
            "source_key": "id",
            "target_endpoint": "/fabricDevices?fabricId=%v",
            "target_key": "siteId",
        }
    }
    responses = {
        "/fabricSites": {"response": [{"id": "parent"}]},
        "/fabricZones": {"response": [{"id": "zone"}]},
        "/fabricDevices?fabricId=parent": {"response": [{"networkDeviceId": "border"}]},
        "/fabricDevices?fabricId=zone": {"response": [{"networkDeviceId": "edge"}]},
    }
    client.fetch_data_pagination = Mock(side_effect=lambda path: responses[path])
    result = client.fetch_data_alternate(
        {"name": "fabric_device", "endpoint": endpoint}
    )
    assert {group["siteId"] for group in result["response"]} == {"parent", "zone"}
