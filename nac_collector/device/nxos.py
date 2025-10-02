import json
from typing import Any

import httpx

from nac_collector.device.base import CiscoClientDevice


class CiscoClientNXOS(CiscoClientDevice):
    """NXOS device client using REST API with aaaLogin authentication."""

    SOLUTION = "nxos"
    DEFAULT_PROTOCOL = "rest"
    AUTH_ENDPOINT = "/api/aaaLogin.json"
    CONFIG_ENDPOINT = (
        "/api/mo/sys.json?rsp-subtree=full&rsp-prop-include=set-config-only"
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._authenticated_clients: dict[str, httpx.Client] = {}

    def authenticate_device(self, device: dict[str, Any]) -> bool:
        """
        Authenticate to NXOS device using aaaLogin endpoint.
        Stores authenticated client for reuse during collection.
        """
        username, password = self.get_device_credentials(device)
        target = device.get("target")
        device_name = device.get("name", "unknown")

        if not target:
            self.logger.error(f"No target specified for device {device_name}")
            return False

        # Ensure target has proper scheme
        if not target.startswith(("http://", "https://")):
            target = f"https://{target}"

        # Create HTTP client
        client = httpx.Client(
            verify=self.ssl_verify,
            timeout=self.timeout,
        )

        try:
            # Authenticate using aaaLogin
            auth_url = f"{target}{self.AUTH_ENDPOINT}"
            auth_data = {"aaaUser": {"attributes": {"name": username, "pwd": password}}}

            self.logger.debug(f"Authenticating to {device_name} via REST")
            auth_response = client.post(auth_url, json=auth_data)

            if auth_response.status_code != 200:
                self.logger.error(
                    f"Authentication failed for {device_name} with status code: {auth_response.status_code}"
                )
                client.close()
                return False

            # Validate authentication response
            try:
                _ = auth_response.json()
            except (json.JSONDecodeError, Exception) as e:
                self.logger.error(
                    f"Failed to parse authentication response for {device_name}: {e}"
                )
                client.close()
                return False

            # Store authenticated client for this device
            self._authenticated_clients[device_name] = client
            self.logger.info(f"Successfully authenticated to {device_name}")
            return True

        except httpx.RequestError as e:
            self.logger.error(f"Authentication connection error to {device_name}: {e}")
            client.close()
            return False
        except Exception as e:
            self.logger.error(f"Authentication error for {device_name}: {e}")
            client.close()
            return False

    def collect_from_device(self, device: dict[str, Any]) -> dict[str, Any]:
        """Collect configuration from NXOS device via REST API."""
        protocol = device.get("protocol", self.DEFAULT_PROTOCOL)

        if protocol != "rest":
            self.logger.warning(
                f"Protocol {protocol} not supported for NXOS, using REST"
            )

        return self.collect_via_rest(device)

    def collect_via_rest(self, device: dict[str, Any]) -> dict[str, Any]:
        """Collect configuration from NXOS device via REST API using authenticated client."""
        device_name = device.get("name", "unknown")
        target = device.get("target")

        if not target:
            return {"error": "No target specified for device"}

        # Ensure target has proper scheme
        if not target.startswith(("http://", "https://")):
            target = f"https://{target}"

        # Get authenticated client for this device
        client = self._authenticated_clients.get(device_name)
        if not client:
            return {"error": f"No authenticated client found for device {device_name}"}

        try:
            # Collect configuration data using authenticated client
            config_url = f"{target}{self.CONFIG_ENDPOINT}"

            self.logger.debug(f"Collecting configuration from {device_name} via REST")
            config_response = client.get(config_url)

            if config_response.status_code != 200:
                self.logger.error(
                    f"Configuration collection failed for {device_name} with status code: {config_response.status_code}"
                )
                return {
                    "error": f"Configuration collection failed with status code {config_response.status_code}"
                }

            try:
                config_data = config_response.json()

                # Process the response to extract the first element from imdata
                processed_data = self._process_rest_output(config_data)

                self.logger.info(
                    f"Successfully collected configuration from {device_name} via REST"
                )
                return processed_data  # type: ignore[no-any-return]
            except (json.JSONDecodeError, Exception) as e:
                self.logger.error(
                    f"Failed to parse configuration JSON from {device_name}: {e}"
                )
                return {
                    "error": f"Failed to parse configuration JSON: {str(e)}",
                    "raw_output": config_response.text,
                }

        except httpx.RequestError as e:
            error_msg = f"REST connection error to {device_name}: {e}"
            self.logger.error(error_msg)
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"Error collecting from {device_name}: {e}"
            self.logger.error(error_msg)
            return {"error": error_msg}

    def _process_rest_output(self, config_data: dict[str, Any]) -> Any:
        """
        Process NXOS REST API output to extract the first element from imdata.
        NXOS API returns data in the format: {"imdata": [<config_object>]}
        We want only the first element of the imdata list.
        """
        if (
            isinstance(config_data, dict)
            and "imdata" in config_data
            and isinstance(config_data["imdata"], list)
            and len(config_data["imdata"]) > 0
        ):
            return config_data["imdata"][0]
        else:
            # Return original data if it doesn't match expected format
            return config_data

    def __del__(self) -> None:
        """Clean up authenticated clients when object is destroyed."""
        for client in self._authenticated_clients.values():
            try:
                client.close()
            except (AttributeError, RuntimeError):  # nosec B110
                # Ignore cleanup errors during object destruction
                # AttributeError: client may not have close method
                # RuntimeError: cleanup during interpreter shutdown
                continue
