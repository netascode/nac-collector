"""Endpoint resolver for orchestrating endpoint data resolution from multiple sources."""

import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from nac_collector.constants import GIT_TMP
from nac_collector.github_repo_wrapper import GithubRepoWrapper
from nac_collector.resource_manager import ResourceManager

logger = logging.getLogger(__name__)


class EndpointResolver:
    """Orchestrates endpoint data resolution from multiple sources."""

    @staticmethod
    def resolve_endpoint_data(
        solution: str, explicit_file: str | None = None, use_git_provider: bool = False
    ) -> list[dict[str, Any]] | None:
        """
        Resolve endpoint data using the fallback chain.

        Fallback order:
        1. Explicit --endpoints-file argument
        2. Fetch latest mode (fetch from upstream sources)
        3. Packaged resource

        Args:
            solution: The solution name
            explicit_file: Explicitly provided file path
            use_git_provider: Whether to fetch latest from upstream sources

        Returns:
            List of endpoint definitions, or None if no source available
        """
        # 1. Explicit file argument takes precedence
        if explicit_file:
            if Path(explicit_file).exists():
                logger.info("Using explicit endpoint file: %s", explicit_file)
                return EndpointResolver._load_from_file(explicit_file)
            else:
                logger.warning("Explicit endpoint file not found: %s", explicit_file)
                # Continue to fallback options

        # 2. Fetch latest mode - fetch from upstream sources
        if use_git_provider:
            logger.info("Fetching latest endpoint data for solution: %s", solution)
            return EndpointResolver._load_from_git_provider(solution)

        # 3. Packaged resource
        packaged_data = ResourceManager.get_packaged_endpoint_data(solution)
        if packaged_data:
            logger.info("Using packaged endpoint data for solution: %s", solution)
            return packaged_data

        logger.error("No endpoint data found for solution: %s", solution)
        return None

    @staticmethod
    def exclude_endpoints(
        endpoints_data: list[dict[str, Any]], names: list[str]
    ) -> list[dict[str, Any]]:
        """
        Remove endpoint definitions whose ``name`` is in ``names``.

        Matching is applied at every nesting level, so child endpoints can be
        excluded on their own. Children of an excluded entry are removed with it.

        Args:
            endpoints_data: Resolved endpoint definitions
            names: Endpoint names to exclude

        Returns:
            Endpoint definitions without the excluded entries

        Raises:
            ValueError: If a name does not match any endpoint at any level
        """
        if not names:
            return endpoints_data

        excluded = set(names)
        found: set[str] = set()

        def prune(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
            kept = []
            for entry in entries:
                name = entry.get("name")
                if name in excluded:
                    found.add(name)
                    continue
                if entry.get("children"):
                    entry = {**entry, "children": prune(entry["children"])}
                kept.append(entry)
            return kept

        result = prune(endpoints_data)
        unknown = sorted(excluded - found)
        if unknown:
            raise ValueError(
                f"Unknown endpoint name(s) to exclude: {', '.join(unknown)}"
            )
        logger.info("Excluding endpoints from collection: %s", ", ".join(sorted(found)))
        return result

    @staticmethod
    def load_exclude_file(file_path: str) -> list[str]:
        """
        Load endpoint names to exclude from a YAML file.

        The file is a YAML list of endpoint names.

        Raises:
            ValueError: If the file cannot be read or is not a list of strings
        """
        try:
            yaml = YAML(typ="safe", pure=True)
            with Path(file_path).open(encoding="utf-8") as f:
                data = yaml.load(f)
        except (OSError, YAMLError) as e:
            raise ValueError(f"Failed to load exclude file {file_path}: {e}") from e
        if data is None:
            return []
        if not isinstance(data, list) or not all(isinstance(n, str) for n in data):
            raise ValueError(
                f"Exclude file {file_path} must be a YAML list of endpoint names"
            )
        return data

    @staticmethod
    def _load_from_file(file_path: str) -> list[dict[str, Any]] | None:
        """Load endpoint data from a YAML file."""
        try:
            yaml = YAML(typ="safe", pure=True)
            with Path(file_path).open(encoding="utf-8") as f:
                data: list[dict[str, Any]] = yaml.load(f)
                logger.debug("Loaded endpoint data from file: %s", file_path)
                return data
        except Exception as e:
            logger.error("Failed to load endpoint data from file %s: %s", file_path, e)
            return None

    @staticmethod
    def _load_from_git_provider(solution: str) -> list[dict[str, Any]] | None:
        """Load endpoint data from upstream sources."""
        try:
            wrapper = GithubRepoWrapper(
                repo_url=f"https://github.com/CiscoDevNet/terraform-provider-{solution.lower()}.git",
                clone_dir=GIT_TMP,
                solution=solution.lower(),
            )
            data = wrapper.get_definitions()
            logger.debug("Loaded endpoint data from upstream for: %s", solution)
            return data
        except Exception as e:
            logger.error(
                "Failed to load endpoint data from upstream for %s: %s", solution, e
            )
            return None
