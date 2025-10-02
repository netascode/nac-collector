import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

logger = logging.getLogger(__name__)


def load_devices_from_file(file_path: str | Path) -> list[dict[str, Any]]:
    """
    Load device inventory from YAML file.

    Expected format:
    - name: Switch1
      target: https://1.1.1.1  # For RESTCONF: URL, for SSH: IP/hostname
      protocol: restconf  # optional
      username: admin     # optional
      password: cisco123  # optional

    Parameters:
        file_path (str | Path): Path to the YAML file containing device inventory

    Returns:
        list[dict[str, Any]]: List of device dictionaries, empty list on error
    """
    yaml = YAML(typ="safe", pure=True)

    try:
        path = Path(file_path)
        with path.open() as f:
            devices = yaml.load(f)

        if not devices:
            logger.error("Invalid devices file format: file is empty or invalid")
            return []

        if not isinstance(devices, list):
            logger.error("Invalid devices file format: expected a list of devices")
            return []

        # Validate required fields
        for device in devices:
            if not isinstance(device, dict):
                logger.error("Invalid device format: each device must be a dictionary")
                return []
            if "target" not in device:
                logger.error(
                    f"Device {device.get('name', 'unknown')} missing required 'target' field"
                )
                return []
            if "name" not in device:
                logger.error(
                    f"Device at {device.get('target')} missing required 'name' field"
                )
                return []

        logger.info(f"Loaded {len(devices)} devices from {file_path}")
        return devices  # type: ignore[no-any-return]

    except Exception as e:
        logger.error(f"Failed to load devices file {file_path}: {e}")
        return []
