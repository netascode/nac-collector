import pytest

from nac_collector.controller.ise import CiscoClientISE

pytestmark = pytest.mark.unit


def test_initialization() -> None:
    client: CiscoClientISE = CiscoClientISE(
        username="test_user",
        password="test_password",
        base_url="https://example.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )
    assert client.username == "test_user"
    assert client.password == "test_password"
    assert client.base_url == "https://example.com"
    assert client.max_retries == 3
    assert client.retry_after == 1
    assert client.timeout == 5
    assert client.ssl_verify is False
