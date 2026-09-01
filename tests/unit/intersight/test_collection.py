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
def authenticated_client():
    client = CiscoClientINTERSIGHT(
        api_key_id="test-key-id",
        secret_key=_make_rsa_pem(),
        base_url="https://intersight.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )
    client.authenticate()
    return client


def _mock_response(status_code: int, json_body: dict) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_body
    response.headers = {}
    return response


def test_fetch_all_pages_single_page(mocker, authenticated_client) -> None:
    items = [{"Moid": f"moid-{i}", "Name": f"item-{i}"} for i in range(3)]
    mock_resp = _mock_response(200, {"Results": items, "Count": 3})
    mocker.patch.object(authenticated_client, "_get_full_url", return_value=mock_resp)

    result = authenticated_client._fetch_all_pages("/api/v1/organization/Organizations")

    assert result == items
    authenticated_client._get_full_url.assert_called_once()


def test_fetch_all_pages_paginates(mocker, authenticated_client) -> None:
    # First page returns exactly _PAGE_SIZE (500) items; second returns fewer → stops
    from nac_collector.controller.intersight import _PAGE_SIZE

    page1 = [{"Moid": f"m{i}"} for i in range(_PAGE_SIZE)]
    page2 = [{"Moid": f"m{_PAGE_SIZE + i}"} for i in range(5)]

    mocker.patch.object(
        authenticated_client,
        "_get_full_url",
        side_effect=[
            _mock_response(200, {"Results": page1, "Count": _PAGE_SIZE}),
            _mock_response(200, {"Results": page2, "Count": 5}),
        ],
    )

    result = authenticated_client._fetch_all_pages("/api/v1/bios/Policies")

    assert len(result) == _PAGE_SIZE + 5
    assert authenticated_client._get_full_url.call_count == 2


def test_fetch_all_pages_none_response(mocker, authenticated_client) -> None:
    mocker.patch.object(authenticated_client, "_get_full_url", return_value=None)

    result = authenticated_client._fetch_all_pages("/api/v1/bios/Policies")

    assert result == []


def test_fetch_all_pages_empty_results(mocker, authenticated_client) -> None:
    mock_resp = _mock_response(200, {"Results": [], "Count": 0})
    mocker.patch.object(authenticated_client, "_get_full_url", return_value=mock_resp)

    result = authenticated_client._fetch_all_pages("/api/v1/bios/Policies")

    assert result == []


def test_fetch_all_pages_null_results_key(mocker, authenticated_client) -> None:
    # Intersight may return {"Results": null} for empty collections
    mock_resp = _mock_response(200, {"Results": None, "Count": 0})
    mocker.patch.object(authenticated_client, "_get_full_url", return_value=mock_resp)

    result = authenticated_client._fetch_all_pages("/api/v1/bios/Policies")

    assert result == []


def test_fetch_all_pages_appends_pagination_params(mocker, authenticated_client) -> None:
    from nac_collector.controller.intersight import _PAGE_SIZE

    mock_resp = _mock_response(200, {"Results": [], "Count": 0})
    mock_get = mocker.patch.object(
        authenticated_client, "_get_full_url", return_value=mock_resp
    )

    authenticated_client._fetch_all_pages("/api/v1/bios/Policies")

    called_url = mock_get.call_args[0][0]
    assert f"$top={_PAGE_SIZE}" in called_url
    assert "$skip=0" in called_url


def test_fetch_all_pages_filter_preserved(mocker, authenticated_client) -> None:
    mock_resp = _mock_response(200, {"Results": [], "Count": 0})
    mock_get = mocker.patch.object(
        authenticated_client, "_get_full_url", return_value=mock_resp
    )

    authenticated_client._fetch_all_pages(
        "/api/v1/fcpool/Pools?$filter=PoolPurpose eq 'WWNN'"
    )

    called_url = mock_get.call_args[0][0]
    assert "$filter=PoolPurpose eq 'WWNN'" in called_url
    assert "$top=" in called_url


def test_get_from_endpoints_data(mocker, authenticated_client) -> None:
    endpoints = [
        {"name": "organization", "endpoint": "/api/v1/organization/Organizations"},
        {"name": "bios_policy", "endpoint": "/api/v1/bios/Policies"},
    ]
    orgs = [{"Moid": "org-1", "Name": "default"}]
    bios = [{"Moid": "bios-1", "Name": "my-bios"}]

    mocker.patch.object(
        authenticated_client,
        "_fetch_all_pages",
        side_effect=[orgs, bios],
    )

    result = authenticated_client.get_from_endpoints_data(endpoints)

    assert result == {"organization": orgs, "bios_policy": bios}
    assert authenticated_client._fetch_all_pages.call_count == 2


def test_get_from_endpoints_data_with_filter(mocker, authenticated_client) -> None:
    endpoints = [
        {
            "name": "wwnn_pool",
            "endpoint": "/api/v1/fcpool/Pools",
            "filter": "PoolPurpose eq 'WWNN'",
        }
    ]
    pools = [{"Moid": "pool-1", "Name": "wwnn-pool"}]

    mock_fetch = mocker.patch.object(
        authenticated_client, "_fetch_all_pages", return_value=pools
    )

    result = authenticated_client.get_from_endpoints_data(endpoints)

    assert result == {"wwnn_pool": pools}
    called_path = mock_fetch.call_args[0][0]
    assert "$filter=PoolPurpose eq 'WWNN'" in called_path
