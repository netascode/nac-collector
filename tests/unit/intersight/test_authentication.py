from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from nac_collector.controller.intersight import CiscoClientINTERSIGHT

pytestmark = pytest.mark.unit


def _make_rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def rsa_pem() -> str:
    return _make_rsa_pem()


@pytest.fixture
def mock_get(mocker):
    """Mock the signed request that authenticate() sends to check the key."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    return mocker.patch.object(httpx.Client, "get", return_value=response)


def _client(secret_key: str) -> CiscoClientINTERSIGHT:
    return CiscoClientINTERSIGHT(
        api_key_id="test-key-id",
        secret_key=secret_key,
        base_url="https://intersight.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )


@pytest.fixture
def rsa_key_file(tmp_path, rsa_pem):
    key_file = tmp_path / "test_key.pem"
    key_file.write_text(rsa_pem)
    return key_file


def test_authenticate_success_from_file(rsa_key_file, mock_get) -> None:
    client = CiscoClientINTERSIGHT(
        api_key_id="test-key-id",
        secret_key=str(rsa_key_file),
        base_url="https://intersight.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )
    result = client.authenticate()
    assert result is True
    assert client.client is not None
    mock_get.assert_called_once_with(
        "https://intersight.com/api/v1/organization/Organizations?$top=1"
    )


def test_authenticate_success_from_pem_string(rsa_pem, mock_get) -> None:
    client = CiscoClientINTERSIGHT(
        api_key_id="test-key-id",
        secret_key=rsa_pem,
        base_url="https://intersight.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )
    result = client.authenticate()
    assert result is True
    assert client.client is not None
    mock_get.assert_called_once_with(
        "https://intersight.com/api/v1/organization/Organizations?$top=1"
    )


def test_authenticate_bad_key_returns_false() -> None:
    client = CiscoClientINTERSIGHT(
        api_key_id="test-key-id",
        secret_key="this-is-not-a-valid-pem-key",
        base_url="https://intersight.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )
    result = client.authenticate()
    assert result is False
    assert client.client is None


def test_authenticate_missing_key_file_returns_false(tmp_path, caplog) -> None:
    client = _client(str(tmp_path / "missing.pem"))
    assert client.authenticate() is False
    assert client.client is None
    assert "Secret key file not found" in caplog.text


def test_authenticate_rejected_key_returns_false(rsa_pem, mock_get) -> None:
    mock_get.return_value.status_code = 401
    client = _client(rsa_pem)
    assert client.authenticate() is False


def test_authenticate_unreachable_returns_false(rsa_pem, mock_get) -> None:
    mock_get.side_effect = httpx.ConnectError("connection refused")
    client = _client(rsa_pem)
    assert client.authenticate() is False
