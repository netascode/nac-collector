from typing import Any

import httpx

from nac_collector.device.base import CiscoClientDevice


class CiscoClientIOSXE(CiscoClientDevice):
    """
    IOSXE device collection via RESTCONF API.
    Supports Catalyst switches and routers running IOSXE.
    """

    SOLUTION = "iosxe"
    DEFAULT_PROTOCOL = "restconf"
    # Single endpoint to retrieve full configuration
    CONFIG_ENDPOINT = "/restconf/data/Cisco-IOS-XE-native:native"
    # Increased timeout for /restconf/data requests (120 seconds)
    RESTCONF_DATA_TIMEOUT = 120
    # SSH timeout for connection and command execution (60 seconds)
    SSH_TIMEOUT = 60
    # SSH command to get configuration in restconf-json format
    SSH_COMMAND = "show running-config | format restconf-json"

    def authenticate_device(self, device: dict[str, Any]) -> bool:
        """
        Authentication is handled as part of the collection process.
        This method always returns True as there's no separate authentication phase.
        """
        return True

    def collect_via_ssh(self, device: dict[str, Any]) -> dict[str, Any]:
        """
        Collect full configuration from IOSXE device via SSH.
        Executes 'show running-config | format restconf-json' command.
        """
        return self._execute_ssh_command(device, self.SSH_COMMAND, self.SSH_TIMEOUT)

    def _process_ssh_output(self, config_data: dict[str, Any]) -> dict[str, Any]:
        """
        Process IOSXE SSH output by removing the 'data' wrapper if present.
        """
        # Extract only the Cisco-IOS-XE-native:native data, removing the 'data' wrapper
        if isinstance(config_data, dict) and "data" in config_data:
            return config_data["data"]  # type: ignore[no-any-return]
        else:
            return config_data

    def collect_from_device(self, device: dict[str, Any]) -> dict[str, Any]:
        """
        Collect full configuration from IOSXE device via RESTCONF or SSH.
        Uses appropriate method based on the protocol specified in device config.
        """
        protocol = device.get("protocol", self.DEFAULT_PROTOCOL)

        if protocol == "ssh":
            return self.collect_via_ssh(device)
        elif protocol == "restconf":
            return self.collect_via_restconf(device)
        else:
            self.logger.warning(f"Protocol {protocol} not supported, using restconf")
            return self.collect_via_restconf(device)

    def collect_via_restconf(self, device: dict[str, Any]) -> dict[str, Any]:
        """
        Collect full configuration from IOSXE device via RESTCONF.
        Uses a single endpoint to retrieve the complete native configuration.
        """
        username, password = self.get_device_credentials(device)
        target = device.get("target")

        if not target:
            return {"error": "No target specified for device"}

        # Construct full URL for configuration endpoint
        # If target doesn't start with http/https, assume it needs https://
        if not target.startswith(("http://", "https://")):
            base_url = f"https://{target}"
        else:
            base_url = target

        config_url = f"{base_url}{self.CONFIG_ENDPOINT}"

        try:
            with httpx.Client(
                verify=self.ssl_verify,
                auth=(username, password),
                timeout=self.RESTCONF_DATA_TIMEOUT,
                headers={"Accept": "application/yang-data+json"},
            ) as client:
                self.logger.debug(f"Collecting configuration from {device.get('name')}")
                response = client.get(config_url)

                if response.status_code == 200:
                    # Return the full configuration
                    config_data = response.json()
                    self.logger.info(
                        f"Successfully collected configuration from {device.get('name')}"
                    )
                    return config_data  # type: ignore[no-any-return]
                else:
                    self.logger.error(
                        f"Failed to collect configuration from {device.get('name')}: "
                        f"HTTP {response.status_code}"
                    )
                    return {
                        "error": f"Failed to collect configuration - HTTP {response.status_code}"
                    }

        except Exception as e:
            self.logger.error(f"Error collecting from {device.get('name')}: {e}")
            return {"error": f"Collection failed - {str(e)}"}
