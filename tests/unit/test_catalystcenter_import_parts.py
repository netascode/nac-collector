"""The collector records provider identity without knowing Terraform module keys."""

from copy import deepcopy
from pathlib import Path

from ruamel.yaml import YAML

from nac_collector.controller.catalystcenter import CiscoClientCATALYSTCENTER
from nac_collector.github_repo_wrapper import GithubRepoWrapper


def collect(data, recipe, parent=None, per_item=False):
    client = CiscoClientCATALYSTCENTER.__new__(CiscoClientCATALYSTCENTER)
    client.id_lookup = (
        {"/items": {"emit_per_item": True, "target_endpoint": "/items/%v"}}
        if per_item
        else {}
    )
    endpoint = {"name": "items", "endpoint": "/items", "import_id_attributes": recipe}
    return client.process_endpoint_data(
        endpoint, {"items": []}, {"response": data}, parent
    )["items"]


def test_list_objects_keep_payload_and_have_individually_addressed_id_parts():
    objects = [
        {"projectId": "p1", "id": "t1", "name": "A"},
        {"projectId": "p2", "id": "t2", "name": "B"},
    ]
    original = deepcopy(objects)
    recipe = [{"field": "projectId"}, {"field": "id"}]
    entries = collect(objects, recipe)
    assert objects == original
    assert len(entries) == 1
    assert entries[0]["data"] == original
    assert entries[0]["terraform_import_id_parts"] == {
        "attributes": recipe,
        "objects": {"/0": ["p1", "t1"], "/1": ["p2", "t2"]},
    }
    assert "terraform_import_ids" not in entries[0]


def test_per_item_shape_and_parent_components():
    recipe = [{"source": "parent"}, {"field": "id"}]
    entries = collect([{"id": "one"}, {"id": "two"}], recipe, "site-1", per_item=True)
    assert [entry["data"] for entry in entries] == [{"id": "one"}, {"id": "two"}]
    for entry, ident in zip(entries, ["one", "two"], strict=True):
        assert entry["terraform_import_id_parts"] == {
            "attributes": recipe,
            "objects": {"": ["site-1", ident]},
        }


def test_missing_and_grouped_id_parts_are_not_guessed():
    entries = collect(
        [{"id": "one"}, {"data": [{"id": "nested"}]}, {"id": ["a", "b"]}],
        [{"field": "id"}],
    )
    assert entries[0]["terraform_import_id_parts"]["objects"] == {"/0": ["one"]}


def test_id_parts_preserve_spaces_and_zero_and_recipe_order():
    result = CiscoClientCATALYSTCENTER.build_terraform_import_ids(
        {
            "import_id_attributes": [
                {"field": "name"},
                {"source": "parent"},
                {"field": "number"},
            ]
        },
        {"name": " Closed Authentication\n", "number": 0},
        " site-1 ",
    )
    assert result == ["Closed Authentication", "site-1", "0"]


def test_provider_recipe_excludes_module_key_derivation():
    wrapper = GithubRepoWrapper.__new__(GithubRepoWrapper)
    assert wrapper.catc_import_id_attributes(
        {
            "attributes": [
                {"reference": True, "response_model_name": "projectId"},
                {"match_id": True, "model_name": "name"},
            ]
        }
    ) == [{"field": "projectId"}, {"field": "id"}]
    assert wrapper.catc_import_id_attributes({"no_import": True}) is None
    assert not hasattr(wrapper, "catc_import_id_key")
    assert not hasattr(CiscoClientCATALYSTCENTER, "attach_keyed_import_ids")


def test_packaged_recipes_have_no_module_matching_instructions():
    root = Path(__file__).parents[2] / "nac_collector/resources"
    nodes = YAML(typ="safe").load(root / "endpoints/catalystcenter.yaml")

    def walk(items):
        for node in items:
            assert not any(
                key.startswith("import_id_") and key != "import_id_attributes"
                for key in node
            )
            yield node
            yield from walk(node.get("children", []))

    by_name = {node["name"]: node for node in walk(nodes)}
    assert by_name["template"]["import_id_attributes"] == [
        {"field": "projectId"},
        {"field": "id"},
    ]
    assert by_name["fabric_l3_handoff_ip_transit"]["import_id_attributes"] == [
        {"field": "networkDeviceId"},
        {"field": "fabricId"},
        {"field": "id"},
    ]
