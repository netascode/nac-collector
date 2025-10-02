from typing import Any

from nac_collector.device.base import CiscoClientDevice


class CiscoClientIOSXR(CiscoClientDevice):
    """
    IOSXR device collection via SSH.
    Supports routers running IOS-XR.
    """

    SOLUTION = "iosxr"
    DEFAULT_PROTOCOL = "ssh"
    # SSH timeout for connection and command execution (60 seconds)
    SSH_TIMEOUT = 60
    # SSH command to get configuration in JSON unified model format
    SSH_COMMAND = "show running-config | json unified-model"

    def authenticate_device(self, device: dict[str, Any]) -> bool:
        """
        Authentication is handled as part of the collection process.
        This method always returns True as there's no separate authentication phase.
        """
        return True

    def collect_via_ssh(self, device: dict[str, Any]) -> dict[str, Any]:
        """
        Collect full configuration from IOSXR device via SSH.
        Executes 'show running-config | json unified-model' command.
        """
        return self._execute_ssh_command(device, self.SSH_COMMAND, self.SSH_TIMEOUT)

    def collect_from_device(self, device: dict[str, Any]) -> dict[str, Any]:
        """
        Collect full configuration from IOSXR device via SSH.
        IOS-XR only supports SSH collection.
        """
        protocol = device.get("protocol", self.DEFAULT_PROTOCOL)

        if protocol != "ssh":
            self.logger.warning(
                f"Protocol {protocol} not supported for IOSXR, using SSH"
            )

        return self.collect_via_ssh(device)
