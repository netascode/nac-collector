"""Import-ID contracts required by the current Catalyst Center model."""

from pathlib import Path

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
    client.fetch_data_pagination = Mock(
        side_effect=lambda path, expected_status_codes=(): responses[path]
    )
    result = client.fetch_data_alternate(
        {"name": "fabric_device", "endpoint": endpoint}
    )
    assert {group["siteId"] for group in result["response"]} == {"parent", "zone"}
