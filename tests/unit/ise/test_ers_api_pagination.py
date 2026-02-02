from unittest.mock import Mock

import pytest

from nac_collector.controller.ise import CiscoClientISE

pytestmark = pytest.mark.unit


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


def test_process_ers_api_results_no_pagination(mocker, cisco_client):
    # Mocking response when there's no pagination
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "SearchResult": {
            "resources": [
                {"link": {"href": "https://example.com/api/endpoint/1"}},
                {"link": {"href": "https://example.com/api/endpoint/2"}},
            ],
        }
    }
    mocker.patch.object(cisco_client, "get_request", return_value=mock_response)

    # Call the method to test
    data = cisco_client.process_ers_api_results(mock_response.json.return_value)

    # Assertions
    assert len(data) == 2  # Total 2 resources without pagination
    assert all(
        isinstance(item, dict) for item in data
    )  # All items should be dictionaries


def test_process_ers_api_results_with_pagination(mocker, cisco_client):
    # Mocking get_request method
    def mock_get_request(url):
        mock_responses = {
            "https://example.com/api/endpoint/1": {
                "key": {
                    "id": "1",
                    "name": "name-1",
                    "attr1": "attr-1",
                    "attr2": "attr-2",
                }
            },
            "https://example.com/api/endpoint/2": {
                "key": {
                    "id": "2",
                    "name": "name-2",
                    "attr1": "attr-3",
                    "attr2": "attr-4",
                }
            },
            "https://example.com/api/endpoint?size=1&page=1": {
                "SearchResult": {
                    "resources": [
                        {
                            "link": {"href": "https://example.com/api/endpoint/1"},
                            "id": "1",
                            "name": "name-1",
                            "attr1": "attr-1",
                            "attr2": "attr-2",
                        }
                    ],
                    "nextPage": {
                        "href": "https://example.com/api/endpoint?size=1&page=2"
                    },
                }
            },
            "https://example.com/api/endpoint?size=1&page=2": {
                "SearchResult": {
                    "resources": [
                        {
                            "link": {"href": "https://example.com/api/endpoint/2"},
                            "id": "2",
                            "name": "name-2",
                            "attr1": "attr-3",
                            "attr2": "attr-4",
                        }
                    ],
                    "previousPage": {
                        "href": "https://example.com/api/endpoint?size=1&page=1"
                    },
                }
            },
        }

        if url in mock_responses:
            return Mock(status_code=200, json=lambda: mock_responses[url])
        else:
            raise ValueError(f"Unexpected URL in mock_get_request: {url}")

    mocker.patch.object(cisco_client, "get_request", side_effect=mock_get_request)

    # Call the method to test
    data = []
    response_url = "https://example.com/api/endpoint?size=1&page=1"
    response_data = mock_get_request(response_url).json()
    data.extend(cisco_client.process_ers_api_results(response_data))

    # Assertions
    assert len(data) == 2  # Total 2 resources with pagination
    for item in data:
        assert isinstance(item, dict)
        assert "id" in item
        assert "name" in item
        assert "attr1" in item
        assert "attr2" in item

    # Specific assertions for the first and second elements
    assert data[0]["id"] == "1"
    assert data[0]["name"] == "name-1"
    assert data[0]["attr1"] == "attr-1"
    assert data[0]["attr2"] == "attr-2"

    assert data[1]["id"] == "2"
    assert data[1]["name"] == "name-2"
    assert data[1]["attr1"] == "attr-3"
    assert data[1]["attr2"] == "attr-4"


def test_reconstruct_url_with_internal_ip(cisco_client):
    """Test URL reconstruction when ISE returns internal IP in href (proxy scenario)"""
    href = "https://10.247.67.80/ers/config/sgt?size=20&page=3"
    expected = "https://example.com/ers/config/sgt?size=20&page=3"

    result = cisco_client.reconstruct_url_with_base(href)

    assert result == expected


def test_reconstruct_url_with_matching_host(cisco_client):
    """Test URL reconstruction when href already uses correct host"""
    href = "https://example.com/ers/config/sgt/abc-123"
    expected = "https://example.com/ers/config/sgt/abc-123"

    result = cisco_client.reconstruct_url_with_base(href)

    assert result == expected


def test_reconstruct_url_preserves_query_params(cisco_client):
    """Test that URL reconstruction preserves all query parameters"""
    href = "https://10.1.1.1/ers/config/networkdevice?filter=name.EQ.test&size=100&page=2"
    expected = "https://example.com/ers/config/networkdevice?filter=name.EQ.test&size=100&page=2"

    result = cisco_client.reconstruct_url_with_base(href)

    assert result == expected


def test_reconstruct_url_without_query_params(cisco_client):
    """Test URL reconstruction with no query parameters"""
    href = "https://192.168.1.100/ers/config/sgt/9ba71a76-0622-4a0f-8cb1-18bc155f65ca"
    expected = "https://example.com/ers/config/sgt/9ba71a76-0622-4a0f-8cb1-18bc155f65ca"

    result = cisco_client.reconstruct_url_with_base(href)

    assert result == expected


def test_reconstruct_url_with_domain_name_href(cisco_client):
    """Test URL reconstruction when href uses different domain name"""
    href = "https://ise-internal.company.local/ers/config/sgt?size=20"
    expected = "https://example.com/ers/config/sgt?size=20"

    result = cisco_client.reconstruct_url_with_base(href)

    assert result == expected
