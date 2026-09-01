import pytest

from nac_collector.controller.intersight import CiscoClientINTERSIGHT

pytestmark = pytest.mark.unit


def test_initialization() -> None:
    client = CiscoClientINTERSIGHT(
        api_key_id="test-key-id",
        secret_key="dummy",
        base_url="https://intersight.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )
    assert client.api_key_id == "test-key-id"
    assert client.secret_key == "dummy"
    assert client.base_url == "https://intersight.com"
    assert client.max_retries == 3
    assert client.retry_after == 1
    assert client.timeout == 5
    assert client.ssl_verify is False
    assert client.client is None


def test_default_base_url() -> None:
    client = CiscoClientINTERSIGHT(
        api_key_id="key",
        secret_key="dummy",
        base_url="",
        max_retries=3,
        retry_after=1,
        timeout=5,
    )
    assert client.base_url == CiscoClientINTERSIGHT.DEFAULT_BASE_URL


def test_solution_constant() -> None:
    assert CiscoClientINTERSIGHT.SOLUTION == "intersight"
