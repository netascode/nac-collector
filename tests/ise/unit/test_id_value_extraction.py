import pytest

from nac_collector.cisco_client_ise import CiscoClientISE

pytestmark = pytest.mark.unit


def test_get_id_value_from_dict_with_id():
    data = {"id": "12345", "name": "Test Item"}
    id_value = CiscoClientISE.get_id_value(data)
    assert id_value == "12345"


def test_get_id_value_from_dict_with_rule_id():
    data = {"rule": {"id": "54321"}, "name": "Test Rule"}
    id_value = CiscoClientISE.get_id_value(data)
    assert id_value == "54321"


def test_get_id_value_from_dict_with_name():
    data = {"name": "Item Name"}
    id_value = CiscoClientISE.get_id_value(data)
    assert id_value == "Item Name"


def test_get_id_value_none():
    data = {}
    id_value = CiscoClientISE.get_id_value(data)
    assert id_value is None
