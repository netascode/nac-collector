"""Tests that generated endpoint definitions are in a canonical order.

`GithubRepoWrapper.add_endpoint_to_list` uses `bisect.insort`, which only
inserts at the correct position if the list is already sorted by name.
`parent_children` establishes that invariant for generated endpoints, and the
overrides machinery preserves it. If a regenerated endpoints YAML is not sorted,
`bisect.insort` silently places manually added endpoints at arbitrary positions,
and unrelated edits (e.g. to `remove_endpoints`) shuffle the whole file.

Only solutions generated from Terraform provider definitions are checked.
Hand-maintained endpoint files (fmc, ndfc, ndo) never pass through
`add_endpoint_to_list`, so the invariant does not apply to them.
"""

import sys
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).parent.parent.parent

# Add scripts directory to path
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from update_endpoints import SUPPORTED_SOLUTIONS  # noqa: E402

ENDPOINTS_DIR = REPO_ROOT / "nac_collector" / "resources" / "endpoints"


def collect_unsorted_levels(
    endpoints: list[dict[str, Any]], path: str = "<root>"
) -> list[str]:
    """Return a description of every level that is not sorted by name."""
    problems = []
    names = [e["name"] for e in endpoints]
    if names != sorted(names):
        inversions = [
            f"{a} > {b}" for a, b in zip(names, names[1:], strict=False) if a > b
        ]
        problems.append(f"{path}: {', '.join(inversions)}")
    for endpoint in endpoints:
        children = endpoint.get("children")
        if children:
            problems.extend(
                collect_unsorted_levels(children, f"{path} -> {endpoint['name']}")
            )
    return problems


@pytest.mark.parametrize("solution", sorted(SUPPORTED_SOLUTIONS))
def test_endpoints_sorted_by_name(solution: str) -> None:
    """Every endpoint list, at every nesting level, is sorted by name."""
    path = ENDPOINTS_DIR / f"{solution}.yaml"
    yaml = YAML(typ="safe", pure=True)
    endpoints = yaml.load(path.read_text(encoding="utf-8"))

    problems = collect_unsorted_levels(endpoints)
    assert not problems, (
        f"{path.name} is not sorted by name; "
        "bisect.insort in add_endpoint_to_list requires sorted lists. "
        "Regenerate with 'uv run ./scripts/update_endpoints.py'. "
        f"Unsorted levels: {problems}"
    )
