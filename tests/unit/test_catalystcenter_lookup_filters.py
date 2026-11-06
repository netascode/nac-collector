from unittest.mock import MagicMock, patch

import pytest

from nac_collector.controller.catalystcenter import CiscoClientCATALYSTCENTER

pytestmark = pytest.mark.unit


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


NETWORK_DEVICES = {
    "response": [
        {"id": "wlc-1", "family": "Wireless Controller"},
        {"id": "switch-1", "family": "Switches and Hubs"},
        {"id": "ap-1", "family": "Unified AP"},
    ]
}


class TestMatchesFilter:
    def test_single_value_match(self):
        assert CiscoClientCATALYSTCENTER._matches_filter(
            {"family": "Wireless Controller"}, {"family": "Wireless Controller"}
        )

    def test_single_value_mismatch(self):
        assert not CiscoClientCATALYSTCENTER._matches_filter(
            {"family": "Unified AP"}, {"family": "Wireless Controller"}
        )

    def test_list_of_allowed_values(self):
        assert CiscoClientCATALYSTCENTER._matches_filter(
            {"family": "Unified AP"}, {"family": ["Wireless Controller", "Unified AP"]}
        )

    def test_missing_field_does_not_match(self):
        assert not CiscoClientCATALYSTCENTER._matches_filter(
            {"id": "x"}, {"family": "Wireless Controller"}
        )

    def test_all_fields_must_match(self):
        assert not CiscoClientCATALYSTCENTER._matches_filter(
            {"family": "Wireless Controller", "role": "ACCESS"},
            {"family": "Wireless Controller", "role": "CORE"},
        )


WIRELESS_DEVICES = {
    "response": [
        {"id": "wlc-1", "family": "Wireless Controller"},
        {"id": "ewc-switch", "family": "Switches and Hubs"},
        {"id": "edge-switch", "family": "Switches and Hubs"},
        {"id": "ap-1", "family": "Unified AP"},
    ]
}
FABRIC_SITES = {"response": [{"id": "fabric-1"}, {"id": "fabric-2"}]}
FABRIC_DEVICES_URL = (
    "/dna/intent/api/v1/sda/fabricDevices?fabricId={}"
    "&deviceRoles=WIRELESS_CONTROLLER_NODE"
)


def _fake_fetch(responses):
    """Return a fetch_data_pagination stand-in that answers by exact URL."""

    def fetch(url):
        return responses.get(url)

    return fetch


class TestWirelessControllerSourceFilter:
    @pytest.mark.parametrize("kind", ["primary", "secondary"])
    def test_wlcs_and_fabric_wireless_nodes_are_queried(self, catalyst_client, kind):
        endpoint = {
            "name": f"wireless_controller_{kind}_managed_ap_locations",
            "endpoint": (
                f"/dna/intent/api/v1/wirelessControllers/%v/{kind}ManagedApLocations"
            ),
        }
        target = (
            "/dna/intent/api/v1/wirelessControllers/{}/" + kind + "ManagedApLocations"
        )
        responses = {
            "/dna/intent/api/v1/network-device": WIRELESS_DEVICES,
            "/dna/intent/api/v1/sda/fabricSites?limit=500": FABRIC_SITES,
            FABRIC_DEVICES_URL.format("fabric-1"): {
                "response": [{"networkDeviceId": "ewc-switch"}]
            },
            FABRIC_DEVICES_URL.format("fabric-2"): {"response": []},
            target.format("wlc-1"): {"response": {"managedApLocations": [1]}},
            target.format("ewc-switch"): {"response": {"managedApLocations": [2]}},
        }

        with patch.object(
            catalyst_client,
            "fetch_data_pagination",
            side_effect=_fake_fetch(responses),
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(endpoint)

        requested = [c.args[0] for c in mock_fetch.call_args_list]
        assert target.format("edge-switch") not in requested
        assert target.format("ap-1") not in requested
        assert result == {
            "response": [
                {"managedApLocations": [1], "deviceId": "wlc-1"},
                {"managedApLocations": [2], "deviceId": "ewc-switch"},
            ]
        }

    def test_fabric_lookup_failure_still_queries_family_matches(self, catalyst_client):
        endpoint = {
            "name": "wireless_controller_primary_managed_ap_locations",
            "endpoint": (
                "/dna/intent/api/v1/wirelessControllers/%v/primaryManagedApLocations"
            ),
        }
        target = "/dna/intent/api/v1/wirelessControllers/{}/primaryManagedApLocations"
        responses = {
            "/dna/intent/api/v1/network-device": WIRELESS_DEVICES,
            target.format("wlc-1"): {"response": {"managedApLocations": [1]}},
        }

        with patch.object(
            catalyst_client,
            "fetch_data_pagination",
            side_effect=_fake_fetch(responses),
        ):
            result = catalyst_client.fetch_data_alternate(endpoint)

        assert result == {
            "response": [{"managedApLocations": [1], "deviceId": "wlc-1"}]
        }


class TestDeviceDetailLookup:
    def test_device_detail_is_queried_per_device(self, catalyst_client):
        endpoint = {
            "name": "device_detail",
            "endpoint": "/dna/intent/api/v1/device-detail",
        }
        details = [
            {"response": {"nwDeviceName": name}} for name in ("wlc", "switch", "ap")
        ]

        with patch.object(
            catalyst_client,
            "fetch_data_pagination",
            side_effect=[NETWORK_DEVICES, *details],
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(endpoint)

        requested = [c.args[0] for c in mock_fetch.call_args_list]
        assert requested == [
            "/dna/intent/api/v1/network-device",
            "/dna/intent/api/v1/device-detail?identifier=uuid&searchBy=wlc-1",
            "/dna/intent/api/v1/device-detail?identifier=uuid&searchBy=switch-1",
            "/dna/intent/api/v1/device-detail?identifier=uuid&searchBy=ap-1",
        ]
        assert result == {
            "response": [
                {"nwDeviceName": "wlc", "deviceId": "wlc-1"},
                {"nwDeviceName": "switch", "deviceId": "switch-1"},
                {"nwDeviceName": "ap", "deviceId": "ap-1"},
            ]
        }


class TestAuthenticationProfileMembershipFilter:
    ENDPOINT = {
        "name": "fabric_authentication_profile",
        "endpoint": "/dna/intent/api/v1/business/sda/authentication-profile",
    }
    SITES = {
        "response": [
            {"id": "site-global", "groupNameHierarchy": "Global"},
            {"id": "site-area", "groupNameHierarchy": "Global/Area"},
            {"id": "site-fabric", "groupNameHierarchy": "Global/Area/Fabric"},
        ]
    }

    def test_only_fabric_sites_are_queried(self, catalyst_client):
        fabric_sites = {"response": [{"id": "fabric-1", "siteId": "site-fabric"}]}
        profile = {"response": [{"authenticateTemplateName": "No Authentication"}]}

        with patch.object(
            catalyst_client,
            "fetch_data_pagination",
            side_effect=[self.SITES, fabric_sites, profile],
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(self.ENDPOINT)

        requested = [c.args[0] for c in mock_fetch.call_args_list]
        assert requested == [
            "/dna/intent/api/v2/site",
            "/dna/intent/api/v1/sda/fabricSites?limit=500",
            "/dna/intent/api/v1/business/sda/authentication-profile"
            "?siteNameHierarchy=Global/Area/Fabric",
        ]
        assert result == {
            "response": [
                {
                    "siteNameHierarchy": "Global/Area/Fabric",
                    "data": [{"authenticateTemplateName": "No Authentication"}],
                }
            ]
        }

    def test_site_name_spaces_are_encoded_not_stripped(self, catalyst_client):
        sites = {
            "response": [
                {
                    "id": "site-1",
                    "groupNameHierarchy": "Global/Area/Tail Site 1 (SA-14)\n",
                }
            ]
        }
        fabric_sites = {"response": [{"id": "fabric-1", "siteId": "site-1"}]}
        profile = {"siteNameHierarchy": "Global/Area/Tail Site 1 (SA-14)"}

        with patch.object(
            catalyst_client,
            "fetch_data_pagination",
            side_effect=[sites, fabric_sites, profile],
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(self.ENDPOINT)

        assert mock_fetch.call_args_list[2].args[0] == (
            "/dna/intent/api/v1/business/sda/authentication-profile"
            "?siteNameHierarchy=Global/Area/Tail%20Site%201%20%28SA-14%29"
        )
        assert result == {
            "response": [{"siteNameHierarchy": "Global/Area/Tail Site 1 (SA-14)"}]
        }

    def test_no_fabric_sites_issues_no_target_requests(self, catalyst_client):
        with patch.object(
            catalyst_client,
            "fetch_data_pagination",
            side_effect=[self.SITES, {"response": []}],
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(self.ENDPOINT)

        assert mock_fetch.call_count == 2
        assert result == {"response": []}

    def test_membership_endpoint_failure_skips_lookup(self, catalyst_client):
        with patch.object(
            catalyst_client,
            "fetch_data_pagination",
            side_effect=[self.SITES, None],
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(self.ENDPOINT)

        assert mock_fetch.call_count == 2
        assert result is None
