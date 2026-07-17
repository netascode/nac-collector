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


class TestFeatureTemplateAlternateFetch:
    def test_fetch_data_alternate_flattens_summary_instances(self, catalyst_client):
        endpoint = {
            "name": "wireless_rrm_fra_configuration",
            "endpoint": (
                "/dna/intent/api/v1/featureTemplates/wireless/rrmFraConfigurations"
            ),
        }
        summary = {
            "response": [
                {
                    "type": "RRM_FRA_CONFIGURATION",
                    "count": 2,
                    "instances": [
                        {"designName": "template-a", "id": "id-a"},
                        {"designName": "template-b", "id": "id-b"},
                    ],
                }
            ]
        }
        detail_a = {
            "response": {
                "id": "id-a",
                "designName": "template-a",
                "featureAttributes": {"fraStatus": True},
            }
        }
        detail_b = {
            "response": {
                "id": "id-b",
                "designName": "template-b",
                "featureAttributes": {"fraStatus": False},
            }
        }

        with patch.object(
            catalyst_client, "fetch_data_pagination", side_effect=[summary, detail_a, detail_b]
        ) as mock_fetch:
            result = catalyst_client.fetch_data_alternate(endpoint)

        assert mock_fetch.call_args_list[0].args[0].endswith(
            "summary?type=RRM_FRA_CONFIGURATION&limit=25"
        )
        assert result == {
            "response": [
                {
                    "id": "id-a",
                    "designName": "template-a",
                    "featureAttributes": {"fraStatus": True},
                },
                {
                    "id": "id-b",
                    "designName": "template-b",
                    "featureAttributes": {"fraStatus": False},
                },
            ]
        }

    def test_process_endpoint_data_emits_per_template_entries(self, catalyst_client):
        endpoint = {
            "name": "wireless_cleanair_configuration",
            "endpoint": (
                "/dna/intent/api/v1/featureTemplates/wireless/cleanAirConfigurations"
            ),
        }
        endpoint_dict = {"wireless_cleanair_configuration": []}
        data = {
            "response": [
                {
                    "id": "abc-123",
                    "designName": "CLEANAIR_TEST",
                    "featureAttributes": {"cleanAir": True},
                }
            ]
        }

        result = catalyst_client.process_endpoint_data(endpoint, endpoint_dict, data)

        assert result["wireless_cleanair_configuration"] == [
            {
                "data": {
                    "id": "abc-123",
                    "designName": "CLEANAIR_TEST",
                    "featureAttributes": {"cleanAir": True},
                },
                "endpoint": (
                    "/dna/intent/api/v1/featureTemplates/wireless/"
                    "cleanAirConfigurations/abc-123"
                ),
            }
        ]
