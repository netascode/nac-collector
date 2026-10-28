from unittest.mock import MagicMock, patch

import pytest

from nac_collector.controller.catalystcenter import CiscoClientCATALYSTCENTER

pytestmark = pytest.mark.unit

PRIMARY_ENDPOINT = "/dna/intent/api/v1/wirelessControllers/%v/primaryManagedApLocations"
SECONDARY_ENDPOINT = (
    "/dna/intent/api/v1/wirelessControllers/%v/secondaryManagedApLocations"
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


def _inventory():
    return {
        "response": [
            {"id": "wlc-1", "family": "Wireless Controller"},
            {"id": "switch-1", "family": "Switches and Hubs"},
            {"id": "ap-1", "family": "Unified AP"},
            {"id": "router-1", "family": "Routers"},
            {"id": "wlc-2", "family": "Wireless Controller"},
        ]
    }


class TestManagedApLocationsSourceFilter:
    @pytest.mark.parametrize("endpoint", [PRIMARY_ENDPOINT, SECONDARY_ENDPOINT])
    def test_queries_only_wireless_controllers(self, catalyst_client, endpoint):
        locations = {"response": ["Global/Site1"]}

        with patch.object(
            catalyst_client,
            "fetch_data_pagination",
            side_effect=[_inventory(), locations, locations],
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(
                {"name": "managed_ap_locations", "endpoint": endpoint}
            )

        queried = [call.args[0] for call in mock_fetch.call_args_list[1:]]
        assert queried == [
            endpoint.replace("%v", "wlc-1"),
            endpoint.replace("%v", "wlc-2"),
        ]
        assert [entry["deviceId"] for entry in result["response"]] == [
            "wlc-1",
            "wlc-2",
        ]

    def test_no_controllers_issues_no_target_calls(self, catalyst_client):
        inventory = {
            "response": [
                {"id": "switch-1", "family": "Switches and Hubs"},
                {"id": "ap-1", "family": "Unified AP"},
            ]
        }

        with patch.object(
            catalyst_client, "fetch_data_pagination", side_effect=[inventory]
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(
                {"name": "managed_ap_locations", "endpoint": PRIMARY_ENDPOINT}
            )

        assert mock_fetch.call_count == 1
        assert result == {"response": []}

    def test_device_missing_family_is_skipped(self, catalyst_client):
        inventory = {"response": [{"id": "unknown-1"}]}

        with patch.object(
            catalyst_client, "fetch_data_pagination", side_effect=[inventory]
        ) as mock_fetch:
            catalyst_client.fetch_data_alternate(
                {"name": "managed_ap_locations", "endpoint": PRIMARY_ENDPOINT}
            )

        assert mock_fetch.call_count == 1


class TestSourceFilterHelper:
    def test_absent_filter_leaves_data_untouched(self):
        data = [{"id": "a"}, {"id": "b"}]
        assert CiscoClientCATALYSTCENTER._apply_source_filter(data, {}) == data

    def test_incomplete_filter_leaves_data_untouched(self):
        data = [{"id": "a", "family": "Routers"}]
        assert (
            CiscoClientCATALYSTCENTER._apply_source_filter(
                data, {"source_filter": {"key": "family"}}
            )
            == data
        )

    def test_non_list_payload_is_returned_as_is(self):
        payload = {"id": "a"}
        assert (
            CiscoClientCATALYSTCENTER._apply_source_filter(
                payload,
                {"source_filter": {"key": "family", "values": ["Wireless Controller"]}},
            )
            == payload
        )


class TestLookupConfiguration:
    @pytest.mark.parametrize("endpoint", [PRIMARY_ENDPOINT, SECONDARY_ENDPOINT])
    def test_managed_ap_location_lookups_filter_on_family(self, endpoint):
        lookup = CiscoClientCATALYSTCENTER.id_lookup[endpoint]
        assert lookup["source_filter"] == {
            "key": "family",
            "values": ["Wireless Controller"],
        }
