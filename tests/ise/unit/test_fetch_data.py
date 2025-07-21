import pytest

from nac_collector.cisco_client_ise import CiscoClientISE

pytestmark = pytest.mark.unit


@pytest.fixture
def cisco_client():
    # Mocked CiscoClientISE instance for testing
    return CiscoClientISE(
        username="test_user",
        password="test_password",
        api_key="test_api_key",
        base_url="https://example.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )


def test_fetch_data_none_response(mocker, cisco_client):
    # Mocking fetch_data to return None
    mocker.patch.object(cisco_client, "fetch_data", return_value=None)

    endpoint = "/api/test_endpoint"
    data = cisco_client.fetch_data(endpoint)

    assert data is None


def test_fetch_data_list_response(mocker, cisco_client):
    # Mocking fetch_data to return a list of dictionaries
    mock_data = [{"id": "1", "name": "Item 1"}, {"id": "2", "name": "Item 2"}]
    mocker.patch.object(cisco_client, "fetch_data", return_value=mock_data)

    endpoint = "/api/test_endpoint"
    data = cisco_client.fetch_data(endpoint)

    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["id"] == "1"


def test_fetch_data_single_dict_response(mocker, cisco_client):
    # Mocking fetch_data to return a single dictionary
    mock_data = {"id": "1", "name": "Single Item"}
    mocker.patch.object(cisco_client, "fetch_data", return_value=mock_data)

    endpoint = "/api/test_endpoint"
    data = cisco_client.fetch_data(endpoint)

    assert isinstance(data, dict)
    assert data["name"] == "Single Item"
