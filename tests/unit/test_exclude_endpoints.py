"""Tests for EndpointResolver.exclude_endpoints and load_exclude_file."""

from pathlib import Path

import pytest
import yaml

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


def test_exclude_child_entry_keeps_parent():
    result = EndpointResolver.exclude_endpoints(ENDPOINTS, ["child"])
    assert names(result) == names(ENDPOINTS)
    assert result[1]["children"] == []


def test_exclude_deeply_nested_child():
    data = [
        {
            "name": "a",
            "endpoint": "/a",
            "children": [
                {
                    "name": "b",
                    "endpoint": "b",
                    "children": [{"name": "c", "endpoint": "c"}],
                }
            ],
        }
    ]
    result = EndpointResolver.exclude_endpoints(data, ["c"])
    assert result[0]["children"][0]["children"] == []


def test_unknown_name_raises():
    with pytest.raises(ValueError, match="does_not_exist"):
        EndpointResolver.exclude_endpoints(ENDPOINTS, ["endpoint", "does_not_exist"])


def test_load_exclude_file(tmp_path):
    f = tmp_path / "exclude.yaml"
    f.write_text("# tacacs\n- tacacs_profile\n- tacacs_command_set\n")
    assert EndpointResolver.load_exclude_file(str(f)) == [
        "tacacs_profile",
        "tacacs_command_set",
    ]


def test_load_exclude_file_rejects_non_list(tmp_path):
    f = tmp_path / "exclude.yaml"
    f.write_text("tacacs_profile: true\n")
    with pytest.raises(ValueError, match="list"):
        EndpointResolver.load_exclude_file(str(f))


def test_load_exclude_file_missing(tmp_path):
    with pytest.raises(ValueError, match="Failed to load"):
        EndpointResolver.load_exclude_file(str(tmp_path / "nope.yaml"))


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


def chain(depth):
    """Build a linear chain l1 > l2 > ... > l<depth>."""
    node = {"name": f"l{depth}", "endpoint": f"l{depth}"}
    for level in range(depth - 1, 0, -1):
        node = {"name": f"l{level}", "endpoint": f"l{level}", "children": [node]}
    return [node]


def chain_names(data):
    out = []
    while data:
        out.append(data[0]["name"])
        data = data[0].get("children", [])
    return out


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_exclude_at_every_level_of_a_five_level_chain(level):
    """Packaged definitions nest up to 5 levels (meraki); test every level."""
    result = EndpointResolver.exclude_endpoints(chain(5), [f"l{level}"])
    # Excluding a node drops its whole subtree, keeps everything above it.
    assert chain_names(result) == [f"l{i}" for i in range(1, level)]


def test_duplicate_child_name_removed_everywhere():
    data = [
        {"name": "p1", "endpoint": "/p1", "children": [{"name": "x", "endpoint": "x"}]},
        {"name": "p2", "endpoint": "/p2", "children": [{"name": "x", "endpoint": "x"}]},
    ]
    result = EndpointResolver.exclude_endpoints(data, ["x"])
    assert [e["children"] for e in result] == [[], []]


def test_duplicate_names_in_list_are_accepted():
    result = EndpointResolver.exclude_endpoints(ENDPOINTS, ["endpoint", "endpoint"])
    assert names(result) == ["network_device", "internal_user"]


def test_load_exclude_file_rejects_non_string_items(tmp_path):
    f = tmp_path / "exclude.yaml"
    f.write_text("- tacacs_profile\n- 1\n")
    with pytest.raises(ValueError, match="list"):
        EndpointResolver.load_exclude_file(str(f))


def test_load_exclude_file_empty_returns_empty_list(tmp_path):
    f = tmp_path / "exclude.yaml"
    f.write_text("")
    assert EndpointResolver.load_exclude_file(str(f)) == []


def readme_tacacs_names():
    """Parse the documented exclude-tacacs.yaml block out of the README."""
    readme = Path(__file__).parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")
    block = text.split("# exclude-tacacs.yaml\n", 1)[1].split("```", 1)[0]
    return yaml.safe_load(block)


def test_readme_tacacs_example_is_valid_for_packaged_ise():
    """Every name the README publishes must exist, since unknown names abort."""
    listed = readme_tacacs_names()
    assert len(listed) == 9
    data = EndpointResolver.resolve_endpoint_data("ise")
    result = EndpointResolver.exclude_endpoints(data, listed)
    remaining = names(result)
    assert not [n for n in remaining if "tacacs" in n or n.startswith("device_admin")]
    assert "network_access_policy_set" in remaining
