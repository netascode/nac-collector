"""Helper module for 1Password CLI integration."""

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class OnePasswordError(Exception):
    """Exception raised for 1Password CLI errors."""

    pass


def check_op_cli_available() -> bool:
    """
    Check if 1Password CLI is available and accessible.

    Returns:
        bool: True if op CLI is available, False otherwise.
    """
    try:
        result = subprocess.run(
            ["op", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def get_op_item(item_reference: str) -> dict[str, Any]:
    """
    Retrieve an item from 1Password using the CLI.

    Args:
        item_reference: The item reference (item name, UUID, or share link).

    Returns:
        Dictionary containing the item data.

    Raises:
        OnePasswordError: If retrieval fails or op CLI is not available.
    """
    if not check_op_cli_available():
        raise OnePasswordError(
            "1Password CLI (op) is not available. "
            "Please install from https://developer.1password.com/docs/cli/get-started/"
        )

    try:
        result = subprocess.run(
            ["op", "item", "get", item_reference, "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        item_dict: dict[str, Any] = json.loads(result.stdout)
        return item_dict
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to retrieve 1Password item: {e.stderr}")
        raise OnePasswordError(
            f"Failed to retrieve item '{item_reference}': {e.stderr.strip()}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise OnePasswordError(
            f"Timeout while retrieving item '{item_reference}'"
        ) from e
    except json.JSONDecodeError as e:
        raise OnePasswordError(
            f"Failed to parse 1Password CLI output for '{item_reference}'"
        ) from e


def extract_credentials(
    item_data: dict[str, Any]
) -> tuple[str | None, str | None, str | None]:
    """
    Extract username, password, and URL from 1Password item data.

    Args:
        item_data: The 1Password item data dictionary.

    Returns:
        Tuple of (username, password, url). Any field may be None if not found.
        Note: URL paths like /login.html are preserved for SSO bypass requirements.
    """
    username = None
    password = None
    url = None

    # Extract from fields array
    fields = item_data.get("fields", [])
    for field in fields:
        field_id = field.get("id", "").lower()
        field_label = field.get("label", "").lower()
        field_value = field.get("value")

        # Match username field
        if field_id == "username" or "username" in field_label:
            username = field_value
        # Match password field
        elif field_id == "password" or "password" in field_label:
            password = field_value
        # Match URL field
        elif field_id in ["url", "website"] or any(
            term in field_label for term in ["url", "website", "address"]
        ):
            url = field_value

    # Try to extract URL from urls array if not found in fields
    if not url:
        urls = item_data.get("urls", [])
        if urls and len(urls) > 0:
            url = urls[0].get("href")

    return username, password, url


def get_credentials_from_op(
    item_reference: str,
) -> tuple[str | None, str | None, str | None]:
    """
    Get credentials from 1Password for a given item reference.

    Args:
        item_reference: The 1Password item reference.

    Returns:
        Tuple of (username, password, url).

    Raises:
        OnePasswordError: If retrieval or parsing fails.
    """
    logger.debug(f"Retrieving credentials from 1Password item: {item_reference}")

    item_data = get_op_item(item_reference)
    username, password, url = extract_credentials(item_data)

    logger.debug(
        f"Extracted from 1Password - username: {'***' if username else 'None'}, "
        f"password: {'***' if password else 'None'}, "
        f"url: {url or 'None'}"
    )

    return username, password, url
