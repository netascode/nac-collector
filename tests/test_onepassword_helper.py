"""Tests for 1Password helper module."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from nac_collector.onepassword_helper import (
    OnePasswordError,
    check_op_cli_available,
    extract_credentials,
    get_credentials_from_op,
    get_op_item,
)


class TestCheckOpCliAvailable:
    """Tests for check_op_cli_available function."""

    @patch("subprocess.run")
    def test_op_cli_available(self, mock_run: MagicMock) -> None:
        """Test when op CLI is available."""
        mock_run.return_value = MagicMock(returncode=0)
        assert check_op_cli_available() is True

    @patch("subprocess.run")
    def test_op_cli_not_available(self, mock_run: MagicMock) -> None:
        """Test when op CLI is not available."""
        mock_run.return_value = MagicMock(returncode=1)
        assert check_op_cli_available() is False

    @patch("subprocess.run")
    def test_op_cli_file_not_found(self, mock_run: MagicMock) -> None:
        """Test when op command is not found."""
        mock_run.side_effect = FileNotFoundError()
        assert check_op_cli_available() is False

    @patch("subprocess.run")
    def test_op_cli_timeout(self, mock_run: MagicMock) -> None:
        """Test when op command times out."""
        mock_run.side_effect = subprocess.TimeoutExpired("op", 5)
        assert check_op_cli_available() is False


class TestGetOpItem:
    """Tests for get_op_item function."""

    @patch("nac_collector.onepassword_helper.check_op_cli_available")
    def test_op_cli_not_available(self, mock_check: MagicMock) -> None:
        """Test when op CLI is not available."""
        mock_check.return_value = False
        with pytest.raises(OnePasswordError, match="not available"):
            get_op_item("test-item")

    @patch("subprocess.run")
    @patch("nac_collector.onepassword_helper.check_op_cli_available")
    def test_successful_retrieval(
        self, mock_check: MagicMock, mock_run: MagicMock
    ) -> None:
        """Test successful item retrieval."""
        mock_check.return_value = True
        item_data = {"id": "test123", "title": "Test Item"}
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(item_data), stderr=""
        )

        result = get_op_item("test-item")
        assert result == item_data
        mock_run.assert_called_once_with(
            ["op", "item", "get", "test-item", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )

    @patch("subprocess.run")
    @patch("nac_collector.onepassword_helper.check_op_cli_available")
    def test_item_not_found(self, mock_check: MagicMock, mock_run: MagicMock) -> None:
        """Test when item is not found."""
        mock_check.return_value = True
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "op", stderr="[ERROR] item not found"
        )

        with pytest.raises(OnePasswordError, match="Failed to retrieve"):
            get_op_item("nonexistent-item")

    @patch("subprocess.run")
    @patch("nac_collector.onepassword_helper.check_op_cli_available")
    def test_timeout(self, mock_check: MagicMock, mock_run: MagicMock) -> None:
        """Test timeout during retrieval."""
        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired("op", 30)

        with pytest.raises(OnePasswordError, match="Timeout"):
            get_op_item("test-item")

    @patch("subprocess.run")
    @patch("nac_collector.onepassword_helper.check_op_cli_available")
    def test_invalid_json(self, mock_check: MagicMock, mock_run: MagicMock) -> None:
        """Test invalid JSON response."""
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="not valid json")

        with pytest.raises(OnePasswordError, match="Failed to parse"):
            get_op_item("test-item")


class TestExtractCredentials:
    """Tests for extract_credentials function."""

    def test_extract_all_fields(self) -> None:
        """Test extracting all credential fields."""
        item_data = {
            "fields": [
                {"id": "username", "label": "username", "value": "admin"},
                {"id": "password", "label": "password", "value": "secret123"},
                {"id": "url", "label": "url", "value": "https://example.com"},
            ]
        }
        username, password, url = extract_credentials(item_data)
        assert username == "admin"
        assert password == "secret123"
        assert url == "https://example.com"

    def test_extract_from_labels(self) -> None:
        """Test extracting from field labels."""
        item_data = {
            "fields": [
                {"id": "field1", "label": "Username", "value": "testuser"},
                {"id": "field2", "label": "Password", "value": "testpass"},
                {"id": "field3", "label": "Website Address", "value": "https://test.com"},
            ]
        }
        username, password, url = extract_credentials(item_data)
        assert username == "testuser"
        assert password == "testpass"
        assert url == "https://test.com"

    def test_extract_url_from_urls_array(self) -> None:
        """Test extracting URL from urls array."""
        item_data = {
            "fields": [
                {"id": "username", "value": "admin"},
                {"id": "password", "value": "secret"},
            ],
            "urls": [{"href": "https://fallback.com"}],
        }
        username, password, url = extract_credentials(item_data)
        assert username == "admin"
        assert password == "secret"
        assert url == "https://fallback.com"

    def test_missing_fields(self) -> None:
        """Test with missing fields."""
        item_data = {"fields": [{"id": "username", "value": "admin"}]}
        username, password, url = extract_credentials(item_data)
        assert username == "admin"
        assert password is None
        assert url is None

    def test_empty_item(self) -> None:
        """Test with empty item data."""
        item_data: dict[str, list[dict[str, str]]] = {"fields": []}
        username, password, url = extract_credentials(item_data)
        assert username is None
        assert password is None
        assert url is None

    def test_case_insensitive_matching(self) -> None:
        """Test case-insensitive field matching."""
        item_data = {
            "fields": [
                {"id": "USERNAME", "label": "USERNAME", "value": "admin"},
                {"id": "PASSWORD", "label": "PASSWORD", "value": "secret"},
            ]
        }
        username, password, url = extract_credentials(item_data)
        assert username == "admin"
        assert password == "secret"


class TestGetCredentialsFromOp:
    """Tests for get_credentials_from_op function."""

    @patch("nac_collector.onepassword_helper.get_op_item")
    def test_successful_credential_retrieval(self, mock_get_item: MagicMock) -> None:
        """Test successful credential retrieval."""
        mock_get_item.return_value = {
            "fields": [
                {"id": "username", "value": "admin"},
                {"id": "password", "value": "secret123"},
                {"id": "url", "value": "https://vmanage.example.com"},
            ]
        }

        username, password, url = get_credentials_from_op("my-item")
        assert username == "admin"
        assert password == "secret123"
        assert url == "https://vmanage.example.com"

    @patch("nac_collector.onepassword_helper.get_op_item")
    def test_op_error_propagation(self, mock_get_item: MagicMock) -> None:
        """Test that OnePasswordError is propagated."""
        mock_get_item.side_effect = OnePasswordError("Test error")

        with pytest.raises(OnePasswordError, match="Test error"):
            get_credentials_from_op("my-item")
