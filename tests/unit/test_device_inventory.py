import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nac_collector.device_inventory import load_devices_from_file

pytestmark = pytest.mark.unit


class TestLoadDevicesFromFile:
    def test_load_valid_devices_file(self):
        yaml_content = """
- name: Switch1
  target: https://switch1.example.com
  username: admin
  password: cisco123
  protocol: restconf
- name: Switch2
  target: https://switch2.example.com
  protocol: restconf
- name: Router1
  target: https://router1.example.com
  username: router_admin
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            devices = load_devices_from_file(temp_path)

            assert len(devices) == 3

            # Check first device (all fields)
            assert devices[0]["name"] == "Switch1"
            assert devices[0]["target"] == "https://switch1.example.com"
            assert devices[0]["username"] == "admin"
            assert devices[0]["password"] == "cisco123"
            assert devices[0]["protocol"] == "restconf"

            # Check second device (minimal fields)
            assert devices[1]["name"] == "Switch2"
            assert devices[1]["target"] == "https://switch2.example.com"
            assert devices[1]["protocol"] == "restconf"
            assert "username" not in devices[1]
            assert "password" not in devices[1]

            # Check third device (mixed fields)
            assert devices[2]["name"] == "Router1"
            assert devices[2]["target"] == "https://router1.example.com"
            assert devices[2]["username"] == "router_admin"
            assert "password" not in devices[2]
            assert "protocol" not in devices[2]

        finally:
            Path(temp_path).unlink()

    def test_load_empty_devices_list(self):
        yaml_content = """[]"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            devices = load_devices_from_file(temp_path)
            assert devices == []
        finally:
            Path(temp_path).unlink()

    def test_invalid_format_dict_instead_of_list(self):
        yaml_content = """
configuration:
  - name: Switch1
    target: https://switch1.example.com
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            with patch("nac_collector.device_inventory.logger") as mock_logger:
                devices = load_devices_from_file(temp_path)

                assert devices == []
                mock_logger.error.assert_called_once_with(
                    "Invalid devices file format: expected a list of devices"
                )
        finally:
            Path(temp_path).unlink()

    def test_empty_file(self):
        yaml_content = ""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            with patch("nac_collector.device_inventory.logger") as mock_logger:
                devices = load_devices_from_file(temp_path)

                assert devices == []
                mock_logger.error.assert_called_once_with(
                    "Invalid devices file format: file is empty or invalid"
                )
        finally:
            Path(temp_path).unlink()

    def test_invalid_device_format_not_dict(self):
        yaml_content = """
- name: Switch1
  target: https://switch1.example.com
- "not a dictionary"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            with patch("nac_collector.device_inventory.logger") as mock_logger:
                devices = load_devices_from_file(temp_path)

                assert devices == []
                mock_logger.error.assert_called_once_with(
                    "Invalid device format: each device must be a dictionary"
                )
        finally:
            Path(temp_path).unlink()

    def test_device_missing_target(self):
        yaml_content = """
- name: Switch1
  username: admin
  password: cisco123
- name: Switch2
  target: https://switch2.example.com
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            with patch("nac_collector.device_inventory.logger") as mock_logger:
                devices = load_devices_from_file(temp_path)

                assert devices == []
                mock_logger.error.assert_called_once_with(
                    "Device Switch1 missing required 'target' field"
                )
        finally:
            Path(temp_path).unlink()

    def test_device_missing_name(self):
        yaml_content = """
- target: https://switch1.example.com
  username: admin
- name: Switch2
  target: https://switch2.example.com
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            with patch("nac_collector.device_inventory.logger") as mock_logger:
                devices = load_devices_from_file(temp_path)

                assert devices == []
                mock_logger.error.assert_called_once_with(
                    "Device at https://switch1.example.com missing required 'name' field"
                )
        finally:
            Path(temp_path).unlink()

    def test_file_not_found(self):
        non_existent_path = "/path/that/does/not/exist.yaml"

        with patch("nac_collector.device_inventory.logger") as mock_logger:
            devices = load_devices_from_file(non_existent_path)

            assert devices == []
            mock_logger.error.assert_called_once()
            # Check that the error message contains the expected text
            error_call = mock_logger.error.call_args[0][0]
            assert "Failed to load devices file" in error_call
            assert non_existent_path in error_call

    def test_invalid_yaml_syntax(self):
        yaml_content = """
- name: Switch1
  target: https://switch1.example.com
- name: Switch2
  target: https://switch2.example.com
  invalid_yaml: [unclosed bracket
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            with patch("nac_collector.device_inventory.logger") as mock_logger:
                devices = load_devices_from_file(temp_path)

                assert devices == []
                mock_logger.error.assert_called_once()
                error_call = mock_logger.error.call_args[0][0]
                assert "Failed to load devices file" in error_call
                assert temp_path in error_call
        finally:
            Path(temp_path).unlink()

    def test_successful_loading_logs_info(self):
        yaml_content = """
- name: Switch1
  target: https://switch1.example.com
- name: Switch2
  target: https://switch2.example.com
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            with patch("nac_collector.device_inventory.logger") as mock_logger:
                devices = load_devices_from_file(temp_path)

                assert len(devices) == 2
                mock_logger.info.assert_called_once_with(
                    f"Loaded 2 devices from {temp_path}"
                )
        finally:
            Path(temp_path).unlink()

    def test_single_device(self):
        yaml_content = """
- name: OnlyDevice
  target: https://only.example.com
  username: sole_user
  password: sole_pass
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            devices = load_devices_from_file(temp_path)

            assert len(devices) == 1
            assert devices[0]["name"] == "OnlyDevice"
            assert devices[0]["target"] == "https://only.example.com"
            assert devices[0]["username"] == "sole_user"
            assert devices[0]["password"] == "sole_pass"
        finally:
            Path(temp_path).unlink()

    def test_device_with_special_characters(self):
        yaml_content = """
- name: "Switch-1_test"
  target: "https://192.168.1.100:443"
  username: "admin@domain.com"
  password: "P@ssw0rd!123"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            devices = load_devices_from_file(temp_path)

            assert len(devices) == 1
            assert devices[0]["name"] == "Switch-1_test"
            assert devices[0]["target"] == "https://192.168.1.100:443"
            assert devices[0]["username"] == "admin@domain.com"
            assert devices[0]["password"] == "P@ssw0rd!123"
        finally:
            Path(temp_path).unlink()

    def test_multiple_validation_errors_stops_at_first(self):
        yaml_content = """
- name: Switch1
  # Missing target - should trigger first error
- # Missing name and target - would trigger second error if we got there
  username: admin
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            with patch("nac_collector.device_inventory.logger") as mock_logger:
                devices = load_devices_from_file(temp_path)

                assert devices == []
                # Should only call error once (for the first validation failure)
                mock_logger.error.assert_called_once_with(
                    "Device Switch1 missing required 'target' field"
                )
        finally:
            Path(temp_path).unlink()
