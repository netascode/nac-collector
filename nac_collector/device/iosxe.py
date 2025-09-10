import json
from typing import Any
from urllib.parse import urlparse

import httpx
import paramiko  # type: ignore[import-untyped]

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
        username, password = self.get_device_credentials(device)
        target = device.get("target")

        if not target:
            return {"error": "No target specified for device"}

        # Parse hostname and port from target
        try:
            parsed_target = urlparse(
                f"ssh://{target}"
                if not target.startswith(("ssh://", "http://", "https://"))
                else target
            )
            hostname = parsed_target.hostname
            port = parsed_target.port or 22
        except ValueError:
            return {"error": f"Invalid target format: {target}"}

        if not hostname:
            return {"error": f"Invalid target format: {target}"}

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507

        try:
            # Connect to the device
            ssh_client.connect(
                hostname=hostname,
                port=port,
                username=username,
                password=password,
                timeout=self.SSH_TIMEOUT,
                look_for_keys=False,
                allow_agent=False,
            )

            self.logger.debug(
                f"Collecting configuration from {device.get('name')} via SSH"
            )

            # Execute the command to get configuration in restconf-json format
            _, stdout, stderr = ssh_client.exec_command(self.SSH_COMMAND)  # nosec B601

            # Wait for command completion and get exit status
            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0:
                error_output = stderr.read().decode("utf-8").strip()
                self.logger.error(
                    f"SSH command failed on {device.get('name')} with exit status {exit_status}: {error_output}"
                )
                return {
                    "error": f"SSH command failed with exit status {exit_status}: {error_output}"
                }

            # Read the output
            output = stdout.read().decode("utf-8").strip()

            if not output:
                self.logger.error(
                    f"No output received from SSH command on {device.get('name')}"
                )
                return {"error": "No output received from SSH command"}

            try:
                # Parse JSON output
                config_data = json.loads(output)

                # Extract only the Cisco-IOS-XE-native:native data, removing the 'data' wrapper
                if isinstance(config_data, dict) and "data" in config_data:
                    native_data = config_data["data"]
                else:
                    native_data = config_data

                self.logger.info(
                    f"Successfully collected configuration from {device.get('name')} via SSH"
                )
                return native_data  # type: ignore[no-any-return]

            except json.JSONDecodeError as e:
                self.logger.error(
                    f"Failed to parse JSON output from {device.get('name')}: {e}"
                )
                return {
                    "error": f"Failed to parse JSON output: {str(e)}",
                    "raw_output": output,
                }

        except paramiko.AuthenticationException:
            error_msg = f"SSH authentication failed for {device.get('name')}"
            self.logger.error(error_msg)
            return {"error": error_msg}
        except paramiko.SSHException as e:
            error_msg = f"SSH connection error to {device.get('name')}: {e}"
            self.logger.error(error_msg)
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"Error collecting from {device.get('name')}: {e}"
            self.logger.error(error_msg)
            return {"error": error_msg}
        finally:
            ssh_client.close()

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
