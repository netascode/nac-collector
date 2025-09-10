#!/usr/bin/env python3
"""
Script to update endpoint definition files from Terraform provider repositories.

This script fetches the latest endpoint definitions from the respective
Terraform provider GitHub repositories and updates the packaged endpoint
files in nac_collector/resources/endpoints/.
"""

import logging
import sys
from pathlib import Path

from ruamel.yaml import YAML

# Add parent directory to path to import nac_collector modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from nac_collector.constants import GIT_TMP
from nac_collector.github_repo_wrapper import GithubRepoWrapper

# Solutions that support fetching from upstream sources
# NDO is excluded as it has a different repository structure
SUPPORTED_SOLUTIONS = ["fmc", "ise", "sdwan"]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def update_endpoint_file(solution: str) -> bool:
    """
    Update the endpoint file for a specific solution.

    Args:
        solution: The solution name (e.g., 'ise', 'sdwan')

    Returns:
        True if update was successful, False otherwise
    """
    logger.info(f"Updating endpoint definitions for {solution}")

    try:
        # Initialize the GitHub wrapper to fetch definitions
        clone_dir = Path(GIT_TMP) / solution
        wrapper = GithubRepoWrapper(
            repo_url=f"https://github.com/CiscoDevNet/terraform-provider-{solution.lower()}.git",
            clone_dir=str(clone_dir),
            solution=solution.lower(),
        )

        # Get the endpoint definitions
        endpoint_data = wrapper.get_definitions()

        if not endpoint_data:
            logger.warning(f"No endpoint data retrieved for {solution}")
            return False

        # Determine the output file path
        output_dir = (
            Path(__file__).parent.parent / "nac_collector" / "resources" / "endpoints"
        )
        output_file = output_dir / f"{solution.lower()}.yaml"

        # Ensure the output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save the endpoint data to YAML file
        yaml = YAML()
        yaml.default_flow_style = False
        yaml.indent(sequence=2)
        yaml.preserve_quotes = True

        with open(output_file, "w", encoding="utf-8") as f:
            yaml.dump(endpoint_data, f)

        logger.info(f"Successfully updated {output_file}")
        return True

    except Exception as e:
        logger.error(f"Failed to update endpoint file for {solution}: {e}")
        return False


def main() -> int:
    """
    Main function to update all endpoint files.

    Returns:
        Exit code (0 for success, 1 for any failure)
    """
    logger.info("Starting endpoint definition update process")

    success_count = 0
    failure_count = 0
    failed_solutions = []

    for solution in SUPPORTED_SOLUTIONS:
        if update_endpoint_file(solution):
            success_count += 1
        else:
            failure_count += 1
            failed_solutions.append(solution)

    # Log summary
    logger.info(f"Update complete: {success_count} succeeded, {failure_count} failed")

    if failed_solutions:
        logger.error(f"Failed to update: {', '.join(failed_solutions)}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
