import concurrent.futures
import json
import logging
import re
import zipfile
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

import paramiko  # type: ignore[import-untyped]
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)


class CiscoClientDevice(ABC):
    """
    Abstract Base Class for controller-less device collection.
    Manages connections to multiple individual devices.
    """

    def __init__(
        self,
        devices: list[dict[str, Any]],
        default_username: str,
        default_password: str,
        max_retries: int,
        retry_after: int,
        timeout: int,
        ssl_verify: bool = False,
    ) -> None:
        self.devices = devices
        self.default_username = default_username
        self.default_password = default_password
        self.max_retries = max_retries
        self.retry_after = retry_after
        self.timeout = timeout
        self.ssl_verify = ssl_verify
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def authenticate_device(self, device: dict[str, Any]) -> bool:
        """Authenticate to an individual device"""

    @abstractmethod
    def collect_from_device(self, device: dict[str, Any]) -> dict[str, Any]:
        """
        Collect full configuration from a single device.
        Device-based solutions typically have a single endpoint for full config.
        """

    def get_device_credentials(self, device: dict[str, Any]) -> tuple[str, str]:
        """Get credentials for a device (device-specific or defaults)"""
        username = device.get("username", self.default_username)
        password = device.get("password", self.default_password)
        return username, password

    def _execute_ssh_command(
        self, device: dict[str, Any], command: str, timeout: int = 60
    ) -> dict[str, Any]:
        """
        Execute SSH command on device and return parsed JSON.
        Common SSH logic shared between device types.
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
                timeout=timeout,
                look_for_keys=False,
                allow_agent=False,
            )

            self.logger.debug(
                f"Collecting configuration from {device.get('name')} via SSH"
            )

            # Execute the command
            _, stdout, stderr = ssh_client.exec_command(command)  # nosec B601

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
                # Clean output by removing non-JSON lines (like timestamps, comments)
                cleaned_output = self._clean_ssh_output(output)

                # Parse JSON output
                config_data = json.loads(cleaned_output)

                # Apply device-specific post-processing
                processed_data = self._process_ssh_output(config_data)

                self.logger.info(
                    f"Successfully collected configuration from {device.get('name')} via SSH"
                )
                return processed_data  # type: ignore[no-any-return]

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

    def _clean_ssh_output(self, output: str) -> str:
        """
        Clean SSH command output by removing non-JSON lines.
        Filters out timestamps, comments, and other non-JSON content that may
        appear before the actual JSON data in device outputs.
        """
        lines = output.split("\n")
        cleaned_lines = []

        # Find the first line that starts with '{'
        json_start_index = None
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                json_start_index = i
                break

        # If no JSON start found, return original output
        if json_start_index is None:
            return output

        # Include everything from the JSON start onwards
        # This preserves the complete JSON structure and any content after it
        cleaned_lines = lines[json_start_index:]

        return "\n".join(cleaned_lines)

    def _process_ssh_output(self, config_data: dict[str, Any]) -> dict[str, Any]:
        """
        Process SSH command output after JSON parsing.
        Subclasses can override this to apply device-specific transformations.
        Default implementation returns data as-is.
        """
        return config_data

    def sanitize_filename(self, name: str) -> str:
        """Sanitize device name to create a valid filename."""
        # First strip whitespace
        sanitized = name.strip()
        # Replace invalid filename characters with underscores
        # Invalid chars: < > : " | ? * / \ and control characters
        sanitized = re.sub(r'[<>:"|?*/\\]', "_", sanitized)
        # Replace multiple consecutive underscores with single underscore
        sanitized = re.sub(r"_+", "_", sanitized)
        # Remove leading/trailing underscores
        sanitized = sanitized.strip("_")
        # Ensure we have a non-empty filename
        if not sanitized:
            sanitized = "device"
        return sanitized

    def collect_and_write_to_archive(self, output: str) -> None:
        """
        Collect from all devices and write individual JSON files to ZIP archive.
        Each device gets its own JSON file named after the device.
        """
        successful = 0
        failed = 0

        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Collect from devices in parallel with progress bar
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=None,
            ) as progress:
                task = progress.add_task("Processing devices", total=len(self.devices))

                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {
                        executor.submit(
                            self._collect_with_error_handling, device
                        ): device
                        for device in self.devices
                    }

                    # Process results as they complete
                    for future in concurrent.futures.as_completed(futures):
                        progress.advance(task)
                        device = futures[future]
                        device_name = device.get("name", device.get("url", "unknown"))
                        sanitized_name = self.sanitize_filename(device_name)
                        json_filename = f"{sanitized_name}.json"

                        try:
                            device_data = future.result()
                            if device_data:
                                # Write device data to JSON file in archive
                                json_content = json.dumps(device_data, indent=4)
                                zip_file.writestr(json_filename, json_content)
                                successful += 1
                                self.logger.info(
                                    f"Successfully collected from {device_name}"
                                )
                            else:
                                # Write error information for failed device
                                error_data = {
                                    "device": device_name,
                                    "error": "Collection failed - authentication or connection error",
                                }
                                json_content = json.dumps(error_data, indent=4)
                                zip_file.writestr(json_filename, json_content)
                                failed += 1
                                self.logger.error(
                                    f"Failed to collect from {device_name}"
                                )
                        except Exception as e:
                            # Write error information for failed device
                            error_data = {"device": device_name, "error": str(e)}
                            json_content = json.dumps(error_data, indent=4)
                            zip_file.writestr(json_filename, json_content)
                            failed += 1
                            self.logger.error(
                                f"Error collecting from {device_name}: {e}"
                            )

        self.logger.info(
            f"Collection complete: {successful} successful, {failed} failed. "
            f"Data written to {output}"
        )

    def _collect_with_error_handling(
        self, device: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Wrapper to handle device collection with authentication"""
        try:
            if self.authenticate_device(device):
                return self.collect_from_device(device)
            else:
                self.logger.error(f"Authentication failed for {device.get('name')}")
                return None
        except Exception as e:
            self.logger.error(f"Error with device {device.get('name')}: {e}")
            raise
