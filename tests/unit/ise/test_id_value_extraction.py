import pytest

from nac_collector.controller.ise import CiscoClientISE

pytestmark = pytest.mark.unit


def test_get_id_value_from_dict_with_id() -> None:
    data: dict[str, str] = {"id": "12345", "name": "Test Item"}
    id_value: str | None = CiscoClientISE.get_id_value(data)
    assert id_value == "12345"


def test_get_id_value_from_dict_with_rule_id() -> None:
    data: dict[str, dict[str, str] | str] = {
        "rule": {"id": "54321"},
        "name": "Test Rule",
    }
    id_value: str | None = CiscoClientISE.get_id_value(data)
    assert id_value == "54321"


def test_get_id_value_from_dict_with_name() -> None:
    data: dict[str, str] = {"name": "Item Name"}
    id_value: str | None = CiscoClientISE.get_id_value(data)
    assert id_value == "Item Name"


def test_get_id_value_none() -> None:
    data: dict[str, str] = {}
    id_value: str | None = CiscoClientISE.get_id_value(data)
    assert id_value is None
