import pytest
from nac_collector.client import make_client
from nac_collector.client.ise import CiscoClientISE
from nac_collector.client.ndo import CiscoClientNDO
from nac_collector.client.sdwan import CiscoClientSDWAN

def test_make_client_sdwan_returns_correct_client():
    solution = "SDWAN"
    username = "admin"
    password = "123456"
    url = "https://example.com"
    client = make_client(solution, username, password, url)
    assert isinstance(client, CiscoClientSDWAN)

def test_make_client_ise_returns_correct_client():
    solution = "ISE"
    username = "admin"
    password = "123456"
    url = "https://example.com"
    client = make_client(solution, username, password, url)
    assert isinstance(client, CiscoClientISE)

def test_make_client_ndo_return_correct_client():
    solution = "NDO"
    username = "admin"
    password = "123456"
    url = "https://example.com"
    client = make_client(solution, username, password, url)
    assert isinstance(client, CiscoClientNDO)

def test_make_client_unknown_solution_raises():
    solution = "UnknownSolution"
    username = "admin"
    password = "123456"
    url = "https://example.com"
    with pytest.raises(LookupError):
        make_client(solution, username, password, url)