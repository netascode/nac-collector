"""Interface collection from the ND Manage v1 API (configOnly interface intent).

Fixtures in fixtures/manage_interfaces.json are trimmed real responses from
ND 4.3 (NDFC 12.6) and ND 4.2 (NDFC 12.5), including the int_trunk_host /
int_routed_host template parameters used to recognise unused-port placeholders.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nac_collector.controller.ndfc import CiscoClientNDFC
from nac_collector.resource_manager import ResourceManager

pytestmark = pytest.mark.unit

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "manage_interfaces.json").read_text()
)
TEMPLATE_PREFIX = "/api/v1/manage/configTemplates/"


def _policy(record: dict[str, Any]) -> dict[str, Any]:
    return ((record.get("configData") or {}).get("networkOS") or {}).get("policy") or {}


def _names(records: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(r["interfaceName"], _policy(r).get("policyType")) for r in records]


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


def _fake_controller(
    templates: dict[str, Any] | None,
    pages_by_serial: dict[str, list[dict[str, Any]] | None],
) -> MagicMock:
    """fetch_data replacement serving template parameters and paged interface lists."""

    def fetch_data(url: str) -> Any:
        if url.startswith(TEMPLATE_PREFIX):
            name = url[len(TEMPLATE_PREFIX) :].split("/")[0]
            return (templates or {}).get(name)
        for serial, records in pages_by_serial.items():
            if f"/switches/{serial}/interfaces" in url:
                if records is None:
                    return None
                return {
                    "interfaces": records,
                    "meta": {"counts": {"remaining": 0, "total": len(records)}},
                }
        raise AssertionError(f"unexpected url {url}")

    return MagicMock(side_effect=fetch_data)


class TestEndpointDefinition:
    def test_discovered_switches_collects_interfaces_from_manage_api(self):
        endpoints = ResourceManager.get_packaged_endpoint_data("ndfc")
        discovered = next(e for e in endpoints if e["name"] == "Discovered_Switches")
        children = discovered.get("children", [])
        assert [c["name"] for c in children] == ["manage_interfaces"]
        url = children[0]["endpoint"]
        assert url.startswith("/api/v1/manage/fabrics/%v/switches/{{serialNumber}}/")
        assert "configOnly=true" in url

    def test_no_legacy_global_interface_endpoints_left(self):
        endpoints = ResourceManager.get_packaged_endpoint_data("ndfc")
        assert "globalInterface" not in json.dumps(endpoints)


class TestPagination:
    def test_reads_pages_until_nothing_remains(self, ndfc_client):
        first = [{"interfaceName": f"Ethernet1/{i}"} for i in range(1, 101)]
        second = [{"interfaceName": "Ethernet1/101"}]
        ndfc_client.fetch_data = MagicMock(
            side_effect=[
                {"interfaces": first, "meta": {"counts": {"remaining": 1}}},
                {"interfaces": second, "meta": {"counts": {"remaining": 0}}},
            ]
        )
        records = ndfc_client._fetch_manage_list("/api/x?configOnly=true", "interfaces")
        assert len(records) == 101
        urls = [c.args[0] for c in ndfc_client.fetch_data.call_args_list]
        assert urls == [
            "/api/x?configOnly=true&max=100&offset=0",
            "/api/x?configOnly=true&max=100&offset=100",
        ]

    def test_single_page(self, ndfc_client):
        ndfc_client.fetch_data = MagicMock(
            return_value={"interfaces": [{"interfaceName": "mgmt0"}], "meta": {}}
        )
        assert len(ndfc_client._fetch_manage_list("/api/x", "interfaces")) == 1
        assert ndfc_client.fetch_data.call_args.args[0] == "/api/x?max=100&offset=0"

    def test_empty_page_stops_even_if_remaining_reported(self, ndfc_client):
        ndfc_client.fetch_data = MagicMock(
            return_value={"interfaces": [], "meta": {"counts": {"remaining": 5}}}
        )
        assert ndfc_client._fetch_manage_list("/api/x", "interfaces") == []
        assert ndfc_client.fetch_data.call_count == 1

    @pytest.mark.parametrize("response", [None, [], {"meta": {}}, {"interfaces": {}}])
    def test_unreadable_response_returns_none(self, ndfc_client, response):
        ndfc_client.fetch_data = MagicMock(return_value=response)
        assert ndfc_client._fetch_manage_list("/api/x", "interfaces") is None


class TestFiltering:
    @pytest.mark.parametrize("release", ["nd43", "nd42"])
    def test_drops_only_placeholders_and_records_without_policy(
        self, ndfc_client, release
    ):
        records = FIXTURES[f"{release}_leaf"]
        ndfc_client.fetch_data = _fake_controller(FIXTURES[f"{release}_templates"], {})
        drop_counts: dict[str, int] = {}
        kept = ndfc_client._filter_manage_interfaces(records, drop_counts)

        expected = [
            (r["interfaceName"], _policy(r)["policyType"])
            for r in records
            if _policy(r).get("policyType")
            and _policy(r)["policyType"] not in ("trunkHost", "routedHost")
        ]
        assert _names(kept) == expected
        assert drop_counts["placeholder"] == sum(
            _policy(r).get("policyType") in ("trunkHost", "routedHost") for r in records
        )
        assert drop_counts["no_policy"] == sum(
            not _policy(r).get("policyType") for r in records
        )

    def test_keeps_fabric_managed_and_user_defined_policies(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd42_templates"], {})
        kept = ndfc_client._filter_manage_interfaces(FIXTURES["nd42_leaf"], {})
        policy_types = {p for _, p in _names(kept)}
        assert {"userDefined", "underlayLoopback"} <= policy_types

    def test_configured_routed_ports_are_kept(self, ndfc_client):
        """Spine E1/21-23 carry config (description/IP/MTU, partly undeployed);
        E1/30-31 are unused placeholders."""
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        drop_counts: dict[str, int] = {}
        kept = ndfc_client._filter_manage_interfaces(
            FIXTURES["nd43_spine"], drop_counts
        )
        assert sorted(_names(kept)) == [
            ("Ethernet1/21", "routedHost"),
            ("Ethernet1/21.100", "subinterface"),
            ("Ethernet1/22", "routedHost"),
            ("Ethernet1/22.200", "subinterface"),
            ("Ethernet1/23", "routedHost"),
        ]
        assert drop_counts == {"placeholder": 2}

    def test_any_non_default_template_parameter_keeps_the_port(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        placeholder = next(
            r for r in FIXTURES["nd43_leaf"] if _policy(r)["policyType"] == "trunkHost"
        )
        for field, value in [
            ("description", "server-1"),
            ("allowedVlans", "10-20"),
            ("adminState", False),
            ("nativeVlan", 10),
        ]:
            policy = {**_policy(placeholder), field: value}
            assert not ndfc_client._is_placeholder_interface(policy), field

    def test_fields_outside_the_template_are_ignored(self, ndfc_client):
        """ptp is not an int_trunk_host parameter (string on ND 4.3, bool on 4.2)."""
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        placeholder = next(
            r for r in FIXTURES["nd43_leaf"] if _policy(r)["policyType"] == "trunkHost"
        )
        for ptp in ("false", False, True):
            assert ndfc_client._is_placeholder_interface(
                {**_policy(placeholder), "ptp": ptp}
            )

    def test_template_parameters_are_read_once_per_template(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        ndfc_client._filter_manage_interfaces(FIXTURES["nd43_leaf"], {})
        ndfc_client._filter_manage_interfaces(FIXTURES["nd43_spine"], {})
        template_calls = [
            c.args[0]
            for c in ndfc_client.fetch_data.call_args_list
            if c.args[0].startswith(TEMPLATE_PREFIX)
        ]
        assert sorted(template_calls) == [
            "/api/v1/manage/configTemplates/int_routed_host/parameters",
            "/api/v1/manage/configTemplates/int_trunk_host/parameters",
        ]

    def test_unreadable_template_keeps_ports_and_warns_once(self, ndfc_client, caplog):
        ndfc_client.fetch_data = _fake_controller(None, {})
        records = FIXTURES["nd43_leaf"] + FIXTURES["nd43_spine"]
        drop_counts: dict[str, int] = {}
        kept = ndfc_client._filter_manage_interfaces(records, drop_counts)
        assert "placeholder" not in drop_counts
        assert len(kept) == sum(bool(_policy(r).get("policyType")) for r in records)
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 2  # one per template, not per port

    def test_string_booleans_are_normalised(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        kept = ndfc_client._filter_manage_interfaces(
            json.loads(json.dumps(FIXTURES["nd43_dot1q"])), {}
        )
        assert _policy(kept[0])["ptp"] is False


class TestProcessSwitchInterfaces:
    def _endpoint(self) -> dict[str, Any]:
        endpoints = ResourceManager.get_packaged_endpoint_data("ndfc")
        return next(e for e in endpoints if e["name"] == "Discovered_Switches")

    def test_records_are_attached_to_each_switch(self, ndfc_client, caplog):
        caplog.set_level("INFO")
        leaf = FIXTURES["nd43_leaf"]
        spine = FIXTURES["nd43_spine"]
        ndfc_client.fetch_data = _fake_controller(
            FIXTURES["nd43_templates"], {"SN-LEAF": leaf, "SN-SPINE": spine}
        )
        switches = [
            {"logicalName": "leaf1", "serialNumber": "SN-LEAF", "fabricName": "FAB1"},
            {"logicalName": "spine1", "serialNumber": "SN-SPINE", "fabricName": "FAB1"},
            {"logicalName": "other", "serialNumber": "SN-OTHER", "fabricName": "FAB2"},
        ]
        endpoint_dict = {"Discovered_Switches": [{"fabric": "FAB1", "data": switches}]}

        ndfc_client._process_switch_interfaces(self._endpoint(), endpoint_dict)

        urls = [c.args[0] for c in ndfc_client.fetch_data.call_args_list]
        assert (
            "/api/v1/manage/fabrics/FAB1/switches/SN-LEAF/interfaces"
            "?configOnly=true&max=100&offset=0" in urls
        )
        assert not any("SN-OTHER" in u for u in urls)
        assert "manage_interfaces" not in switches[2]
        assert len(switches[0]["manage_interfaces"]) == 16
        assert len(switches[1]["manage_interfaces"]) == 5
        summary = [
            r.getMessage() for r in caplog.records if "collected" in r.getMessage()
        ]
        assert summary == [
            "Fabric FAB1: collected 21 interface records "
            "(dropped 4 unused-port placeholders, 3 without a policy)"
        ]

    def test_failed_fetch_leaves_empty_list(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(
            FIXTURES["nd43_templates"], {"SN-LEAF": None}
        )
        switch = {
            "logicalName": "leaf1",
            "serialNumber": "SN-LEAF",
            "fabricName": "FAB1",
        }
        endpoint_dict = {"Discovered_Switches": [{"fabric": "FAB1", "data": [switch]}]}
        ndfc_client._process_switch_interfaces(self._endpoint(), endpoint_dict)
        assert switch["manage_interfaces"] == []


class TestHostInterfaceAdminState:
    """Fabric "Unshut Host Interfaces by Default" = false: NDFC creates unused-port
    policies with adminState false (live ND 4.3 fabric with HOST_INTF_ADMIN_STATE=false)."""

    def test_shut_placeholders_dropped_when_fabric_shuts_host_ports(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        drop_counts: dict[str, int] = {}
        kept = ndfc_client._filter_manage_interfaces(
            FIXTURES["nd43_unshut_false"], drop_counts, "false"
        )
        assert [p for _, p in _names(kept)] == ["accessHost", "accessHost"]
        assert drop_counts == {"placeholder": 3}

    def test_shut_port_is_intent_when_fabric_unshuts_host_ports(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        for admin_default in ("true", None):
            drop_counts: dict[str, int] = {}
            kept = ndfc_client._filter_manage_interfaces(
                FIXTURES["nd43_unshut_false"], drop_counts, admin_default
            )
            assert len(kept) == 5 and not drop_counts

    def test_admin_state_read_from_fabric_configuration(self, ndfc_client):
        endpoint_dict = {
            "Fabric_Configuration": [
                {
                    "data": {
                        "fabricName": "A",
                        "nvPairs": {"HOST_INTF_ADMIN_STATE": "true"},
                    }
                },
                {
                    "data": {
                        "fabricName": "B",
                        "nvPairs": {"HOST_INTF_ADMIN_STATE": "false"},
                    }
                },
                {"data": {"fabricName": "C", "nvPairs": {}}},
            ]
        }
        assert ndfc_client._host_interface_admin_state(endpoint_dict, "A") == "true"
        assert ndfc_client._host_interface_admin_state(endpoint_dict, "B") == "false"
        assert ndfc_client._host_interface_admin_state(endpoint_dict, "C") is None
        assert ndfc_client._host_interface_admin_state({}, "A") is None

    def test_switch_processing_uses_the_switch_fabric_setting(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(
            FIXTURES["nd43_templates"], {"SN1": FIXTURES["nd43_unshut_false"]}
        )
        switch = {"logicalName": "leaf1", "serialNumber": "SN1", "fabricName": "FAB1"}
        endpoint_dict = {
            "Fabric_Configuration": [
                {
                    "data": {
                        "fabricName": "FAB1",
                        "nvPairs": {"HOST_INTF_ADMIN_STATE": "false"},
                    }
                }
            ],
            "Discovered_Switches": [{"fabric": "FAB1", "data": [switch]}],
        }
        endpoints = ResourceManager.get_packaged_endpoint_data("ndfc")
        discovered = next(e for e in endpoints if e["name"] == "Discovered_Switches")
        ndfc_client._process_switch_interfaces(discovered, endpoint_dict)
        assert [p for _, p in _names(switch["manage_interfaces"])] == [
            "accessHost",
            "accessHost",
        ]


class TestFabricLinks:
    """Manage v1 /links of a live ND 4.3 MSD member fabric plus a NAC-created planned
    link; link template parameters (defaults) from the same ND."""

    @staticmethod
    def _client(ndfc_client, templates=None):
        ndfc_client.fetch_data = _fake_controller(
            FIXTURES["nd43_templates"] if templates is None else templates, {}
        )
        return ndfc_client

    @staticmethod
    def _auto_link(**inputs):
        """A spine/leaf link as NDFC creates it for a discovered cable."""
        template_inputs = {
            "interfaceAdminState": True,
            "mtu": 9216,
            "srcIp": "10.0.0.1",
            "dstIp": "10.0.0.2",
            "srcInterfaceDescription": "connected-to-leaf1-Ethernet1/1",
            "dstInterfaceDescription": "connected-to-spine1-Ethernet1/1",
            **inputs,
        }
        return {
            "srcFabricName": "F",
            "dstFabricName": "F",
            "portChannel": False,
            "memberLink": False,
            "linkPlanned": False,
            "configData": {"policyType": "numbered", "templateInputs": template_inputs},
        }

    def test_planned_link_kept_and_default_discovered_links_skipped(self, ndfc_client):
        kept = self._client(ndfc_client)._filter_fabric_links(
            FIXTURES["nd43_links"], "CERT43-R3-S1"
        )
        assert [(lk["srcInterfaceName"], lk["linkPlanned"]) for lk in kept] == [
            ("Ethernet1/40", True)
        ]

    def test_multisite_underlay_and_policyless_links_are_dropped(self, ndfc_client):
        client = self._client(ndfc_client)
        kept = client._filter_fabric_links(FIXTURES["nd43_links"], "CERT43-R3-S1")
        policies = {
            (lk.get("configData") or {}).get("policyType")
            for lk in FIXTURES["nd43_links"]
            if lk not in kept
        }
        assert {"multisiteUnderlay", None, "numbered"} <= policies

    # Real Manage v1 record (NDFC 12.6.0.267 + SMU) of the pre-provision link NAC creates
    # for the peer link of a pre-provisioned vPC pair.
    PREPROVISION_LINK = {
        "configData": {"policyType": "preprovision", "templateInputs": {}},
        "displayName": "Pre-provision",
        "srcFabricName": "PP",
        "dstFabricName": "PP",
        "srcSwitchName": "A-AZ1-Gold-Leaf1",
        "srcSwitchId": "TESTPPR1003",
        "srcInterfaceName": "Ethernet1/5",
        "dstSwitchName": "A-AZ1-Gold-Leaf2",
        "dstSwitchId": "TESTPPR1004",
        "dstInterfaceName": "Ethernet1/1",
        "linkDiscovered": False,
        "linkPlanned": True,
        "linkPresent": False,
        "linkState": "neighborMissing",
        "linkType": "lan_planned_link",
        "memberLink": False,
        "portChannel": False,
    }

    def test_preprovision_link_is_kept(self, ndfc_client):
        client = self._client(ndfc_client)
        assert client._filter_fabric_links([self.PREPROVISION_LINK], "PP") == [
            self.PREPROVISION_LINK
        ]

    def test_preprovision_link_to_other_fabric_is_dropped(self, ndfc_client):
        client = self._client(ndfc_client)
        link = {**self.PREPROVISION_LINK, "dstFabricName": "OTHER"}
        assert client._filter_fabric_links([link], "PP") == []

    def test_other_fabric_name_keeps_nothing(self, ndfc_client):
        client = self._client(ndfc_client)
        assert client._filter_fabric_links(FIXTURES["nd43_links"], "OTHER") == []

    @pytest.mark.parametrize(
        "inputs",
        [
            {"mtu": 9000},
            {"interfaceAdminState": False},
            {"srcInterfaceConfig": "load-interval counter 1 30"},
            {"dstInterfaceConfig": "no shutdown"},
        ],
    )
    def test_discovered_link_with_user_setting_is_kept(self, ndfc_client, inputs):
        link = self._auto_link(**inputs)
        assert self._client(ndfc_client)._filter_fabric_links([link], "F") == [link]

    def test_discovered_link_with_template_defaults_is_skipped(self, ndfc_client):
        """Pool-allocated IPs and NDFC-filled descriptions do not select a link."""
        links = [
            self._auto_link(),
            self._auto_link(srcInterfaceDescription="custom text"),
            self._auto_link(srcInterfaceConfig="", dstInterfaceConfig=None),
        ]
        assert self._client(ndfc_client)._filter_fabric_links(links, "F") == []

    def test_link_template_parameters_read_once(self, ndfc_client):
        client = self._client(ndfc_client)
        client._filter_fabric_links([self._auto_link(), self._auto_link()], "F")
        template_calls = [
            c.args[0]
            for c in client.fetch_data.call_args_list
            if c.args[0].startswith(TEMPLATE_PREFIX)
        ]
        assert template_calls == [
            "/api/v1/manage/configTemplates/int_intra_fabric_num_link/parameters"
        ]

    def test_unreadable_link_template_keeps_the_link(self, ndfc_client):
        link = self._auto_link()
        assert self._client(ndfc_client, templates={})._filter_fabric_links(
            [link], "F"
        ) == [link]

    @pytest.mark.parametrize("policy_type", ["unnumbered", "ipv6LinkLocal"])
    def test_other_intra_fabric_policies_planned_link_kept(
        self, ndfc_client, policy_type
    ):
        link = {
            "srcFabricName": "F",
            "dstFabricName": "F",
            "portChannel": False,
            "memberLink": False,
            "linkPlanned": True,
            "configData": {"policyType": policy_type},
        }
        assert self._client(ndfc_client)._filter_fabric_links([link], "F") == [link]

    def test_unnumbered_default_link_is_skipped(self, ndfc_client):
        link = self._auto_link()
        link["configData"] = {
            "policyType": "unnumbered",
            "templateInputs": {"interfaceAdminState": True, "mtu": 9216},
        }
        assert self._client(ndfc_client)._filter_fabric_links([link], "F") == []


class TestManageListEndpoints:
    def test_endpoints_are_defined(self):
        endpoints = {
            e["name"]: e["endpoint"]
            for e in ResourceManager.get_packaged_endpoint_data("ndfc")
        }
        assert endpoints["Fabric_Resources"] == "/api/v1/manage/fabrics/%v/resources"
        assert endpoints["Fabric_Links"] == "/api/v1/manage/links?fabricName=%v"

    def test_single_site_reads_all_pages_and_filters_links(self, ndfc_client):
        links = FIXTURES["nd43_links"]
        ndfc_client.fabric_name = "CERT43-R3-S1"
        pages = iter(
            [
                {
                    "links": links[:10],
                    "meta": {"counts": {"remaining": len(links) - 10}},
                },
                {"links": links[10:], "meta": {"counts": {"remaining": 0}}},
            ]
        )
        templates = _fake_controller(FIXTURES["nd43_templates"], {})
        ndfc_client.fetch_data = MagicMock(
            side_effect=lambda url: (
                templates(url) if url.startswith(TEMPLATE_PREFIX) else next(pages)
            )
        )
        result: dict[str, list] = {"Fabric_Links": []}
        endpoint = {
            "name": "Fabric_Links",
            "endpoint": "/api/v1/manage/links?fabricName=%v",
        }
        ndfc_client._process_endpoint_single_site(endpoint, result)
        urls = [
            c.args[0]
            for c in ndfc_client.fetch_data.call_args_list
            if not c.args[0].startswith(TEMPLATE_PREFIX)
        ]
        assert urls == [
            "/api/v1/manage/links?fabricName=CERT43-R3-S1&max=100&offset=0",
            "/api/v1/manage/links?fabricName=CERT43-R3-S1&max=100&offset=10",
        ]
        assert result["Fabric_Links"][0]["fabric"] == "CERT43-R3-S1"
        assert [lk["srcInterfaceName"] for lk in result["Fabric_Links"][0]["data"]] == [
            "Ethernet1/40"
        ]

    def test_resources_are_collected_unfiltered(self, ndfc_client):
        resources = [
            {"poolName": "VPC_DOMAIN_ID", "entityName": "A~B", "resourceValue": "10"},
            {
                "poolName": "LOOPBACK0_IP_POOL",
                "entityName": "A",
                "resourceValue": "10.0.0.1",
            },
        ]
        ndfc_client.fabric_name = "F"
        ndfc_client.fetch_data = MagicMock(
            return_value={"resources": resources, "meta": {"counts": {"remaining": 0}}}
        )
        result: dict[str, list] = {"Fabric_Resources": []}
        ndfc_client._process_endpoint_single_site(
            {
                "name": "Fabric_Resources",
                "endpoint": "/api/v1/manage/fabrics/%v/resources",
            },
            result,
        )
        assert result["Fabric_Resources"][0]["data"] == resources

    @pytest.mark.parametrize(
        "name",
        ["Fabric_Links", "Discovered_Switches", "TorPairing"],
    )
    def test_msd_root_is_skipped(self, ndfc_client, name):
        ndfc_client.msd_topology = {"all_fabrics": ["MSD1"]}
        ndfc_client._is_msd_root_fabric = MagicMock(return_value=True)
        ndfc_client._process_endpoint_single_site = MagicMock()
        ndfc_client._process_endpoint_for_msd_fabrics(
            {"name": name, "endpoint": "/x"}, {name: []}
        )
        ndfc_client._process_endpoint_single_site.assert_not_called()

    def test_msd_root_resources_are_collected(self, ndfc_client):
        """The MSD root's resource manager holds the members' BGW anycast VIPs."""
        ndfc_client.msd_topology = {"all_fabrics": ["MSD1"]}
        ndfc_client._is_msd_root_fabric = MagicMock(return_value=True)
        ndfc_client._process_endpoint_single_site = MagicMock()
        ndfc_client._process_endpoint_for_msd_fabrics(
            {"name": "Fabric_Resources", "endpoint": "/x"}, {"Fabric_Resources": []}
        )
        ndfc_client._process_endpoint_single_site.assert_called_once()


class TestFabricLinkFabricDefaults:
    """NDFC creates links with the fabric "Intra Fabric Interface MTU" (FABRIC_MTU),
    not the template default 9216 (live ND 4.3 fabric with FABRIC_MTU 9100)."""

    def test_link_with_fabric_mtu_is_skipped(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        link = TestFabricLinks._auto_link(mtu=9100)
        assert ndfc_client._filter_fabric_links([link], "F", {"mtu": "9100"}) == []

    def test_link_differing_from_fabric_mtu_is_kept(self, ndfc_client):
        ndfc_client.fetch_data = _fake_controller(FIXTURES["nd43_templates"], {})
        link = TestFabricLinks._auto_link(mtu=9216)
        assert ndfc_client._filter_fabric_links([link], "F", {"mtu": "9100"}) == [link]

    def test_fabric_mtu_read_from_collected_fabric_configuration(self, ndfc_client):
        links = [TestFabricLinks._auto_link(mtu=9100)]
        templates = _fake_controller(FIXTURES["nd43_templates"], {})
        ndfc_client.fetch_data = MagicMock(
            side_effect=lambda url: (
                templates(url)
                if url.startswith(TEMPLATE_PREFIX)
                else {"links": links, "meta": {"counts": {"remaining": 0}}}
            )
        )
        ndfc_client.fabric_name = "F"
        result: dict[str, list] = {
            "Fabric_Configuration": [
                {"data": {"fabricName": "F", "nvPairs": {"FABRIC_MTU": "9100"}}}
            ],
            "Fabric_Links": [],
        }
        ndfc_client._process_endpoint_single_site(
            {"name": "Fabric_Links", "endpoint": "/api/v1/manage/links?fabricName=%v"},
            result,
        )
        assert result["Fabric_Links"][0]["data"] == []
