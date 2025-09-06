from typing import Any
from unittest.mock import MagicMock, mock_open, patch

import httpx
import pytest
from ruamel.yaml import YAML

from nac_collector.cisco_client import CiscoClient

pytestmark = pytest.mark.unit


class ConcreteCiscoClient(CiscoClient):
    """Concrete implementation of CiscoClient for testing purposes."""

    def authenticate(self) -> bool:
        return True

    def get_from_endpoints(self, endpoints_yaml_file: str) -> dict[str, Any]:
        return {"test": "data"}


@pytest.fixture
def cisco_client() -> ConcreteCiscoClient:
    return ConcreteCiscoClient(
        username="test_user",
        password="test_password",
        base_url="https://example.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )


@pytest.fixture
def mock_httpx_client():
    return MagicMock(spec=httpx.Client)


class TestCiscoClientInitialization:
    def test_initialization_with_defaults(self) -> None:
        client = ConcreteCiscoClient(
            username="user",
            password="pass",
            base_url="https://api.example.com",
            max_retries=3,
            retry_after=2,
            timeout=10,
        )
        assert client.username == "user"
        assert client.password == "pass"
        assert client.base_url == "https://api.example.com"
        assert client.max_retries == 3
        assert client.retry_after == 2
        assert client.timeout == 10
        assert client.ssl_verify is False
        assert client.client is None
        assert isinstance(client.yaml, YAML)

    def test_initialization_with_ssl_verify(self) -> None:
        client = ConcreteCiscoClient(
            username="user",
            password="pass",
            base_url="https://api.example.com",
            max_retries=3,
            retry_after=2,
            timeout=10,
            ssl_verify=True,
        )
        assert client.ssl_verify is True

    def test_abstract_methods_raise_not_implemented(self) -> None:
        with pytest.raises(TypeError):
            CiscoClient(
                username="user",
                password="pass",
                base_url="https://api.example.com",
                max_retries=3,
                retry_after=2,
                timeout=10,
            )


class TestGetRequest:
    def test_get_request_success(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_httpx_client.get.return_value = mock_response

        result = cisco_client.get_request("https://example.com/api/test")

        assert result == mock_response
        mock_httpx_client.get.assert_called_once_with("https://example.com/api/test")

    def test_get_request_client_not_initialized(self, cisco_client: ConcreteCiscoClient):
        cisco_client.client = None

        result = cisco_client.get_request("https://example.com/api/test")

        assert result is None

    def test_get_request_timeout_exception(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_httpx_client.get.side_effect = httpx.TimeoutException("Timeout")

        result = cisco_client.get_request("https://example.com/api/test")

        assert result is None
        assert mock_httpx_client.get.call_count == cisco_client.max_retries

    def test_get_request_rate_limited_with_retry_after_header(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "5"}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_httpx_client.get.side_effect = [mock_response_429, mock_response_200]

        with patch('time.sleep') as mock_sleep:
            result = cisco_client.get_request("https://example.com/api/test")

        assert result == mock_response_200
        assert cisco_client.retry_after == 5
        mock_sleep.assert_called_once_with(5)

    def test_get_request_rate_limited_without_retry_after_header(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_httpx_client.get.side_effect = [mock_response_429, mock_response_200]

        with patch('time.sleep') as mock_sleep:
            result = cisco_client.get_request("https://example.com/api/test")

        assert result == mock_response_200
        mock_sleep.assert_called_once_with(1)  # Uses default retry_after

    def test_get_request_unauthorized_calls_authenticate(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response_401 = MagicMock()
        mock_response_401.status_code = 401

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_httpx_client.get.side_effect = [mock_response_401, mock_response_200]

        with patch.object(cisco_client, 'authenticate') as mock_auth:
            result = cisco_client.get_request("https://example.com/api/test")

        assert result == mock_response_200
        mock_auth.assert_called_once()

    def test_get_request_unexpected_status_code(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_httpx_client.get.return_value = mock_response

        result = cisco_client.get_request("https://example.com/api/test")

        assert result is None

    def test_get_request_max_retries_exceeded(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        with patch('time.sleep'):
            result = cisco_client.get_request("https://example.com/api/test")

        assert result == mock_response
        assert mock_httpx_client.get.call_count == cisco_client.max_retries


class TestPostRequest:
    def test_post_request_success(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_httpx_client.post.return_value = mock_response

        data = {"key": "value"}
        result = cisco_client.post_request("https://example.com/api/test", data)

        assert result == mock_response
        mock_httpx_client.post.assert_called_once_with("https://example.com/api/test", data=data)

    def test_post_request_client_not_initialized(self, cisco_client: ConcreteCiscoClient):
        cisco_client.client = None

        result = cisco_client.post_request("https://example.com/api/test", {})

        assert result is None

    def test_post_request_timeout_exception(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_httpx_client.post.side_effect = httpx.TimeoutException("Timeout")

        # The current implementation has a bug where response is not initialized when all attempts timeout
        with pytest.raises(UnboundLocalError):
            cisco_client.post_request("https://example.com/api/test", {})

        assert mock_httpx_client.post.call_count == cisco_client.max_retries

    def test_post_request_rate_limited(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "3"}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_httpx_client.post.side_effect = [mock_response_429, mock_response_200]

        with patch('time.sleep') as mock_sleep:
            result = cisco_client.post_request("https://example.com/api/test", {})

        assert result == mock_response_200
        mock_sleep.assert_called_once_with(3)

    def test_post_request_2xx_success(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client

        for status_code in [200, 201, 202, 204]:
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_httpx_client.post.return_value = mock_response

            result = cisco_client.post_request("https://example.com/api/test", {})

            assert result == mock_response

    def test_post_request_unexpected_status_code(self, cisco_client: ConcreteCiscoClient, mock_httpx_client):
        cisco_client.client = mock_httpx_client
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_httpx_client.post.return_value = mock_response

        result = cisco_client.post_request("https://example.com/api/test", {})

        assert result == mock_response


class TestLogResponse:
    def test_log_response_success(self, cisco_client: ConcreteCiscoClient, caplog):
        with caplog.at_level("INFO"):
            mock_response = MagicMock()
            mock_response.status_code = 200

            cisco_client.log_response("/api/test", mock_response)

            assert "GET /api/test succeeded with status code 200" in caplog.text

    def test_log_response_failure(self, cisco_client: ConcreteCiscoClient, caplog):
        with caplog.at_level("ERROR"):
            mock_response = MagicMock()
            mock_response.status_code = 404

            cisco_client.log_response("/api/test", mock_response)

            assert "GET /api/test failed with status code 404" in caplog.text


class TestFetchData:
    def test_fetch_data_success(self, cisco_client: ConcreteCiscoClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"key": "value"}

        with patch.object(cisco_client, 'get_request', return_value=mock_response):
            result = cisco_client.fetch_data("/api/test")

        assert result == {"key": "value"}

    def test_fetch_data_no_response(self, cisco_client: ConcreteCiscoClient):
        with patch.object(cisco_client, 'get_request', return_value=None):
            result = cisco_client.fetch_data("/api/test")

        assert result is None

    def test_fetch_data_json_decode_error(self, cisco_client: ConcreteCiscoClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch.object(cisco_client, 'get_request', return_value=mock_response):
            result = cisco_client.fetch_data("/api/test")

        assert result is None

    def test_fetch_data_non_dict_response(self, cisco_client: ConcreteCiscoClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["item1", "item2"]

        with patch.object(cisco_client, 'get_request', return_value=mock_response):
            result = cisco_client.fetch_data("/api/test")

        assert result is None


class TestFetchDataPagination:
    def test_fetch_data_pagination_single_page(self, cisco_client: ConcreteCiscoClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": [{"id": 1}, {"id": 2}]}

        with patch.object(cisco_client, 'get_request', return_value=mock_response):
            result = cisco_client.fetch_data_pagination("/api/test")

        assert result == {"response": [{"id": 1}, {"id": 2}]}

    def test_fetch_data_pagination_multiple_pages(self, cisco_client: ConcreteCiscoClient):
        mock_response_1 = MagicMock()
        mock_response_1.status_code = 200
        mock_response_1.json.return_value = {"response": [{"id": i} for i in range(500)]}

        mock_response_2 = MagicMock()
        mock_response_2.status_code = 200
        mock_response_2.json.return_value = {"response": [{"id": i} for i in range(500, 600)]}

        with patch.object(cisco_client, 'get_request', side_effect=[mock_response_1, mock_response_2]):
            result = cisco_client.fetch_data_pagination("/api/test")

        assert len(result["response"]) == 600
        assert result["response"][0]["id"] == 0
        assert result["response"][-1]["id"] == 599

    def test_fetch_data_pagination_no_response_wrapper(self, cisco_client: ConcreteCiscoClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": 1}, {"id": 2}]

        with patch.object(cisco_client, 'get_request', return_value=mock_response):
            result = cisco_client.fetch_data_pagination("/api/test")

        assert result == [{"id": 1}, {"id": 2}]

    def test_fetch_data_pagination_single_item_response(self, cisco_client: ConcreteCiscoClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {"id": 1, "name": "test"}}

        with patch.object(cisco_client, 'get_request', return_value=mock_response):
            result = cisco_client.fetch_data_pagination("/api/test")

        assert result == {"response": [{"id": 1, "name": "test"}]}

    def test_fetch_data_pagination_reserve_ip_subpool_endpoint(self, cisco_client: ConcreteCiscoClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": [{"id": 1}]}

        with patch.object(cisco_client, 'get_request', return_value=mock_response) as mock_get:
            cisco_client.fetch_data_pagination("/dna/intent/api/v1/reserve-ip-subpool")

        mock_get.assert_called_once_with("https://example.com/dna/intent/api/v1/reserve-ip-subpool")

    def test_fetch_data_pagination_no_response(self, cisco_client: ConcreteCiscoClient):
        with patch.object(cisco_client, 'get_request', return_value=None):
            result = cisco_client.fetch_data_pagination("/api/test")

        assert result is None

    def test_fetch_data_pagination_json_decode_error(self, cisco_client: ConcreteCiscoClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch.object(cisco_client, 'get_request', return_value=mock_response):
            result = cisco_client.fetch_data_pagination("/api/test")

        assert result is None


class TestWriteToJson:
    def test_write_to_json(self, cisco_client: ConcreteCiscoClient):
        test_data = {"key": "value", "number": 42}

        with patch("builtins.open", mock_open()) as mock_file:
            cisco_client.write_to_json(test_data, "test_output.json")

        mock_file.assert_called_once_with("test_output.json", "w", encoding="utf-8")
        handle = mock_file()
        handle.write.assert_called()

        # Verify JSON format by checking if json.dump was called correctly
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        assert "key" in written_content
        assert "value" in written_content


class TestCreateEndpointDict:
    def test_create_endpoint_dict(self) -> None:
        endpoint = {"name": "test_endpoint", "endpoint": "/api/test"}

        result = CiscoClient.create_endpoint_dict(endpoint)

        assert result == {"test_endpoint": []}

    def test_create_endpoint_dict_different_names(self) -> None:
        endpoints = [
            {"name": "users", "endpoint": "/api/users"},
            {"name": "devices", "endpoint": "/api/devices"},
        ]

        for endpoint in endpoints:
            result = CiscoClient.create_endpoint_dict(endpoint)
            assert result == {endpoint["name"]: []}
