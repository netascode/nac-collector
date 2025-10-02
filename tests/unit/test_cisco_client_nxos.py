from unittest.mock import MagicMock, patch

import httpx
import pytest

from nac_collector.device.nxos import CiscoClientNXOS

pytestmark = pytest.mark.unit


@pytest.fixture
def sample_devices():
    """Sample device data for testing."""
    return [
        {
            "name": "Switch1",
            "target": "https://switch1.example.com",
            "username": "switch_user",
            "password": "switch_pass",
            "protocol": "rest",
        },
        {
            "name": "Switch2",
            "target": "switch2.example.com",
        },
    ]


@pytest.fixture
def nxos_client(sample_devices):
    """Create a CiscoClientNXOS instance for testing."""
    return CiscoClientNXOS(
        devices=sample_devices,
        default_username="default_user",
        default_password="default_pass",
        max_retries=3,
        retry_after=1,
        timeout=30,
        ssl_verify=False,
    )


class TestCiscoClientNXOSInit:
    def test_init_inherits_from_base_class(self, nxos_client, sample_devices):
        assert nxos_client.devices == sample_devices
        assert nxos_client.default_username == "default_user"
        assert nxos_client.default_password == "default_pass"
        assert nxos_client.SOLUTION == "nxos"
        assert nxos_client.DEFAULT_PROTOCOL == "rest"
        assert nxos_client.AUTH_ENDPOINT == "/api/aaaLogin.json"
        assert (
            nxos_client.CONFIG_ENDPOINT
            == "/api/mo/sys.json?rsp-subtree=full&rsp-prop-include=set-config-only"
        )
        assert hasattr(nxos_client, "_authenticated_clients")
        assert isinstance(nxos_client._authenticated_clients, dict)


class TestAuthenticateDevice:
    @patch("httpx.Client")
    def test_authenticate_device_success(self, mock_client_class, nxos_client):
        # Setup mock HTTP client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Setup successful authentication response
        mock_auth_response = MagicMock()
        mock_auth_response.status_code = 200
        mock_auth_response.json.return_value = {"imdata": []}
        mock_client.post.return_value = mock_auth_response

        device = {
            "name": "TestDevice",
            "target": "https://switch.example.com",
            "username": "test_user",
            "password": "test_pass",
        }

        result = nxos_client.authenticate_device(device)
        assert result is True
        assert "TestDevice" in nxos_client._authenticated_clients

        # Verify authentication call
        mock_client.post.assert_called_once_with(
            "https://switch.example.com/api/aaaLogin.json",
            json={"aaaUser": {"attributes": {"name": "test_user", "pwd": "test_pass"}}},
        )

    @patch("httpx.Client")
    def test_authenticate_device_failure(self, mock_client_class, nxos_client):
        # Setup mock HTTP client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Setup failed authentication response
        mock_auth_response = MagicMock()
        mock_auth_response.status_code = 401
        mock_client.post.return_value = mock_auth_response

        device = {"name": "TestDevice", "target": "https://switch.example.com"}

        result = nxos_client.authenticate_device(device)
        assert result is False
        assert "TestDevice" not in nxos_client._authenticated_clients
        mock_client.close.assert_called_once()

    @patch("httpx.Client")
    def test_authenticate_device_invalid_json_response(
        self, mock_client_class, nxos_client
    ):
        # Setup mock HTTP client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Setup authentication response with invalid JSON
        mock_auth_response = MagicMock()
        mock_auth_response.status_code = 200
        mock_auth_response.json.side_effect = Exception("Invalid JSON")
        mock_client.post.return_value = mock_auth_response

        device = {"name": "TestDevice", "target": "https://switch.example.com"}

        result = nxos_client.authenticate_device(device)
        assert result is False
        assert "TestDevice" not in nxos_client._authenticated_clients
        mock_client.close.assert_called_once()

    def test_authenticate_device_no_target(self, nxos_client):
        device = {"name": "TestDevice"}
        result = nxos_client.authenticate_device(device)
        assert result is False
        assert "TestDevice" not in nxos_client._authenticated_clients

    @patch("httpx.Client")
    def test_authenticate_device_connection_error(self, mock_client_class, nxos_client):
        # Setup mock HTTP client to raise connection error
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.post.side_effect = httpx.RequestError("Connection failed")

        device = {"name": "TestDevice", "target": "https://switch.example.com"}

        result = nxos_client.authenticate_device(device)
        assert result is False
        assert "TestDevice" not in nxos_client._authenticated_clients
        mock_client.close.assert_called_once()

    @patch("httpx.Client")
    def test_authenticate_device_auto_adds_https(self, mock_client_class, nxos_client):
        # Setup mock HTTP client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Setup successful authentication response
        mock_auth_response = MagicMock()
        mock_auth_response.status_code = 200
        mock_auth_response.json.return_value = {"imdata": []}
        mock_client.post.return_value = mock_auth_response

        device = {
            "name": "TestDevice",
            "target": "switch.example.com",  # No https:// scheme
        }

        result = nxos_client.authenticate_device(device)
        assert result is True

        # Verify that https:// was automatically added
        mock_client.post.assert_called_once_with(
            "https://switch.example.com/api/aaaLogin.json",
            json={
                "aaaUser": {
                    "attributes": {"name": "default_user", "pwd": "default_pass"}
                }
            },
        )


class TestCollectViaRest:
    def test_successful_rest_collection(self, nxos_client):
        # Setup authenticated client
        mock_client = MagicMock()
        nxos_client._authenticated_clients["TestDevice"] = mock_client

        # Setup mock configuration response
        mock_config_response = MagicMock()
        mock_config_response.status_code = 200
        config_data = {
            "imdata": [
                {"topSystem": {"attributes": {"name": "switch1", "serial": "ABC123"}}}
            ]
        }
        mock_config_response.json.return_value = config_data
        mock_client.get.return_value = mock_config_response

        device = {
            "name": "TestDevice",
            "target": "https://switch1.example.com",
        }

        result = nxos_client.collect_via_rest(device)

        assert result is not None
        assert "topSystem" in result
        assert result["topSystem"]["attributes"]["name"] == "switch1"

        # Verify configuration collection call
        mock_client.get.assert_called_once_with(
            "https://switch1.example.com/api/mo/sys.json?rsp-subtree=full&rsp-prop-include=set-config-only"
        )

    def test_successful_rest_collection_without_https_scheme(self, nxos_client):
        # Setup authenticated client
        mock_client = MagicMock()
        nxos_client._authenticated_clients["TestDevice"] = mock_client

        # Setup mock configuration response
        mock_config_response = MagicMock()
        mock_config_response.status_code = 200
        mock_config_response.json.return_value = {"imdata": []}
        mock_client.get.return_value = mock_config_response

        device = {
            "name": "TestDevice",
            "target": "switch1.example.com",  # No https:// scheme
        }

        result = nxos_client.collect_via_rest(device)

        assert result is not None

        # Verify that https:// was automatically added
        mock_client.get.assert_called_once_with(
            "https://switch1.example.com/api/mo/sys.json?rsp-subtree=full&rsp-prop-include=set-config-only"
        )

    def test_no_authenticated_client(self, nxos_client):
        # No authenticated client for this device
        device = {"name": "TestDevice", "target": "https://switch1.example.com"}

        result = nxos_client.collect_via_rest(device)

        assert result is not None
        assert "error" in result
        assert "No authenticated client found for device TestDevice" in result["error"]

    def test_config_collection_failure(self, nxos_client):
        # Setup authenticated client
        mock_client = MagicMock()
        nxos_client._authenticated_clients["TestDevice"] = mock_client

        # Setup failed configuration response
        mock_config_response = MagicMock()
        mock_config_response.status_code = 500
        mock_client.get.return_value = mock_config_response

        device = {"name": "TestDevice", "target": "https://switch1.example.com"}

        result = nxos_client.collect_via_rest(device)

        assert result is not None
        assert "error" in result
        assert "Configuration collection failed with status code 500" in result["error"]

    def test_config_invalid_json_response(self, nxos_client):
        # Setup authenticated client
        mock_client = MagicMock()
        nxos_client._authenticated_clients["TestDevice"] = mock_client

        # Setup configuration response with invalid JSON
        mock_config_response = MagicMock()
        mock_config_response.status_code = 200
        mock_config_response.json.side_effect = Exception("Invalid JSON")
        mock_config_response.text = "Invalid JSON response"
        mock_client.get.return_value = mock_config_response

        device = {"name": "TestDevice", "target": "https://switch1.example.com"}

        result = nxos_client.collect_via_rest(device)

        assert result is not None
        assert "error" in result
        assert "Failed to parse configuration JSON" in result["error"]
        assert "raw_output" in result
        assert result["raw_output"] == "Invalid JSON response"

    def test_rest_collection_no_target(self, nxos_client):
        device = {"name": "TestDevice"}

        result = nxos_client.collect_via_rest(device)

        assert result is not None
        assert "error" in result
        assert "No target specified for device" in result["error"]

    def test_rest_connection_error(self, nxos_client):
        # Setup authenticated client to raise connection error
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.RequestError("Connection failed")
        nxos_client._authenticated_clients["TestDevice"] = mock_client

        device = {"name": "TestDevice", "target": "https://switch1.example.com"}

        result = nxos_client.collect_via_rest(device)

        assert result is not None
        assert "error" in result
        assert "REST connection error" in result["error"]


class TestCollectFromDevice:
    def test_collect_from_device_routes_to_rest(self, nxos_client):
        device = {
            "name": "TestDevice",
            "protocol": "rest",
            "target": "https://switch1.example.com",
        }
        expected_result = {"config": "data"}

        with patch.object(
            nxos_client, "collect_via_rest", return_value=expected_result
        ) as mock_rest_collect:
            result = nxos_client.collect_from_device(device)

            assert result == expected_result
            mock_rest_collect.assert_called_once_with(device)

    def test_collect_from_device_defaults_to_rest(self, nxos_client):
        device = {"name": "TestDevice", "target": "https://switch1.example.com"}
        expected_result = {"config": "data"}

        with patch.object(
            nxos_client, "collect_via_rest", return_value=expected_result
        ) as mock_rest_collect:
            result = nxos_client.collect_from_device(device)

            assert result == expected_result
            mock_rest_collect.assert_called_once_with(device)

    def test_collect_from_device_unsupported_protocol_falls_back_to_rest(
        self, nxos_client
    ):
        device = {
            "name": "TestDevice",
            "protocol": "ssh",
            "target": "https://switch1.example.com",
        }
        expected_result = {"config": "data"}

        with patch.object(
            nxos_client, "collect_via_rest", return_value=expected_result
        ) as mock_rest_collect:
            with patch.object(nxos_client.logger, "warning") as mock_warning:
                result = nxos_client.collect_from_device(device)

                assert result == expected_result
                mock_rest_collect.assert_called_once_with(device)
                mock_warning.assert_called_once_with(
                    "Protocol ssh not supported for NXOS, using REST"
                )


class TestProcessRestOutput:
    def test_process_rest_output_extracts_first_imdata_element(self, nxos_client):
        """Test that _process_rest_output extracts the first element from imdata list."""
        input_data = {
            "imdata": [
                {"topSystem": {"attributes": {"name": "switch1"}}},
                {"topSystem": {"attributes": {"name": "switch2"}}},
            ]
        }
        expected_output = {"topSystem": {"attributes": {"name": "switch1"}}}

        result = nxos_client._process_rest_output(input_data)
        assert result == expected_output

    def test_process_rest_output_returns_original_if_no_imdata(self, nxos_client):
        """Test that _process_rest_output returns original data if no imdata key."""
        input_data = {"config": {"some": "data"}}

        result = nxos_client._process_rest_output(input_data)
        assert result == input_data

    def test_process_rest_output_returns_original_if_empty_imdata(self, nxos_client):
        """Test that _process_rest_output returns original data if imdata is empty."""
        input_data = {"imdata": []}

        result = nxos_client._process_rest_output(input_data)
        assert result == input_data

    def test_process_rest_output_returns_original_if_imdata_not_list(self, nxos_client):
        """Test that _process_rest_output returns original data if imdata is not a list."""
        input_data = {"imdata": {"not": "a list"}}

        result = nxos_client._process_rest_output(input_data)
        assert result == input_data

    def test_process_rest_output_returns_original_if_not_dict(self, nxos_client):
        """Test that _process_rest_output returns original data if input is not a dict."""
        input_data = ["not", "a", "dict"]

        result = nxos_client._process_rest_output(input_data)
        assert result == input_data


class TestConstants:
    def test_solution_constant(self):
        assert CiscoClientNXOS.SOLUTION == "nxos"

    def test_default_protocol_constant(self):
        assert CiscoClientNXOS.DEFAULT_PROTOCOL == "rest"

    def test_auth_endpoint_constant(self):
        assert CiscoClientNXOS.AUTH_ENDPOINT == "/api/aaaLogin.json"

    def test_config_endpoint_constant(self):
        assert (
            CiscoClientNXOS.CONFIG_ENDPOINT
            == "/api/mo/sys.json?rsp-subtree=full&rsp-prop-include=set-config-only"
        )
