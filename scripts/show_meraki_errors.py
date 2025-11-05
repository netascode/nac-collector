#!/usr/bin/env python3

"""
Categorize API errors from a Meraki nac-collector output,
to guide developers adding exclusions to omit expected errors from the output.

nac_collector/resources/endpoints/meraki_overrides.yaml
can be used to add exclusions
to e.g. make Meraki nac-collector not request some device-based endpoints
for given device types.

Usage:
uv run nac-collector <...>
unzip -o nac-collector.zip # To obtain meraki.json
uv run ./scripts/show_meraki_errors.py meraki.json

Example output (trimmed down to 2 example endpoints):
{
    "sm_target_group": [
        {
            "error": {
                "status_code": 400,
                "message": {
                    "errors": [
                        "This combined network does not contain a Systems Manager network"
                    ]
                }
            },
            "count": 4
        }
    ],
    "device_cellular_sims": [
        {
            "error": null,
            "count": 1,
            "conditions": [
                {
                    "conditions": {
                        "product_type": "cellularGateway",
                        "abbreviated_model": "MG"
                    },
                    "count": 1
                }
            ]
        },
        {
            "error": {
                "status_code": 400,
                "message": {
                    "errors": [
                        "This device does not support SIM configurations."
                    ]
                }
            },
            "count": 6,
            "conditions": [
                {
                    "conditions": {
                        "product_type": "appliance",
                        "abbreviated_model": "MX"
                    },
                    "count": 1
                },
                {
                    "conditions": {
                        "product_type": "wireless",
                        "abbreviated_model": "MR"
                    },
                    "count": 1
                },
                {
                    "conditions": {
                        "product_type": "switch",
                        "abbreviated_model": "MS"
                    },
                    "count": 1
                },
                {
                    "conditions": {
                        "product_type": "switch",
                        "abbreviated_model": "C"
                    },
                    "count": 3
                }
            ]
        }
    ]
}
"""

import json
import re
import sys
from collections.abc import Callable
from typing import Any


def print_error_summary(collected_json: dict[str, Any]) -> None:
    errors = find_errors_in_resources(collected_json)

    aggregated_errors = count_errors(errors, lambda error: error["tf_resource_type"])

    print(json.dumps(aggregated_errors, indent=4))


def find_errors_in_resources(
    collected_json: dict[str, Any], parent_device_info: dict[str, Any] | None = None
) -> list[Any]:
    errors = []

    for tf_resource_type, collected_resources in collected_json.items():
        if isinstance(collected_resources, list):
            for collected_resource in collected_resources:
                errors += find_errors_in_resource(
                    tf_resource_type, collected_resource, parent_device_info
                )
            continue

        collected_resource: dict[str, Any] = collected_resources
        errors += find_errors_in_resource(
            tf_resource_type, collected_resource, parent_device_info
        )

    return errors


def find_errors_in_resource(
    tf_resource_type: str,
    collected_resource: dict[str, Any],
    parent_device_info: dict[str, Any] | None,
) -> list[Any]:
    errors = []

    err = collected_resource.get("error")

    error = {
        "tf_resource_type": tf_resource_type,
        # error can be None for counting non-error cases.
        "error": err,
    }
    if parent_device_info is not None:
        error["conditions"] = parent_device_info
    errors.append(error)

    device_info = None
    if tf_resource_type == "device":
        model = collected_resource.get("data", {}).get("model")
        abbreviated_model_match = re.match(r"[^0-9]+", model)
        abbreviated_model = (
            abbreviated_model_match.group()
            if abbreviated_model_match is not None
            else None
        )
        device_info = {
            "product_type": collected_resource.get("data", {}).get("productType"),
            "abbreviated_model": abbreviated_model,
        }

    errors += find_errors_in_resources(
        collected_resource.get("children", {}), device_info
    )

    return errors


def count_errors(
    errors: list[dict[str, Any]], key_fun: Callable[[dict[str, Any]], str]
) -> dict[str, list[dict[str, Any]]]:
    all_counters = {}

    for error in errors:
        counters = all_counters.setdefault(key_fun(error), [])
        count_error(error, counters)

    counters_with_errors = {}
    for key, counters in all_counters.items():
        if len(counters) == 1 and counters[0]["error"] is None:
            continue
        counters_with_errors[key] = counters

    counters_with_errors = sort_counters(counters_with_errors)

    return counters_with_errors


def count_error(error: dict[str, Any], counters: list[dict[str, Any]]) -> None:
    for counter in counters:
        if counter["error"] == error["error"]:
            counter["count"] += 1
            conditions = error.get("conditions")
            if conditions is not None:
                condition_counters = counter.setdefault("conditions", [])
                count_condition(conditions, condition_counters)
            return

    counter = {
        "error": error["error"],
        "count": 1,
    }
    conditions = error.get("conditions")
    if conditions is not None:
        counter["conditions"] = [
            {
                "conditions": conditions,
                "count": 1,
            }
        ]
    counters.append(counter)


def count_condition(
    conditions: dict[str, Any], condition_counters: list[dict[str, Any]]
) -> None:
    for counter in condition_counters:
        if counter["conditions"] == conditions:
            counter["count"] += 1
            return

    counter = {
        "conditions": conditions,
        "count": 1,
    }
    condition_counters.append(counter)


def sort_counters(
    all_counters: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    counters_sorted_inside = {}
    for key, counters in all_counters.items():
        # Sort conditions in each counter by count.
        for counter in counters:
            conditions = counter.get("conditions")
            if conditions is not None:
                counter["conditions"] = sorted(
                    conditions, key=lambda condition: condition["count"]
                )
        # Sort counters by count
        counters = sorted(counters, key=lambda counter: counter["count"])
        counters_sorted_inside[key] = counters

    def largest_non_none_error_count(
        key_and_counters: tuple[str, list[dict[str, Any]]],
    ) -> int:
        _, counters = key_and_counters
        non_null_error_counters = [
            counter for counter in counters if counter["error"] is not None
        ]
        return non_null_error_counters[-1]["count"]

    return dict(
        sorted(counters_sorted_inside.items(), key=largest_non_none_error_count)
    )


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        collected_json = json.load(f)

    print_error_summary(collected_json)
