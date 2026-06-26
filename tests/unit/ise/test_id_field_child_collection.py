import pytest

from nac_collector.controller.ise import CiscoClientISE

pytestmark = pytest.mark.unit

_DICTIONARY_ENDPOINT = {
    "name": "network_access_dictionary",
    "endpoint": "/api/v1/policy/network-access/dictionaries",
    "id_field": "name",
    "children": [
        {
            "name": "network_access_dictionary_attribute",
            "endpoint": "/attribute",
        }
    ],
}


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


def test_child_url_uses_name_not_uuid(mocker, cisco_client):
    """Child URL must be built from the name field, not the UUID, when id_field='name'."""
    parent_url = "/api/v1/policy/network-access/dictionaries"
    child_url = "/api/v1/policy/network-access/dictionaries/DictA/attribute"

    def mock_fetch(url):
        if url == parent_url:
            return {"response": [{"id": "uuid-abc-123", "name": "DictA"}]}
        if url == child_url:
            return {"response": [{"id": "attr-1", "name": "Attr1"}]}
        raise ValueError(f"Unexpected URL: {url}")

    mocker.patch.object(cisco_client, "fetch_data", side_effect=mock_fetch)

    cisco_client.get_from_endpoints_data([_DICTIONARY_ENDPOINT])

    cisco_client.fetch_data.assert_any_call(child_url)


def test_child_url_percent_encodes_name_with_spaces(mocker, cisco_client):
    """A name-keyed id containing spaces/special chars must be percent-encoded in the child URL."""
    parent_url = "/api/v1/policy/network-access/dictionaries"
    # "Network Condition" -> the space must be encoded as %20, not sent raw.
    child_url = (
        "/api/v1/policy/network-access/dictionaries/Network%20Condition/attribute"
    )

    def mock_fetch(url):
        if url == parent_url:
            return {"response": [{"id": "uuid-abc-123", "name": "Network Condition"}]}
        if url == child_url:
            return {"response": [{"id": "attr-1", "name": "Attr1"}]}
        raise ValueError(f"Unexpected URL: {url}")

    mocker.patch.object(cisco_client, "fetch_data", side_effect=mock_fetch)

    cisco_client.get_from_endpoints_data([_DICTIONARY_ENDPOINT])

    cisco_client.fetch_data.assert_any_call(child_url)


def test_child_data_attached_to_correct_parent(mocker, cisco_client):
    """Child attributes must be attached to their matching parent dictionary."""

    def mock_fetch(url):
        if url == "/api/v1/policy/network-access/dictionaries":
            return {
                "response": [
                    {"id": "uuid-1", "name": "DictA"},
                    {"id": "uuid-2", "name": "DictB"},
                ]
            }
        if url == "/api/v1/policy/network-access/dictionaries/DictA/attribute":
            return {"response": [{"id": "attr-1", "name": "Attr1"}]}
        if url == "/api/v1/policy/network-access/dictionaries/DictB/attribute":
            return {"response": [{"id": "attr-2", "name": "Attr2"}]}
        raise ValueError(f"Unexpected URL: {url}")

    mocker.patch.object(cisco_client, "fetch_data", side_effect=mock_fetch)

    result = cisco_client.get_from_endpoints_data([_DICTIONARY_ENDPOINT])

    items = result["network_access_dictionary"]
    dict_a = next(i for i in items if i["data"]["name"] == "DictA")
    dict_b = next(i for i in items if i["data"]["name"] == "DictB")

    assert dict_a["children"]["network_access_dictionary_attribute"] == [
        {"data": {"id": "attr-1", "name": "Attr1"}, "endpoint": "/attribute/attr-1"}
    ]
    assert dict_b["children"]["network_access_dictionary_attribute"] == [
        {"data": {"id": "attr-2", "name": "Attr2"}, "endpoint": "/attribute/attr-2"}
    ]


def test_resolve_id_uses_id_field_when_set():
    """_resolve_id returns the named field value when id_field is specified."""
    data = {"id": "uuid-xyz", "name": "DictA"}
    assert CiscoClientISE._resolve_id(data, "name") == "DictA"


def test_resolve_id_falls_back_to_get_id_value_when_no_id_field():
    """_resolve_id falls back to get_id_value (UUID first) when id_field is None."""
    data = {"id": "uuid-xyz", "name": "DictA"}
    assert CiscoClientISE._resolve_id(data, None) == "uuid-xyz"


def test_resolve_id_returns_none_when_field_absent():
    """_resolve_id returns None when id_field is set but the field is missing from data."""
    data = {"id": "uuid-xyz"}
    assert CiscoClientISE._resolve_id(data, "name") is None
