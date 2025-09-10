import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer

from nac_collector.cli.main import LogLevel, Solution, main

pytestmark = pytest.mark.unit


@pytest.fixture
def sample_devices_yaml():
    """Create a temporary YAML file with sample devices."""
    yaml_content = """
- name: TestDevice1
  url: https://device1.example.com
  username: device1_user
  password: device1_pass
- name: TestDevice2
  url: https://device2.example.com
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


class TestDeviceBasedSolutions:
    @patch("nac_collector.cli.main.CiscoClientIOSXE")
    @patch("nac_collector.cli.main.load_devices_from_file")
    def test_iosxe_solution_with_devices_file(
        self, mock_load_devices, mock_iosxe_class, sample_devices_yaml
    ):
        # Setup mocks
        mock_devices = [
            {"name": "Device1", "url": "https://device1.example.com"},
            {"name": "Device2", "url": "https://device2.example.com"},
        ]
        mock_load_devices.return_value = mock_devices

        mock_client = MagicMock()
        mock_iosxe_class.return_value = mock_client

        # Test IOSXE solution with devices file
        with patch("nac_collector.cli.main.time.time", side_effect=[0, 5]):
            with pytest.raises(typer.Exit) as exc_info:
                main(
                    solution=Solution.IOSXE,
                    username="test_user",
                    password="test_pass",
                    url="http://unused.com",  # Should be ignored for device-based
                    devices_file=sample_devices_yaml,
                    verbosity=LogLevel.WARNING,
                    fetch_latest=False,
                    endpoints_file=None,
                    timeout=30,
                    output=None,
                    version=None,
                )

            # Verify successful exit
            assert exc_info.value.exit_code == 0

        # Verify devices were loaded
        mock_load_devices.assert_called_once_with(sample_devices_yaml)

        # Verify IOSXE client was created with correct parameters
        mock_iosxe_class.assert_called_once_with(
            devices=mock_devices,
            default_username="test_user",
            default_password="test_pass",
            max_retries=5,
            retry_after=60,
            timeout=30,
            ssl_verify=False,
        )

        # Verify collection was called with default output file
        mock_client.collect_and_write_to_archive.assert_called_once_with(
            "nac-collector.zip"
        )

    @patch("nac_collector.cli.main.CiscoClientIOSXE")
    @patch("nac_collector.cli.main.load_devices_from_file")
    def test_iosxe_solution_with_custom_output(
        self, mock_load_devices, mock_iosxe_class, sample_devices_yaml
    ):
        # Setup mocks
        mock_load_devices.return_value = [
            {"name": "Device1", "url": "https://device1.example.com"}
        ]
        mock_client = MagicMock()
        mock_iosxe_class.return_value = mock_client

        # Test with custom output file
        with patch("nac_collector.cli.main.time.time", side_effect=[0, 5]):
            with pytest.raises(typer.Exit) as exc_info:
                main(
                    solution=Solution.IOSXE,
                    username="test_user",
                    password="test_pass",
                    url="http://unused.com",
                    devices_file=sample_devices_yaml,
                    output="custom_output.zip",
                    verbosity=LogLevel.WARNING,
                    fetch_latest=False,
                    endpoints_file=None,
                    timeout=30,
                    version=None,
                )

            # Verify successful exit
            assert exc_info.value.exit_code == 0

        # Verify collection was called with custom output file
        mock_client.collect_and_write_to_archive.assert_called_once_with(
            "custom_output.zip"
        )

    @patch("nac_collector.cli.main.load_devices_from_file")
    def test_iosxe_solution_missing_devices_file(self, mock_load_devices):
        # Test that missing devices file raises error
        with pytest.raises(typer.Exit) as exc_info:
            main(
                solution=Solution.IOSXE,
                username="test_user",
                password="test_pass",
                url="http://unused.com",
                devices_file=None,  # Missing devices file
                verbosity=LogLevel.WARNING,
                fetch_latest=False,
                endpoints_file=None,
                timeout=30,
                output=None,
                version=None,
            )

        assert exc_info.value.exit_code == 1
        mock_load_devices.assert_not_called()

    @patch("nac_collector.cli.main.load_devices_from_file")
    def test_iosxe_solution_empty_devices_file(
        self, mock_load_devices, sample_devices_yaml
    ):
        # Test that empty devices list raises error
        mock_load_devices.return_value = []

        with pytest.raises(typer.Exit) as exc_info:
            main(
                solution=Solution.IOSXE,
                username="test_user",
                password="test_pass",
                url="http://unused.com",
                devices_file=sample_devices_yaml,
                verbosity=LogLevel.WARNING,
                fetch_latest=False,
                endpoints_file=None,
                timeout=30,
                output=None,
                version=None,
            )

        assert exc_info.value.exit_code == 1
        mock_load_devices.assert_called_once_with(sample_devices_yaml)

    @patch("nac_collector.cli.main.CiscoClientIOSXE")
    @patch("nac_collector.cli.main.load_devices_from_file")
    @patch("nac_collector.cli.main.console")
    def test_iosxe_solution_ignores_endpoints_file_with_warning(
        self, mock_console, mock_load_devices, mock_iosxe_class, sample_devices_yaml
    ):
        # Setup mocks
        mock_load_devices.return_value = [
            {"name": "Device1", "url": "https://device1.example.com"}
        ]
        mock_client = MagicMock()
        mock_iosxe_class.return_value = mock_client

        # Test with endpoints file (should be ignored with warning)
        with patch("nac_collector.cli.main.time.time", side_effect=[0, 5]):
            with pytest.raises(typer.Exit) as exc_info:
                main(
                    solution=Solution.IOSXE,
                    username="test_user",
                    password="test_pass",
                    url="http://unused.com",
                    devices_file=sample_devices_yaml,
                    endpoints_file="/path/to/endpoints.yaml",  # Should be ignored
                    verbosity=LogLevel.WARNING,
                    fetch_latest=False,
                    timeout=30,
                    output=None,
                    version=None,
                )

            # Verify successful exit
            assert exc_info.value.exit_code == 0

        # Verify warning was printed
        warning_calls = [
            call for call in mock_console.print.call_args_list if "Warning" in str(call)
        ]
        assert len(warning_calls) > 0
        assert "endpoints-file is ignored" in str(warning_calls[0])

    @patch("nac_collector.cli.main.CiscoClientIOSXR")
    @patch("nac_collector.cli.main.load_devices_from_file")
    def test_iosxr_solution_with_devices_file(
        self, mock_load_devices, mock_iosxr_class, sample_devices_yaml
    ):
        # Setup mocks
        mock_devices = [
            {"name": "Router1", "target": "router1.example.com"},
            {"name": "Router2", "target": "router2.example.com"},
        ]
        mock_load_devices.return_value = mock_devices

        mock_client = MagicMock()
        mock_iosxr_class.return_value = mock_client

        # Test IOSXR solution with devices file
        with patch("nac_collector.cli.main.time.time", side_effect=[0, 5]):
            with pytest.raises(typer.Exit) as exc_info:
                main(
                    solution=Solution.IOSXR,
                    username="test_user",
                    password="test_pass",
                    url="http://unused.com",  # Should be ignored for device-based
                    devices_file=sample_devices_yaml,
                    verbosity=LogLevel.WARNING,
                    fetch_latest=False,
                    endpoints_file=None,
                    timeout=30,
                    output=None,
                    version=None,
                )

            # Verify successful exit
            assert exc_info.value.exit_code == 0

        # Verify devices were loaded
        mock_load_devices.assert_called_once_with(sample_devices_yaml)

        # Verify IOSXR client was created with correct parameters
        mock_iosxr_class.assert_called_once_with(
            devices=mock_devices,
            default_username="test_user",
            default_password="test_pass",
            max_retries=5,
            retry_after=60,
            timeout=30,
            ssl_verify=False,
        )

        # Verify collection was called with default output file
        mock_client.collect_and_write_to_archive.assert_called_once_with(
            "nac-collector.zip"
        )

    @patch("nac_collector.cli.main.load_devices_from_file")
    def test_iosxr_solution_missing_devices_file(self, mock_load_devices):
        # Test that missing devices file raises error
        with pytest.raises(typer.Exit) as exc_info:
            main(
                solution=Solution.IOSXR,
                username="test_user",
                password="test_pass",
                url="http://unused.com",
                devices_file=None,  # Missing devices file
                verbosity=LogLevel.WARNING,
                fetch_latest=False,
                endpoints_file=None,
                timeout=30,
                output=None,
                version=None,
            )

        assert exc_info.value.exit_code == 1
        mock_load_devices.assert_not_called()


class TestControllerBasedSolutions:
    @patch("nac_collector.cli.main.CiscoClientISE")
    @patch("nac_collector.cli.main.EndpointResolver.resolve_endpoint_data")
    def test_ise_solution_still_works(self, mock_resolver, mock_ise_class):
        # Setup mocks
        mock_endpoints_data = [{"name": "test", "endpoint": "/test"}]
        mock_resolver.return_value = mock_endpoints_data

        mock_client = MagicMock()
        mock_client.authenticate.return_value = True
        mock_client.get_from_endpoints_data.return_value = {"test": "data"}
        mock_ise_class.return_value = mock_client

        # Test ISE solution (controller-based)
        with patch("nac_collector.cli.main.time.time", side_effect=[0, 5]):
            with pytest.raises(typer.Exit) as exc_info:
                main(
                    solution=Solution.ISE,
                    username="ise_user",
                    password="ise_pass",
                    url="https://ise-server.com",
                    devices_file=None,
                    verbosity=LogLevel.WARNING,
                    fetch_latest=False,
                    endpoints_file=None,
                    timeout=30,
                    output=None,
                    version=None,
                )

            # Verify successful exit
            assert exc_info.value.exit_code == 0

        # Verify endpoint resolution was called
        mock_resolver.assert_called_once_with(
            solution="ise",
            explicit_file=None,
            use_git_provider=False,
        )

        # Verify ISE client was created
        mock_ise_class.assert_called_once_with(
            username="ise_user",
            password="ise_pass",
            base_url="https://ise-server.com",
            max_retries=5,
            retry_after=60,
            timeout=30,
            ssl_verify=False,
        )

        # Verify authentication and collection
        mock_client.authenticate.assert_called_once()
        mock_client.get_from_endpoints_data.assert_called_once_with(mock_endpoints_data)
        mock_client.write_to_archive.assert_called_once_with(
            {"test": "data"}, "nac-collector.zip", "ise"
        )

    @patch("nac_collector.cli.main.EndpointResolver.resolve_endpoint_data")
    def test_controller_solution_missing_endpoints_data(self, mock_resolver):
        # Test that missing endpoint data raises error
        mock_resolver.return_value = None

        with pytest.raises(typer.Exit) as exc_info:
            main(
                solution=Solution.ISE,
                username="ise_user",
                password="ise_pass",
                url="https://ise-server.com",
                devices_file=None,
                verbosity=LogLevel.WARNING,
                fetch_latest=False,
                endpoints_file=None,
                timeout=30,
                output=None,
                version=None,
            )

        assert exc_info.value.exit_code == 1

    @patch("nac_collector.cli.main.CiscoClientISE")
    @patch("nac_collector.cli.main.EndpointResolver.resolve_endpoint_data")
    def test_controller_solution_authentication_failure(
        self, mock_resolver, mock_ise_class
    ):
        # Setup mocks
        mock_resolver.return_value = [{"name": "test", "endpoint": "/test"}]

        mock_client = MagicMock()
        mock_client.authenticate.return_value = False  # Auth failure
        mock_ise_class.return_value = mock_client

        # Test authentication failure
        with pytest.raises(typer.Exit) as exc_info:
            main(
                solution=Solution.ISE,
                username="ise_user",
                password="wrong_pass",
                url="https://ise-server.com",
                devices_file=None,
                verbosity=LogLevel.WARNING,
                fetch_latest=False,
                endpoints_file=None,
                timeout=30,
                output=None,
                version=None,
            )

        assert exc_info.value.exit_code == 1
        mock_client.authenticate.assert_called_once()
        mock_client.get_from_endpoints_data.assert_not_called()


class TestSpecialCases:
    def test_ndo_fetch_latest_incompatibility(self):
        # Test that NDO + fetch_latest raises error
        with pytest.raises(typer.Exit) as exc_info:
            main(
                solution=Solution.NDO,
                username="ndo_user",
                password="ndo_pass",
                url="https://ndo-server.com",
                devices_file=None,
                verbosity=LogLevel.WARNING,
                fetch_latest=True,  # Should cause error with NDO
                endpoints_file=None,
                timeout=30,
                output=None,
                version=None,
            )

        assert exc_info.value.exit_code == 1

    @patch("nac_collector.cli.main.CiscoClientIOSXE")
    @patch("nac_collector.cli.main.load_devices_from_file")
    @patch("nac_collector.cli.main.time.time")
    @patch("nac_collector.cli.main.logger")
    def test_execution_time_logging(
        self,
        mock_logger,
        mock_time,
        mock_load_devices,
        mock_iosxe_class,
        sample_devices_yaml,
    ):
        # Test that execution time is logged for successful completion
        mock_time.side_effect = [100.0, 105.5]  # 5.5 seconds

        # Setup mocks for successful execution
        mock_load_devices.return_value = [
            {"name": "Device1", "url": "https://device1.example.com"}
        ]
        mock_client = MagicMock()
        mock_iosxe_class.return_value = mock_client

        with pytest.raises(typer.Exit) as exc_info:
            main(
                solution=Solution.IOSXE,
                username="test_user",
                password="test_pass",
                url="http://unused.com",
                devices_file=sample_devices_yaml,
                verbosity=LogLevel.WARNING,
                fetch_latest=False,
                endpoints_file=None,
                timeout=30,
                output=None,
                version=None,
            )

        # Verify successful exit
        assert exc_info.value.exit_code == 0

        # Verify time was logged
        mock_logger.info.assert_called_with("Total execution time: 5.50 seconds")


class TestSolutionEnum:
    def test_solution_enum_contains_iosxe(self):
        # Test that IOSXE is in the Solution enum
        assert hasattr(Solution, "IOSXE")
        assert Solution.IOSXE == "IOSXE"

    def test_solution_enum_contains_iosxr(self):
        # Test that IOSXR is in the Solution enum
        assert hasattr(Solution, "IOSXR")
        assert Solution.IOSXR == "IOSXR"

    def test_all_solutions_present(self):
        # Test that all expected solutions are present
        expected_solutions = [
            "SDWAN",
            "ISE",
            "NDO",
            "FMC",
            "CATALYSTCENTER",
            "IOSXE",
            "IOSXR",
        ]
        actual_solutions = [solution.value for solution in Solution]

        for expected in expected_solutions:
            assert expected in actual_solutions
