from unittest.mock import MagicMock, patch

import paramiko
import pytest

from nac_collector.device.iosxr import CiscoClientIOSXR

pytestmark = pytest.mark.unit


@pytest.fixture
def sample_devices():
    """Sample device data for testing."""
    return [
        {
            "name": "Router1",
            "target": "router1.example.com",
            "username": "router_user",
            "password": "router_pass",
            "protocol": "ssh",
        },
        {
            "name": "Router2",
            "target": "router2.example.com",
        },
    ]


@pytest.fixture
def iosxr_client(sample_devices):
    """Create a CiscoClientIOSXR instance for testing."""
    return CiscoClientIOSXR(
        devices=sample_devices,
        default_username="default_user",
        default_password="default_pass",
        max_retries=3,
        retry_after=1,
        timeout=30,
        ssl_verify=False,
    )


class TestCiscoClientIOSXRInit:
    def test_init_inherits_from_base_class(self, iosxr_client, sample_devices):
        assert iosxr_client.devices == sample_devices
        assert iosxr_client.default_username == "default_user"
        assert iosxr_client.default_password == "default_pass"
        assert iosxr_client.SOLUTION == "iosxr"
        assert iosxr_client.DEFAULT_PROTOCOL == "ssh"
        assert iosxr_client.SSH_COMMAND == "show running-config | json unified-model"


class TestAuthenticateDevice:
    def test_authenticate_device_always_returns_true(self, iosxr_client):
        # Authentication is now a no-op, should always return True
        device = {"name": "TestDevice", "target": "router.example.com"}
        result = iosxr_client.authenticate_device(device)
        assert result is True

    def test_authenticate_device_with_ssh_protocol(self, iosxr_client):
        # Should return True regardless of protocol
        device = {
            "name": "TestDevice",
            "target": "router.example.com",
            "protocol": "ssh",
        }
        result = iosxr_client.authenticate_device(device)
        assert result is True


class TestCollectViaSSH:
    @patch("paramiko.SSHClient")
    def test_successful_ssh_collection(self, mock_ssh_client_class, iosxr_client):
        # Setup mock SSH client
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client

        # Setup mock command execution with valid JSON output
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 0

        # IOSXR SSH command returns unified model JSON format
        json_output = '{"Cisco-IOS-XR-clns-isis-cfg:isis": {"instances": [{"instance-name": "default"}]}}'
        mock_stdout.read.return_value = json_output.encode("utf-8")
        mock_ssh_client.exec_command.return_value = (
            mock_stdin,
            mock_stdout,
            mock_stderr,
        )

        device = {
            "name": "TestDevice",
            "target": "router1.example.com:2222",
            "username": "test_user",
            "password": "test_pass",
        }

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "Cisco-IOS-XR-clns-isis-cfg:isis" in result
        assert (
            result["Cisco-IOS-XR-clns-isis-cfg:isis"]["instances"][0]["instance-name"]
            == "default"
        )

        mock_ssh_client.connect.assert_called_once_with(
            hostname="router1.example.com",
            port=2222,
            username="test_user",
            password="test_pass",
            timeout=60,
            look_for_keys=False,
            allow_agent=False,
        )
        mock_ssh_client.exec_command.assert_called_once_with(
            "show running-config | json unified-model"
        )
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_successful_ssh_collection_with_timestamp_header(
        self, mock_ssh_client_class, iosxr_client
    ):
        # Setup mock SSH client
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client

        # Setup mock command execution with timestamp header before JSON
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 0

        # IOSXR SSH command with timestamp header that needs to be filtered out
        output_with_timestamp = """!! IOS XR Configuration 7.3.2
!! Last configuration change at Wed Jan 10 15:30:25 2024 by admin

{
  "Cisco-IOS-XR-clns-isis-cfg:isis": {
    "instances": [
      {
        "instance-name": "default"
      }
    ]
  }
}"""
        mock_stdout.read.return_value = output_with_timestamp.encode("utf-8")
        mock_ssh_client.exec_command.return_value = (
            mock_stdin,
            mock_stdout,
            mock_stderr,
        )

        device = {
            "name": "TestDevice",
            "target": "router1.example.com",
            "username": "test_user",
            "password": "test_pass",
        }

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "Cisco-IOS-XR-clns-isis-cfg:isis" in result
        assert (
            result["Cisco-IOS-XR-clns-isis-cfg:isis"]["instances"][0]["instance-name"]
            == "default"
        )

        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_ssh_command_failure(self, mock_ssh_client_class, iosxr_client):
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

        device = {"name": "TestDevice", "target": "router1.example.com"}

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "SSH command failed with exit status 1" in result["error"]
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_ssh_invalid_json_output(self, mock_ssh_client_class, iosxr_client):
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

        device = {"name": "TestDevice", "target": "router1.example.com"}

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "Failed to parse JSON output" in result["error"]
        assert "raw_output" in result
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_ssh_no_output(self, mock_ssh_client_class, iosxr_client):
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

        device = {"name": "TestDevice", "target": "router1.example.com"}

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "No output received from SSH command" in result["error"]
        mock_ssh_client.close.assert_called_once()

    @patch("paramiko.SSHClient")
    def test_ssh_connection_error_during_collection(
        self, mock_ssh_client_class, iosxr_client
    ):
        # Setup mock SSH client to raise connection error
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client
        mock_ssh_client.connect.side_effect = paramiko.SSHException("Connection failed")

        device = {"name": "TestDevice", "target": "router1.example.com"}

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "SSH connection error" in result["error"]
        mock_ssh_client.close.assert_called_once()

    def test_ssh_collection_invalid_target(self, iosxr_client):
        # Use a clearly invalid target that will fail hostname parsing
        device = {"name": "TestDevice", "target": "ssh://[invalid"}

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "Invalid target format" in result["error"]

    def test_ssh_collection_no_target(self, iosxr_client):
        device = {"name": "TestDevice"}

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "No target specified for device" in result["error"]

    @patch("paramiko.SSHClient")
    def test_ssh_authentication_failure(self, mock_ssh_client_class, iosxr_client):
        # Setup mock SSH client to raise authentication error
        mock_ssh_client = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh_client
        mock_ssh_client.connect.side_effect = paramiko.AuthenticationException(
            "Auth failed"
        )

        device = {"name": "TestDevice", "target": "router1.example.com"}

        result = iosxr_client.collect_via_ssh(device)

        assert result is not None
        assert "error" in result
        assert "SSH authentication failed" in result["error"]
        mock_ssh_client.close.assert_called_once()


class TestCollectFromDevice:
    def test_collect_from_device_routes_to_ssh(self, iosxr_client):
        device = {
            "name": "TestDevice",
            "protocol": "ssh",
            "target": "router1.example.com",
        }
        expected_result = {"config": "data"}

        with patch.object(
            iosxr_client, "collect_via_ssh", return_value=expected_result
        ) as mock_ssh_collect:
            result = iosxr_client.collect_from_device(device)

            assert result == expected_result
            mock_ssh_collect.assert_called_once_with(device)

    def test_collect_from_device_defaults_to_ssh(self, iosxr_client):
        device = {"name": "TestDevice", "target": "router1.example.com"}
        expected_result = {"config": "data"}

        with patch.object(
            iosxr_client, "collect_via_ssh", return_value=expected_result
        ) as mock_ssh_collect:
            result = iosxr_client.collect_from_device(device)

            assert result == expected_result
            mock_ssh_collect.assert_called_once_with(device)

    def test_collect_from_device_unsupported_protocol_falls_back_to_ssh(
        self, iosxr_client
    ):
        device = {
            "name": "TestDevice",
            "protocol": "restconf",
            "target": "router1.example.com",
        }
        expected_result = {"config": "data"}

        with patch.object(
            iosxr_client, "collect_via_ssh", return_value=expected_result
        ) as mock_ssh_collect:
            with patch.object(iosxr_client.logger, "warning") as mock_warning:
                result = iosxr_client.collect_from_device(device)

                assert result == expected_result
                mock_ssh_collect.assert_called_once_with(device)
                mock_warning.assert_called_once_with(
                    "Protocol restconf not supported for IOSXR, using SSH"
                )


class TestConstants:
    def test_solution_constant(self):
        assert CiscoClientIOSXR.SOLUTION == "iosxr"

    def test_default_protocol_constant(self):
        assert CiscoClientIOSXR.DEFAULT_PROTOCOL == "ssh"

    def test_ssh_timeout_constant(self):
        assert CiscoClientIOSXR.SSH_TIMEOUT == 60

    def test_ssh_command_constant(self):
        assert (
            CiscoClientIOSXR.SSH_COMMAND == "show running-config | json unified-model"
        )
