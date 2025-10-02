import pytest

from nac_collector.device.base import CiscoClientDevice

pytestmark = pytest.mark.unit


class ConcreteCiscoClientDevice(CiscoClientDevice):
    """Concrete implementation of CiscoClientDevice for testing purposes."""

    def authenticate_device(self, device):
        return True

    def collect_from_device(self, device):
        return {"test": "data"}


@pytest.fixture
def device_client():
    return ConcreteCiscoClientDevice(
        devices=[],
        default_username="test_user",
        default_password="test_password",
        max_retries=3,
        retry_after=1,
        timeout=30,
        ssl_verify=False,
    )


class TestCleanSSHOutput:
    def test_clean_ssh_output_with_timestamp_and_comments(self, device_client):
        """Test cleaning SSH output with IOS-XR style timestamps and comments."""
        raw_output = """!! IOS XR Configuration 7.3.2
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

        expected_output = """{
  "Cisco-IOS-XR-clns-isis-cfg:isis": {
    "instances": [
      {
        "instance-name": "default"
      }
    ]
  }
}"""

        result = device_client._clean_ssh_output(raw_output)
        assert result == expected_output

    def test_clean_ssh_output_already_clean_json(self, device_client):
        """Test cleaning SSH output that's already clean JSON."""
        raw_output = """{
  "Cisco-IOS-XR-clns-isis-cfg:isis": {
    "instances": [
      {
        "instance-name": "default"
      }
    ]
  }
}"""

        result = device_client._clean_ssh_output(raw_output)
        assert result == raw_output

    def test_clean_ssh_output_with_mixed_content(self, device_client):
        """Test cleaning SSH output with mixed content before JSON."""
        raw_output = """Building configuration...
!! IOS XR Configuration 7.3.2
!! Last configuration change at Wed Jan 10 15:30:25 2024 by admin
!!

{
  "Cisco-IOS-XR-clns-isis-cfg:isis": {
    "instances": []
  }
}
!! End of configuration"""

        expected_output = """{
  "Cisco-IOS-XR-clns-isis-cfg:isis": {
    "instances": []
  }
}
!! End of configuration"""

        result = device_client._clean_ssh_output(raw_output)
        assert result == expected_output

    def test_clean_ssh_output_empty_input(self, device_client):
        """Test cleaning empty SSH output."""
        raw_output = ""
        result = device_client._clean_ssh_output(raw_output)
        assert result == ""

    def test_clean_ssh_output_only_comments(self, device_client):
        """Test cleaning SSH output with only comments."""
        raw_output = """!! IOS XR Configuration 7.3.2
!! Last configuration change at Wed Jan 10 15:30:25 2024 by admin
!!
"""
        result = device_client._clean_ssh_output(raw_output)
        # Should return original output when no JSON is found
        assert result == raw_output

    def test_clean_ssh_output_preserves_internal_comments(self, device_client):
        """Test that comments within JSON are preserved."""
        raw_output = """!! Header comment
{
  "config": {
    "description": "!! This is not a comment, it's data"
  }
}"""

        expected_output = """{
  "config": {
    "description": "!! This is not a comment, it's data"
  }
}"""

        result = device_client._clean_ssh_output(raw_output)
        assert result == expected_output


class TestProcessSSHOutput:
    def test_process_ssh_output_default_implementation(self, device_client):
        """Test that default _process_ssh_output returns data unchanged."""
        input_data = {"test": "data", "nested": {"key": "value"}}
        result = device_client._process_ssh_output(input_data)
        assert result == input_data

    def test_process_ssh_output_with_empty_dict(self, device_client):
        """Test _process_ssh_output with empty dictionary."""
        input_data = {}
        result = device_client._process_ssh_output(input_data)
        assert result == input_data
