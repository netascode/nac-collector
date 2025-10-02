"""Resource manager for accessing packaged endpoint files."""

import logging
from importlib import resources
from typing import Any

from ruamel.yaml import YAML

logger = logging.getLogger(__name__)


class ResourceManager:
    """Manages access to packaged endpoint resources."""

    @staticmethod
    def get_packaged_endpoint_data(solution: str) -> list[dict[str, Any]] | None:
        """
        Get endpoint data from a packaged endpoint YAML file.

        Args:
            solution: The solution name (e.g., 'ise', 'sdwan', etc.)

        Returns:
            List of endpoint definitions if file exists, None otherwise.
        """
        try:
            from nac_collector.resources import endpoints

            filename = f"{solution.lower()}.yaml"

            if resources.is_resource(endpoints, filename):
                content = resources.read_text(endpoints, filename)
                logger.debug("Read packaged endpoint data for: %s", solution)

                yaml = YAML(typ="safe")
                parsed_content: list[dict[str, Any]] = yaml.load(content)
                return parsed_content
            else:
                logger.debug("Packaged endpoint file not found: %s", filename)
                return None

        except (ImportError, AttributeError, FileNotFoundError, Exception) as e:
            logger.debug("Failed to read packaged endpoint data: %s", e)
            return None

    @staticmethod
    def get_packaged_lookup_content(solution: str) -> dict[str, Any] | list[Any] | None:
        """
        Get content of a packaged lookup YAML file from the lookups subdirectory.

        Args:
            solution: The solution name (e.g., 'catalystcenter', 'ise', etc.)

        Returns:
            Parsed YAML content as dict or list if file exists, None otherwise.
        """
        try:
            # Import the lookups resource package
            from nac_collector.resources import lookups

            filename = f"{solution.lower()}.yaml"

            if resources.is_resource(lookups, filename):
                content = resources.read_text(lookups, filename)
                logger.debug("Read packaged lookup content for: %s", solution)

                yaml = YAML(typ="safe")
                parsed_content: dict[str, Any] = yaml.load(content)
                return parsed_content
            else:
                logger.debug("Packaged lookup file not found: %s", filename)
                return None

        except (ImportError, AttributeError, FileNotFoundError, Exception) as e:
            logger.debug("Failed to read packaged lookup content: %s", e)
            return None

    @staticmethod
    def list_available_solutions() -> list[str]:
        """
        List all available solutions that have packaged endpoint files.

        Returns:
            List of solution names.
        """
        try:
            from nac_collector.resources import endpoints

            available_solutions = []

            # Get all files in the endpoints resource package
            for resource_name in resources.contents(endpoints):
                if resource_name.endswith(".yaml") and not resource_name.startswith(
                    "_"
                ):
                    # Extract solution name from filename
                    solution = resource_name[:-5]  # Remove ".yaml" suffix
                    available_solutions.append(solution)

            logger.debug("Available packaged solutions: %s", available_solutions)
            return sorted(available_solutions)

        except (ImportError, AttributeError) as e:
            logger.debug("Failed to list available solutions: %s", e)
            return []
