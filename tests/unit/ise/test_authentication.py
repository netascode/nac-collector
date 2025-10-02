from unittest.mock import Mock

import pytest

from nac_collector.controller.ise import CiscoClientISE

pytestmark = pytest.mark.unit


@pytest.fixture
def cisco_client():
    return CiscoClientISE(
        username="test_user",
        password="test_password",
        base_url="https://example.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )


def test_authenticate_success(mocker, cisco_client):
    mock_response = Mock()
    mock_response.status_code = 200
    mocker.patch("httpx.get", return_value=mock_response)

    result = cisco_client.authenticate()
    assert result is True
    assert cisco_client.client is not None


def test_authenticate_failure(mocker, cisco_client):
    mock_response = Mock()
    mock_response.status_code = 401
    mocker.patch("httpx.get", return_value=mock_response)

    result = cisco_client.authenticate()
    assert result is False
    assert cisco_client.client is None
