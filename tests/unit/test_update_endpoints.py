"""Unit tests for the update_endpoints script."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


def test_update_endpoints_import():
    """Test that the update_endpoints module can be imported."""
    import update_endpoints

    assert hasattr(update_endpoints, "update_endpoint_file")
    assert hasattr(update_endpoints, "main")
    assert hasattr(update_endpoints, "SUPPORTED_SOLUTIONS")


@patch("update_endpoints.GithubRepoWrapper")
def test_update_endpoint_file_success(mock_wrapper):
    """Test successful update of an endpoint file."""
    import update_endpoints

    # Mock the wrapper to return sample data
    mock_instance = MagicMock()
    mock_instance.get_definitions.return_value = [
        {"name": "test_endpoint", "endpoint": "/api/v1/test"}
    ]
    mock_wrapper.return_value = mock_instance

    # Mock file operations
    mock_open = MagicMock()
    mock_file = MagicMock()
    mock_open.return_value.__enter__.return_value = mock_file

    # Mock Path operations
    with patch("update_endpoints.Path") as mock_path:
        mock_output_dir = MagicMock()
        mock_path.return_value.parent.parent = MagicMock()
        mock_path.return_value.parent.parent.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = mock_output_dir
        mock_output_dir.__truediv__.return_value = MagicMock()
        mock_output_dir.mkdir = MagicMock()

        # Run the function
        with patch("builtins.open", mock_open):
            result = update_endpoints.update_endpoint_file("test_solution")

    assert result is True
    mock_instance.get_definitions.assert_called_once()


@patch("update_endpoints.GithubRepoWrapper")
def test_update_endpoint_file_failure(mock_wrapper):
    """Test handling of failure in updating endpoint file."""
    import update_endpoints

    # Mock the wrapper to raise an exception
    mock_wrapper.side_effect = Exception("Test error")

    # Run the function
    result = update_endpoints.update_endpoint_file("test_solution")

    assert result is False


def test_main_exit_codes():
    """Test that main returns correct exit codes."""
    import update_endpoints

    # Test all successful updates
    with patch.object(update_endpoints, "update_endpoint_file", return_value=True):
        result = update_endpoints.main()
        assert result == 0

    # Test with some failures
    with patch.object(
        update_endpoints, "update_endpoint_file", side_effect=[True, False, True, False]
    ):
        result = update_endpoints.main()
        assert result == 1
