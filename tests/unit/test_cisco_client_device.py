import json
import zipfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nac_collector.device.base import CiscoClientDevice

pytestmark = pytest.mark.unit


class ConcreteCiscoClientDevice(CiscoClientDevice):
    """Concrete implementation of CiscoClientDevice for testing purposes."""

    def authenticate_device(self, device: dict[str, Any]) -> bool:
        """Mock authentication method."""
        return bool(device.get("auth_success", True))

    def collect_from_device(self, device: dict[str, Any]) -> dict[str, Any]:
        """Mock collection method."""
        device_name = device.get("name", "unknown")
        if device.get("collection_error"):
            raise Exception(f"Collection error for {device_name}")
        return {"device": device_name, "config": "test_config_data"}


@pytest.fixture
def sample_devices():
    """Sample device data for testing."""
    return [
        {
            "name": "Device1",
            "url": "https://device1.example.com",
            "username": "device1_user",
            "password": "device1_pass",
        },
        {
            "name": "Device2",
            "url": "https://device2.example.com",
        },
        {
            "name": "Device3",
            "url": "https://device3.example.com",
            "auth_success": False,
        },
    ]


@pytest.fixture
def client_device(sample_devices):
    """Create a ConcreteCiscoClientDevice instance for testing."""
    return ConcreteCiscoClientDevice(
        devices=sample_devices,
        default_username="default_user",
        default_password="default_pass",
        max_retries=3,
        retry_after=1,
        timeout=30,
        ssl_verify=False,
    )


class TestCiscoClientDeviceInit:
    def test_init_with_valid_parameters(self, sample_devices):
        client = ConcreteCiscoClientDevice(
            devices=sample_devices,
            default_username="user",
            default_password="pass",
            max_retries=5,
            retry_after=2,
            timeout=60,
            ssl_verify=True,
        )

        assert client.devices == sample_devices
        assert client.default_username == "user"
        assert client.default_password == "pass"
        assert client.max_retries == 5
        assert client.retry_after == 2
        assert client.timeout == 60
        assert client.ssl_verify is True


class TestGetDeviceCredentials:
    def test_get_device_specific_credentials(self, client_device):
        device = {
            "name": "TestDevice",
            "username": "device_user",
            "password": "device_pass",
        }
        username, password = client_device.get_device_credentials(device)
        assert username == "device_user"
        assert password == "device_pass"

    def test_get_default_credentials(self, client_device):
        device = {"name": "TestDevice"}
        username, password = client_device.get_device_credentials(device)
        assert username == "default_user"
        assert password == "default_pass"

    def test_get_mixed_credentials(self, client_device):
        device = {"name": "TestDevice", "username": "device_user"}
        username, password = client_device.get_device_credentials(device)
        assert username == "device_user"
        assert password == "default_pass"


class TestSanitizeFilename:
    def test_sanitize_valid_filename(self, client_device):
        result = client_device.sanitize_filename("TestDevice")
        assert result == "TestDevice"

    def test_sanitize_filename_with_invalid_chars(self, client_device):
        result = client_device.sanitize_filename("Test<Device>:Name")
        assert result == "Test_Device_Name"

    def test_sanitize_filename_with_path_separators(self, client_device):
        result = client_device.sanitize_filename("Test/Device\\Name")
        assert result == "Test_Device_Name"

    def test_sanitize_filename_with_quotes_and_pipes(self, client_device):
        result = client_device.sanitize_filename('Test"Device|Name')
        assert result == "Test_Device_Name"

    def test_sanitize_filename_with_multiple_underscores(self, client_device):
        result = client_device.sanitize_filename("Test___Device___Name")
        assert result == "Test_Device_Name"

    def test_sanitize_filename_with_leading_trailing_underscores(self, client_device):
        result = client_device.sanitize_filename("_TestDevice_")
        assert result == "TestDevice"

    def test_sanitize_filename_with_spaces(self, client_device):
        result = client_device.sanitize_filename("  Test Device  ")
        assert result == "Test Device"

    def test_sanitize_empty_filename(self, client_device):
        result = client_device.sanitize_filename("")
        assert result == "device"

    def test_sanitize_filename_with_only_invalid_chars(self, client_device):
        result = client_device.sanitize_filename('<>:"|?*/\\')
        assert result == "device"

    def test_sanitize_filename_complex_case(self, client_device):
        result = client_device.sanitize_filename('  _Switch-1/Core:Port"24|Main_  ')
        assert result == "Switch-1_Core_Port_24_Main"


class TestCollectWithErrorHandling:
    def test_successful_collection(self, client_device):
        device = {"name": "TestDevice", "auth_success": True}
        result = client_device._collect_with_error_handling(device)

        assert result is not None
        assert result["device"] == "TestDevice"
        assert result["config"] == "test_config_data"

    def test_authentication_failure(self, client_device):
        device = {"name": "TestDevice", "auth_success": False}
        result = client_device._collect_with_error_handling(device)

        assert result is None

    def test_collection_exception(self, client_device):
        device = {"name": "TestDevice", "collection_error": True}

        with pytest.raises(Exception, match="Collection error for TestDevice"):
            client_device._collect_with_error_handling(device)


class TestCollectAndWriteToArchive:
    @patch("zipfile.ZipFile")
    @patch("concurrent.futures.ThreadPoolExecutor")
    def test_successful_collection_all_devices(
        self, mock_executor, mock_zipfile, client_device
    ):
        # Mock successful futures
        mock_future1 = MagicMock()
        mock_future1.result.return_value = {"device": "Device1", "config": "data1"}
        mock_future2 = MagicMock()
        mock_future2.result.return_value = {"device": "Device2", "config": "data2"}
        mock_future3 = MagicMock()
        mock_future3.result.return_value = None  # Auth failure

        # Setup executor mock
        mock_executor_instance = mock_executor.return_value.__enter__.return_value
        mock_executor_instance.submit.side_effect = [
            mock_future1,
            mock_future2,
            mock_future3,
        ]

        # Mock as_completed to return futures in order
        with patch("concurrent.futures.as_completed") as mock_as_completed:
            mock_as_completed.return_value = [mock_future1, mock_future2, mock_future3]

            # Mock zipfile
            mock_zip_instance = mock_zipfile.return_value.__enter__.return_value

            # Run the method
            client_device.collect_and_write_to_archive("test_output.zip")

            # Verify zipfile was created correctly
            mock_zipfile.assert_called_once_with(
                "test_output.zip", "w", zipfile.ZIP_DEFLATED
            )

            # Verify JSON files were written
            assert mock_zip_instance.writestr.call_count == 3

            # Check the calls
            calls = mock_zip_instance.writestr.call_args_list

            # First device - successful
            filename1, content1 = calls[0][0]
            assert filename1 == "Device1.json"
            data1 = json.loads(content1)
            assert data1["device"] == "Device1"
            assert data1["config"] == "data1"

            # Second device - successful
            filename2, content2 = calls[1][0]
            assert filename2 == "Device2.json"
            data2 = json.loads(content2)
            assert data2["device"] == "Device2"
            assert data2["config"] == "data2"

            # Third device - auth failure
            filename3, content3 = calls[2][0]
            assert filename3 == "Device3.json"
            data3 = json.loads(content3)
            assert "error" in data3
            assert "authentication or connection error" in data3["error"]

    @patch("zipfile.ZipFile")
    @patch("concurrent.futures.ThreadPoolExecutor")
    def test_collection_with_exceptions(
        self, mock_executor, mock_zipfile, client_device
    ):
        # Mock future that raises exception
        mock_future = MagicMock()
        mock_future.result.side_effect = Exception("Network timeout")

        # Setup executor mock
        mock_executor_instance = mock_executor.return_value.__enter__.return_value
        mock_executor_instance.submit.return_value = mock_future

        # Mock as_completed
        with patch("concurrent.futures.as_completed") as mock_as_completed:
            mock_as_completed.return_value = [mock_future]

            # Mock zipfile
            mock_zip_instance = mock_zipfile.return_value.__enter__.return_value

            # Run with single device to simplify test
            client_device.devices = [{"name": "ErrorDevice"}]
            client_device.collect_and_write_to_archive("test_output.zip")

            # Verify error was written to JSON
            mock_zip_instance.writestr.assert_called_once()
            filename, content = mock_zip_instance.writestr.call_args[0]
            assert filename == "ErrorDevice.json"

            data = json.loads(content)
            assert data["device"] == "ErrorDevice"
            assert data["error"] == "Network timeout"

    def test_empty_device_list(self):
        client = ConcreteCiscoClientDevice(
            devices=[],
            default_username="user",
            default_password="pass",
            max_retries=3,
            retry_after=1,
            timeout=30,
        )

        with patch("zipfile.ZipFile") as mock_zipfile:
            mock_zip_instance = mock_zipfile.return_value.__enter__.return_value

            client.collect_and_write_to_archive("empty_output.zip")

            # Should create empty ZIP file
            mock_zipfile.assert_called_once_with(
                "empty_output.zip", "w", zipfile.ZIP_DEFLATED
            )
            mock_zip_instance.writestr.assert_not_called()

    @patch("zipfile.ZipFile")
    @patch("concurrent.futures.ThreadPoolExecutor")
    def test_filename_sanitization_in_archive(
        self, mock_executor, mock_zipfile, client_device
    ):
        # Mock successful future with device that has invalid filename characters
        mock_future = MagicMock()
        mock_future.result.return_value = {"device": "Switch/Core:1", "config": "data"}

        # Setup executor mock
        mock_executor_instance = mock_executor.return_value.__enter__.return_value
        mock_executor_instance.submit.return_value = mock_future

        # Mock as_completed
        with patch("concurrent.futures.as_completed") as mock_as_completed:
            mock_as_completed.return_value = [mock_future]

            # Mock zipfile
            mock_zip_instance = mock_zipfile.return_value.__enter__.return_value

            # Run with device that has invalid filename characters
            client_device.devices = [{"name": "Switch/Core:1"}]
            client_device.collect_and_write_to_archive("test_output.zip")

            # Verify sanitized filename was used
            mock_zip_instance.writestr.assert_called_once()
            filename, content = mock_zip_instance.writestr.call_args[0]
            assert filename == "Switch_Core_1.json"  # Should be sanitized

            data = json.loads(content)
            assert (
                data["device"] == "Switch/Core:1"
            )  # Original name preserved in content


class TestAbstractMethods:
    def test_abstract_methods_must_be_implemented(self):
        # Verify that CiscoClientDevice is abstract and cannot be instantiated
        with pytest.raises(TypeError):
            CiscoClientDevice(
                devices=[],
                default_username="user",
                default_password="pass",
                max_retries=3,
                retry_after=1,
                timeout=30,
            )
