import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# from nac_collector.main import cli
from nac_collector.controller.ise import CiscoClientISE

pytestmark = pytest.mark.integration


@pytest.fixture
def cisco_client():
    return CiscoClientISE(
        username="test_user",
        password="test_password",
        base_url="https://example.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )


def test_cisco_client_ise_with_integration(cisco_client, tmpdir):
    def mock_get_request(url):
        # Mock responses for specific API endpoints
        mock_responses = {
            "https://example.com/api/endpoint_1": {
                "response": [
                    {
                        "id": "id_1",
                        "name": "name_1",
                        "description": "name_1_description",
                    }
                ]
            },
            "https://example.com/api/endpoint_1/id_1/ch_endpoint_1": {
                "response": [
                    {
                        "id": "ch_id_1",
                        "name": "ch_name_1",
                        "description": "ch_name_1_description",
                    },
                    {
                        "id": "ch_id_2",
                        "name": "ch_name_2",
                        "description": "ch_name_2_description",
                    },
                ]
            },
            "https://example.com/api/endpoint_1/id_1/ch_endpoint_2": {
                "response": [
                    {
                        "id": "ch_id_3",
                        "name": "ch_name_3",
                        "description": "ch_name_3_description",
                    },
                    {
                        "id": "ch_id_4",
                        "name": "ch_name_4",
                        "description": "ch_name_4_description",
                    },
                ]
            },
            "https://example.com/api/endpoint_2": {
                "response": [
                    {
                        "id": "id_2",
                        "name": "name_2",
                        "description": "name_2_description",
                    },
                    {
                        "id": "id_3",
                        "name": "name_3",
                        "description": "name_3_description",
                    },
                    {
                        "id": "id_4",
                        "name": "name_4",
                        "description": "name_4_description",
                    },
                ]
            },
        }

        if url in mock_responses:
            return Mock(status_code=200, json=lambda: mock_responses[url])
        else:
            raise ValueError(f"Unexpected URL in mock_get_request: {url}")

    # Load endpoints from the YAML file
    fixture_path = Path(__file__).parent / "fixtures" / "endpoints.yaml"
    with fixture_path.open(encoding="utf-8") as f:
        endpoints_data = cisco_client.yaml.load(f)

    # Patching get_request method with mock implementation
    with patch.object(cisco_client, "get_request", side_effect=mock_get_request):
        # Call the method to test
        final_dict = cisco_client.get_from_endpoints_data(endpoints_data)

        # Write final_dict to a temporary ZIP archive
        output_file = tmpdir.join("ise.zip")
        cisco_client.write_to_archive(final_dict, str(output_file), "ise")

        # Compare the content of ise.json inside the ZIP with expected data
        expected_json_file = Path(__file__).parent / "fixtures" / "ise.json"
        with expected_json_file.open() as f_expected:
            expected_data = json.load(f_expected)

        # Extract ise.json from the ZIP archive and compare
        import zipfile

        with zipfile.ZipFile(str(output_file), "r") as zip_file:
            with zip_file.open("ise.json") as f_actual:
                actual_data = json.load(f_actual)

        assert actual_data == expected_data, "Output JSON data does not match expected"
