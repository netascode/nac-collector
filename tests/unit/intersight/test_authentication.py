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
def rsa_key_file(tmp_path, rsa_pem):
    key_file = tmp_path / "test_key.pem"
    key_file.write_text(rsa_pem)
    return key_file


def test_authenticate_success_from_file(rsa_key_file) -> None:
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


def test_authenticate_success_from_pem_string(rsa_pem) -> None:
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
