"""Regression tests for Catalyst Center collector-side Terraform import IDs."""

from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from nac_collector.controller.catalystcenter import CiscoClientCATALYSTCENTER
from nac_collector.github_repo_wrapper import GithubRepoWrapper

pytestmark = pytest.mark.unit


def _client() -> CiscoClientCATALYSTCENTER:
    return CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)


def _join_context() -> dict[str, Any]:
    return {
        "site": [
            {
                "data": [
                    {
                        "id": "site-1",
                        "name": "Krakow",
                        "nameHierarchy": "Global/Poland/Krakow",
                    }
                ]
            }
        ],
        "fabric_site": [{"data": [{"id": "fabric-1", "siteId": "site-1"}]}],
        "network_devices": [
            {"data": [{"id": "device-1", "hostname": "EDGE01.example.test"}]}
        ],
    }


def test_build_import_id_uses_recipe_order_and_trims_values() -> None:
    endpoint = {
        "name": "template",
        "import_id_attributes": [{"field": "projectId"}, {"field": "id"}],
    }

    assert CiscoClientCATALYSTCENTER.build_terraform_import_ids(
        endpoint, {"projectId": " project-1 ", "id": "template-1\n"}, None
    ) == ["project-1", "template-1"]


def test_import_id_preserves_meaningful_internal_spaces() -> None:
    endpoint = {
        "name": "update_authentication_profile",
        "import_id_attributes": [
            {"field": "fabricId"},
            {"field": "authProfileName"},
        ],
    }

    assert CiscoClientCATALYSTCENTER.build_terraform_import_ids(
        endpoint,
        {"fabricId": "fabric-1", "authProfileName": "Closed Authentication"},
        None,
    ) == ["fabric-1", "Closed Authentication"]


def test_attach_keyed_import_ids_resolves_hierarchy_and_composite_value() -> None:
    endpoint = {
        "name": "fabric_l2_virtual_network",
        "import_id_attributes": [{"field": "fabricId"}, {"field": "vlanName"}],
        "import_id_key": {
            "join": [
                {"field": "associatedLayer3VirtualNetworkName"},
                {"site_hierarchy": "fabricId"},
            ],
            "sep": "#_#",
        },
    }
    final_dict = _join_context()
    final_dict[endpoint["name"]] = [
        {
            "data": [
                {
                    "fabricId": "fabric-1",
                    "vlanName": "Campus-VLAN",
                    "associatedLayer3VirtualNetworkName": "Campus",
                }
            ]
        }
    ]

    _client().attach_keyed_import_ids(final_dict, [endpoint])

    assert final_dict[endpoint["name"]][0]["terraform_import_ids"] == {
        "Campus#_#Global/Poland/Krakow": "fabric-1,Campus-VLAN"
    }


def test_attach_keyed_import_ids_descends_handoff_wrapper() -> None:
    endpoint = {
        "name": "fabric_l3_handoff_ip_transit",
        "import_id_attributes": [
            {"field": "networkDeviceId"},
            {"field": "fabricId"},
            {"field": "id"},
        ],
        "import_id_key": {"join": [{"device_hostname": "networkDeviceId"}]},
    }
    final_dict = _join_context()
    final_dict[endpoint["name"]] = [
        {
            "data": [
                {
                    "siteId": "site-1",
                    "response": [
                        {
                            "id": "handoff-1",
                            "fabricId": "fabric-1",
                            "networkDeviceId": "device-1",
                        }
                    ],
                }
            ]
        }
    ]

    _client().attach_keyed_import_ids(final_dict, [endpoint])

    assert final_dict[endpoint["name"]][0]["terraform_import_ids"] == {
        "EDGE01": "device-1,fabric-1,handoff-1"
    }


def test_upstream_per_item_response_shape_remains_keyable() -> None:
    client = _client()
    client.mappings = {}
    client.id_lookup = {
        "/items": {"target_endpoint": "/items/%v", "emit_per_item": True}
    }
    endpoint = {
        "name": "items",
        "endpoint": "/items",
        "import_id_attributes": [{"field": "id"}],
        "import_id_key": {"field": "name"},
    }
    result = {"items": []}

    client.process_endpoint_data(
        endpoint,
        result,
        {"response": [{"id": "id-1", "name": "first"}]},
    )
    client.attach_keyed_import_ids(result, [endpoint])

    assert result["items"] == [
        {
            "data": {"id": "id-1", "name": "first"},
            "endpoint": "/items/id-1",
            "terraform_import_ids": {"first": "id-1"},
        }
    ]


def test_provider_match_id_derives_simple_key() -> None:
    definition = {
        "attributes": [
            {
                "model_name": "name",
                "response_model_name": "ipPoolName",
                "match_id": True,
            }
        ]
    }

    wrapper = GithubRepoWrapper.__new__(GithubRepoWrapper)

    assert wrapper.catc_import_id_key(definition) == {
        "field": "ipPoolName"
    }


def test_import_id_overrides_survive_endpoint_regeneration() -> None:
    wrapper = GithubRepoWrapper.__new__(GithubRepoWrapper)
    endpoints = [
        {"name": "network_profile", "endpoint": "/profiles"},
        {
            "name": "site",
            "endpoint": "/sites",
            "children": [{"name": "aaa_settings", "endpoint": "/aaa"}],
        },
    ]
    overrides = [
        {"name": "network_profile", "import_id_key": {"field": "name"}},
        {
            "name": "aaa_settings",
            "import_id_key": {"join": [{"site_hierarchy": "id"}]},
        },
    ]

    wrapper.apply_import_ids(endpoints, overrides)

    assert endpoints[0]["import_id_key"] == {"field": "name"}
    assert endpoints[1]["children"][0]["import_id_key"] == {
        "join": [{"site_hierarchy": "id"}]
    }


def test_shipped_endpoint_file_keeps_upstream_entries_and_import_metadata() -> None:
    yaml = YAML(typ="safe")
    endpoint_file = (
        Path(__file__).parents[2]
        / "nac_collector"
        / "resources"
        / "endpoints"
        / "catalystcenter.yaml"
    )
    endpoints = yaml.load(endpoint_file)
    by_name = {entry["name"]: entry for entry in endpoints}

    assert len(by_name) == len(endpoints)
    assert "ap_profile" in by_name
    assert by_name["tag"]["import_id_key"] == {"field": "name"}
    assert by_name["virtual_network_to_fabric_site"]["import_id_key"] == {
        "field": "virtualNetworkName"
    }
