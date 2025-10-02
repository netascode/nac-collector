from unittest.mock import MagicMock, patch

import httpx
import paramiko
import pytest

from nac_collector.device.iosxe import CiscoClientIOSXE

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
            "protocol": "restconf",
        },
        {
            "name": "Switch2",
            "target": "https://switch2.example.com",
        },
    ]


@pytest.fixture
def iosxe_client(sample_devices):
    """Create a CiscoClientIOSXE instance for testing."""
    return CiscoClientIOSXE(
        devices=sample_devices,
        default_username="default_user",
        default_password="default_pass",
        max_retries=3,
        retry_after=1,
        timeout=30,
        ssl_verify=False,
    )


class TestCiscoClientIOSXEInit:
    def test_init_inherits_from_base_class(self, iosxe_client, sample_devices):
        assert iosxe_client.devices == sample_devices
        assert iosxe_client.default_username == "default_user"
        assert iosxe_client.default_password == "default_pass"
        assert iosxe_client.SOLUTION == "iosxe"
        assert iosxe_client.DEFAULT_PROTOCOL == "restconf"
        assert (
            iosxe_client.CONFIG_ENDPOINT == "/restconf/data/Cisco-IOS-XE-native:native"
        )


class TestAuthenticateDevice:
    def test_authenticate_device_always_returns_true(self, iosxe_client):
        # Authentication is now a no-op, should always return True
        device = {"name": "TestDevice", "target": "https://test.example.com"}
        result = iosxe_client.authenticate_device(device)
        assert result is True

    def test_authenticate_device_with_ssh_protocol(self, iosxe_client):
        # Should return True regardless of protocol
        device = {"name": "TestDevice", "target": "test.example.com", "protocol": "ssh"}
        result = iosxe_client.authenticate_device(device)
        assert result is True

    def test_authenticate_device_with_restconf_protocol(self, iosxe_client):
        # Should return True regardless of protocol
        device = {
            "name": "TestDevice",
            "target": "https://test.example.com",
            "protocol": "restconf",
        }
        result = iosxe_client.authenticate_device(device)
        assert result is True


class TestCollectViaRestconf:
    @patch("httpx.Client")
    def test_successful_collection(self, mock_client_class, iosxe_client):
        # Setup mock response with config data
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Cisco-IOS-XE-native:native": {
                "version": "17.3",
                "hostname": "TestDevice",
                "interface": {"GigabitEthernet": [{"name": "0/0/1"}]},
            }
        }

        # Setup mock client
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_client

        device = {
            "name": "TestDevice",
            "target": "https://test.example.com",
            "username": "test_user",
            "password": "test_pass",
        }

        result = iosxe_client.collect_via_restconf(device)

        assert result is not None
        assert "Cisco-IOS-XE-native:native" in result
        assert result["Cisco-IOS-XE-native:native"]["hostname"] == "TestDevice"

        # Verify correct endpoint was called
        mock_client.get.assert_called_once_with(
            "https://test.example.com/restconf/data/Cisco-IOS-XE-native:native"
        )

    @patch("httpx.Client")
    def test_collection_http_error(self, mock_client_class, iosxe_client):
        # Setup mock response with error status
        mock_response = MagicMock()
        mock_response.status_code = 404

        # Setup mock client
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_client

        device = {"name": "TestDevice", "target": "https://test.example.com"}

        result = iosxe_client.collect_via_restconf(device)

        assert result is not None
        assert "error" in result
        assert "Failed to collect configuration - HTTP 404" in result["error"]

    @patch("httpx.Client")
    def test_collection_network_exception(self, mock_client_class, iosxe_client):
        # Setup mock client to raise exception
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("Request timeout")
        mock_client_class.return_value.__enter__.return_value = mock_client

        device = {"name": "TestDevice", "target": "https://test.example.com"}

        result = iosxe_client.collect_via_restconf(device)

        assert result is not None
        assert "error" in result
        assert "Collection failed - Request timeout" in result["error"]

    @patch("httpx.Client")
    def test_uses_ssl_verify_setting(self, mock_client_class, iosxe_client):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"config": "data"}

        # Setup mock client
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_client

        device = {"name": "TestDevice", "target": "https://test.example.com"}

        iosxe_client.collect_via_restconf(device)

        # Verify client was created with correct ssl_verify setting
        mock_client_class.assert_called_once_with(
            verify=False,  # Should match iosxe_client.ssl_verify
            auth=("default_user", "default_pass"),
            timeout=120,  # Should use RESTCONF_DATA_TIMEOUT for data collection
            headers={"Accept": "application/yang-data+json"},
        )


class TestIntegration:
    @patch("httpx.Client")
    def test_full_device_workflow(self, mock_client_class, iosxe_client):
        # Setup mock responses for both auth and collection
        mock_auth_response = MagicMock()
        mock_auth_response.status_code = 200

        mock_collect_response = MagicMock()
        mock_collect_response.status_code = 200
        mock_collect_response.json.return_value = {
            "Cisco-IOS-XE-native:native": {"hostname": "Switch1"}
        }

        # Setup mock client to return different responses for different URLs
        mock_client = MagicMock()

        def side_effect(url, **kwargs):
            if url.endswith("/.well-known/host-meta"):
                return mock_auth_response
            else:
                return mock_collect_response

        mock_client.get.side_effect = side_effect
        mock_client_class.return_value.__enter__.return_value = mock_client

        device = {
            "name": "Switch1",
            "target": "https://switch1.example.com",
            "username": "admin",
            "password": "cisco123",
        }

        # Test authentication
        auth_result = iosxe_client.authenticate_device(device)
        assert auth_result is True

        # Test collection
        collect_result = iosxe_client.collect_from_device(device)
        assert collect_result is not None
        assert "Cisco-IOS-XE-native:native" in collect_result
        assert collect_result["Cisco-IOS-XE-native:native"]["hostname"] == "Switch1"


class TestConstants:
    def test_solution_constant(self):
        assert CiscoClientIOSXE.SOLUTION == "iosxe"

    def test_default_protocol_constant(self):
        assert CiscoClientIOSXE.DEFAULT_PROTOCOL == "restconf"

    def test_config_endpoint_constant(self):
        assert (
            CiscoClientIOSXE.CONFIG_ENDPOINT
            == "/restconf/data/Cisco-IOS-XE-native:native"
        )

    def test_restconf_data_timeout_constant(self):
        assert CiscoClientIOSXE.RESTCONF_DATA_TIMEOUT == 120

    def test_ssh_timeout_constant(self):
        assert CiscoClientIOSXE.SSH_TIMEOUT == 60

    def test_ssh_command_constant(self):
        assert (
            CiscoClientIOSXE.SSH_COMMAND == "show running-config | format restconf-json"
        )


class TestCollectViaSSH:
    @patch("paramiko.SSHClient")
    def test_successful_ssh_collection(self, mock_ssh_client_class, iosxe_client):
        # Setup mock SSH client
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client

        # Setup mock command execution with valid JSON output
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 0

        # SSH command returns data wrapped in a "data" element
        json_output = '{"data": {"Cisco-IOS-XE-native:native": {"hostname": "TestDevice", "version": "17.3"}}}'
        mock_stdout.read.return_value = json_output.encode("utf-8")
        mock_ssh_client.exec_command.return_value = (
            mock_stdin,
            mock_stdout,
            mock_stderr,
        )

        device = {
            "name": "TestDevice",
            "target": "switch1.example.com:2222",
            "username": "test_user",
            "password": "test_pass",
        }

        result = iosxe_client.collect_via_ssh(device)

        assert result is not None
        assert "Cisco-IOS-XE-native:native" in result
        assert result["Cisco-IOS-XE-native:native"]["hostname"] == "TestDevice"

        mock_ssh_client.connect.assert_called_once_with(
            hostname="switch1.example.com",
            port=2222,
            username="test_user",
            password="test_pass",
            timeout=60,
            look_for_keys=False,
            allow_agent=False,
        )
        mock_ssh_client.exec_command.assert_called_once_with(
            "show running-config | format restconf-json"
        )
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_successful_ssh_collection_without_data_wrapper(
        self, mock_ssh_client_class, iosxe_client
    ):
        # Test backward compatibility for SSH output without "data" wrapper
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client

        # Setup mock command execution with JSON output without "data" wrapper
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 0

        # Direct JSON output without "data" wrapper
        json_output = '{"Cisco-IOS-XE-native:native": {"hostname": "TestDevice", "version": "17.3"}}'
        mock_stdout.read.return_value = json_output.encode("utf-8")
        mock_ssh_client.exec_command.return_value = (
            mock_stdin,
            mock_stdout,
            mock_stderr,
        )

        device = {
            "name": "TestDevice",
            "target": "switch1.example.com",
            "username": "test_user",
            "password": "test_pass",
        }

        result = iosxe_client.collect_via_ssh(device)

        assert result is not None
        assert "Cisco-IOS-XE-native:native" in result
        assert result["Cisco-IOS-XE-native:native"]["hostname"] == "TestDevice"
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_ssh_command_failure(self, mock_ssh_client_class, iosxe_client):
        # Setup mock SSH client
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client

        # Setup mock command execution with failure
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stderr.read.return_value = b"Command failed"
        mock_ssh_client.exec_command.return_value = (
            mock_stdin,
            mock_stdout,
            mock_stderr,
        )

        device = {"name": "TestDevice", "target": "switch1.example.com"}

        result = iosxe_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "SSH command failed with exit status 1" in result["error"]
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_ssh_invalid_json_output(self, mock_ssh_client_class, iosxe_client):
        # Setup mock SSH client
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client

        # Setup mock command execution with invalid JSON
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stdout.read.return_value = b"Invalid JSON output"
        mock_ssh_client.exec_command.return_value = (
            mock_stdin,
            mock_stdout,
            mock_stderr,
        )

        device = {"name": "TestDevice", "target": "switch1.example.com"}

        result = iosxe_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "Failed to parse JSON output" in result["error"]
        assert "raw_output" in result
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_ssh_no_output(self, mock_ssh_client_class, iosxe_client):
        # Setup mock SSH client
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client

        # Setup mock command execution with no output
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stdout.read.return_value = b""
        mock_ssh_client.exec_command.return_value = (
            mock_stdin,
            mock_stdout,
            mock_stderr,
        )

        device = {"name": "TestDevice", "target": "switch1.example.com"}

        result = iosxe_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "No output received from SSH command" in result["error"]
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_ssh_connection_error_during_collection(
        self, mock_ssh_client_class, iosxe_client
    ):
        # Setup mock SSH client to raise connection error
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client
        mock_ssh_client.connect.side_effect = paramiko.SSHException("Connection failed")

        device = {"name": "TestDevice", "target": "switch1.example.com"}

        result = iosxe_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "SSH connection error" in result["error"]
        mock_ssh_client.close.assert_called_once()

    def test_ssh_collection_invalid_target(self, iosxe_client):
        # Use a clearly invalid target that will fail hostname parsing
        device = {"name": "TestDevice", "target": "ssh://[invalid"}

        result = iosxe_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "Invalid target format" in result["error"]

    def test_ssh_collection_no_target(self, iosxe_client):
        device = {"name": "TestDevice"}

        result = iosxe_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "No target specified for device" in result["error"]


class TestProtocolRouting:
    def test_collect_from_device_routes_to_ssh(self, iosxe_client):
        device = {
            "name": "TestDevice",
            "protocol": "ssh",
            "target": "switch1.example.com",
        }
        expected_result = {"config": "data"}

        with patch.object(
            iosxe_client, "collect_via_ssh", return_value=expected_result
        ) as mock_ssh_collect:
            result = iosxe_client.collect_from_device(device)

            assert result == expected_result
            mock_ssh_collect.assert_called_once_with(device)

    def test_collect_from_device_routes_to_restconf(self, iosxe_client):
        device = {
            "name": "TestDevice",
            "protocol": "restconf",
            "target": "https://switch1.example.com",
        }
        expected_result = {"config": "data"}

        with patch.object(
            iosxe_client, "collect_via_restconf", return_value=expected_result
        ) as mock_restconf_collect:
            result = iosxe_client.collect_from_device(device)

            assert result == expected_result
            mock_restconf_collect.assert_called_once_with(device)

    def test_collect_from_device_defaults_to_restconf(self, iosxe_client):
        device = {"name": "TestDevice", "target": "https://switch1.example.com"}
        expected_result = {"config": "data"}

        with patch.object(
            iosxe_client, "collect_via_restconf", return_value=expected_result
        ) as mock_restconf_collect:
            result = iosxe_client.collect_from_device(device)

            assert result == expected_result
            mock_restconf_collect.assert_called_once_with(device)

    def test_collect_from_device_unsupported_protocol_falls_back_to_restconf(
        self, iosxe_client
    ):
        device = {
            "name": "TestDevice",
            "protocol": "netconf",
            "target": "https://switch1.example.com",
        }
        expected_result = {"config": "data"}

        with patch.object(
            iosxe_client, "collect_via_restconf", return_value=expected_result
        ) as mock_restconf_collect:
            with patch.object(iosxe_client.logger, "warning") as mock_warning:
                result = iosxe_client.collect_from_device(device)

                assert result == expected_result
                mock_restconf_collect.assert_called_once_with(device)
                mock_warning.assert_called_once_with(
                    "Protocol netconf not supported, using restconf"
                )
