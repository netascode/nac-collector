"""Endpoint resolver for orchestrating endpoint data resolution from multiple sources."""

import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

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
