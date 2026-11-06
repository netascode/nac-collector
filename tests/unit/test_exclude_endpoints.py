"""Tests for EndpointResolver.exclude_endpoints and the --exclude-endpoint option."""

import logging

from nac_collector.endpoint_resolver import EndpointResolver

ENDPOINTS = [
    {"name": "endpoint", "endpoint": "/ers/config/endpoint"},
    {
        "name": "network_device",
        "endpoint": "/ers/config/networkdevice",
        "children": [{"name": "child", "endpoint": "child"}],
    },
    {"name": "internal_user", "endpoint": "/ers/config/internaluser"},
]


def names(data):
    return [e["name"] for e in data]


def test_exclude_top_level_entry():
    result = EndpointResolver.exclude_endpoints(ENDPOINTS, ["endpoint"])
    assert names(result) == ["network_device", "internal_user"]


def test_exclude_entry_with_children_removes_children():
    result = EndpointResolver.exclude_endpoints(ENDPOINTS, ["network_device"])
    assert names(result) == ["endpoint", "internal_user"]
    assert all("children" not in e for e in result)


def test_exclude_multiple():
    result = EndpointResolver.exclude_endpoints(
        ENDPOINTS, ["endpoint", "internal_user"]
    )
    assert names(result) == ["network_device"]


def test_unknown_name_warns_and_keeps_everything(caplog):
    with caplog.at_level(logging.WARNING):
        result = EndpointResolver.exclude_endpoints(ENDPOINTS, ["does_not_exist"])
    assert names(result) == names(ENDPOINTS)
    assert "does_not_exist" in caplog.text


def test_empty_names_returns_input_unchanged():
    assert EndpointResolver.exclude_endpoints(ENDPOINTS, []) is ENDPOINTS


def test_input_not_mutated():
    EndpointResolver.exclude_endpoints(ENDPOINTS, ["endpoint"])
    assert len(ENDPOINTS) == 3


def test_packaged_ise_endpoint_can_be_excluded():
    data = EndpointResolver.resolve_endpoint_data("ise")
    assert data is not None
    assert "endpoint" in names(data)
    result = EndpointResolver.exclude_endpoints(data, ["endpoint"])
    assert "endpoint" not in names(result)
    assert "endpoint_identity_group" in names(result)
