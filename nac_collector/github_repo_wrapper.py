import logging
import os
import shutil
from pathlib import Path
from typing import Any

from git import Repo
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from ruamel.yaml import YAML

logger = logging.getLogger("main")


class GithubRepoWrapper:
    """
    This class is a wrapper for interacting with a GitHub repository.

    It initializes with a repository URL, a directory to clone the repository into,
    and a solution name. Upon initialization, it sets up a logger, clones the repository
    into the specified directory, and creates a safe, pure instance of the YAML class
    with specific configuration.

    Attributes:
        repo_url (str): The URL of the GitHub repository.
        clone_dir (str): The directory to clone the repository into.
        solution (str): The name of the solution.
        logger (logging.Logger): A logger instance.
        yaml (ruamel.yaml.YAML): A YAML instance.

    Methods:
        _clone_repo: Clones the GitHub repository into the specified directory.
        get_definitions: Inspects YAML files in the repository, extracts endpoint information,
                         and saves it to a new YAML file.
    """

    def __init__(self, repo_url: str, clone_dir: str | Path, solution: str) -> None:
        self.repo_url = repo_url
        self.clone_dir = str(clone_dir)
        self.solution = solution
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing GithubRepoWrapper")
        self._clone_repo()

        self.yaml = YAML()
        self.yaml.default_flow_style = False  # Use block style
        self.yaml.indent(sequence=2)

    def _clone_repo(self) -> None:
        # Check if the directory exists and is not empty
        clone_path = Path(self.clone_dir)
        if clone_path.exists() and any(clone_path.iterdir()):
            self.logger.debug("Directory exists and is not empty. Deleting directory.")
            # Delete the directory and its contents
            shutil.rmtree(self.clone_dir)

        # Log a message before cloning the repository
        self.logger.info(
            "Cloning repository from %s to %s", self.repo_url, self.clone_dir
        )

        # Clone the repository
        Repo.clone_from(self.repo_url, self.clone_dir)
        self.logger.info(
            "Successfully cloned repository from %s to %s",
            self.repo_url,
            self.clone_dir,
        )

    def get_definitions(self) -> list[dict[str, Any]]:
        """
        This method inspects YAML files in a specific directory, extracts endpoint information,
        and saves it to a new YAML file. It specifically looks for files ending with '.yaml'
        and keys named 'rest_endpoint' in the file content.

        For files named 'feature_device_template.yaml', it appends a dictionary with a specific
        endpoint format to the endpoints_list list. For other files, it appends a dictionary
        with the 'rest_endpoint' value from the file content.

        If the method encounters a directory named 'feature_templates', it appends a specific
        endpoint format to the endpoints list and a corresponding dictionary to the endpoints_list list.

        After traversing all files and directories, it processes the endpoints_list and deletes
        the cloned repository.

        Returns:
            list[dict[str, Any]]: List of endpoint definitions with name and endpoint keys.
        """
        definitions_dir = Path(self.clone_dir) / "gen" / "definitions"
        self.logger.info("Inspecting YAML files in %s", definitions_dir)
        endpoints = []
        endpoints_list = []

        for root, _, files in os.walk(definitions_dir):
            # Iterate over all endpoints
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=None,
            ) as progress:
                task = progress.add_task(
                    "Processing terraform provider definitions", total=len(files)
                )
                for file in files:
                    progress.advance(task)
                    # Exclude *_update_rank used in ISE from inspecting
                    if file.endswith(".yaml") and not file.endswith("update_rank.yaml"):
                        with (Path(root) / file).open(encoding="utf-8") as f:
                            data = self.yaml.load(f)
                            if data.get("no_read") is not None and data.get("no_read"):
                                continue
                            if data.get("no_resource") is not None and data.get(
                                "no_resource"
                            ):
                                continue
                            if "rest_endpoint" in data or "get_rest_endpoint" in data:
                                # exception for SDWAN localized_policy,cli_device_template,centralized_policy,security_policy
                                if file.split(".yaml")[0] in [
                                    "localized_policy",
                                    "cli_device_template",
                                    "centralized_policy",
                                    "security_policy",
                                ]:
                                    endpoint = data["rest_endpoint"]
                                else:
                                    endpoint = (
                                        data.get("get_rest_endpoint")
                                        if data.get("get_rest_endpoint") is not None
                                        else data["rest_endpoint"]
                                    )
                                self.logger.info(
                                    "Found rest_endpoint: %s in file: %s",
                                    endpoint,
                                    file,
                                )
                                # for SDWAN feature_device_templates
                                if file.split(".yaml")[0] == "feature_device_template":
                                    endpoints_list.append(
                                        {
                                            "name": file.split(".yaml")[0],
                                            "endpoint": "/template/device/object/%i",
                                        }
                                    )
                                else:
                                    endpoints_list.append(
                                        {
                                            "name": file.split(".yaml")[0],
                                            "endpoint": endpoint,
                                        }
                                    )

                    # for SDWAN feature_templates
                    if root.endswith("feature_templates"):
                        self.logger.debug("Found feature_templates directory")
                        endpoints.append("/template/feature/object/%i")
                        endpoints_list.append(
                            {
                                "name": "feature_templates",
                                "endpoint": "/template/feature/object/%i",
                            }
                        )
                        break

        # Adjust endpoints with potential parent-children relationships
        endpoints_list = self.parent_children(endpoints_list)

        self._delete_repo()

        return endpoints_list

    def parent_children(
        self, endpoints_list: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        """
        Adjusts the endpoints_list list to include parent-child relationships
        for endpoints containing `%v` and `%s`. It separates the endpoints into parent and
        child entries, modifying the YAML output structure to reflect this hierarchy.

        Args:
            endpoints_list (list): List of endpoint dictionaries containing name and endpoint keys.

        Returns:
            list: The modified list of endpoint dictionaries with parent-child relationships.
        """
        self.logger.info("Adjusting endpoints for parent-child relationships")
        modified_endpoints = []

        # Dictionary to hold parents and their children based on paths
        parent_map: dict[str, Any] = {}

        # Function to split endpoint and register it in the hierarchy
        def register_endpoint(parts: list[str], name: str) -> None:
            current_level = parent_map
            base_endpoint = parts[0]

            # Register base endpoint
            if base_endpoint not in current_level:
                current_level[base_endpoint] = {"names": [], "children": {}}
            current_level = current_level[base_endpoint]

            # Process each subsequent segment
            for part in parts[1:]:
                if part not in current_level["children"]:
                    current_level["children"][part] = {"names": [], "children": {}}
                current_level = current_level["children"][part]

            # Add the name to the list of names for this segment
            # This is to handle a case where there are two endpoint_data
            # with different name but same endpoint url
            if "names" not in current_level:
                current_level["names"] = []
            if (
                isinstance(current_level["names"], list)
                and name not in current_level["names"]
            ):
                current_level["names"].append(name)

        # Process each endpoint
        for endpoint_data in endpoints_list:
            endpoint = endpoint_data["endpoint"]
            name = endpoint_data["name"]

            # Split the endpoint by placeholders and slashes
            parts = []
            remaining = endpoint
            while remaining:
                if "%v" in remaining or "%s" in remaining:
                    pre, _, post = remaining.partition(
                        "%v" if "%v" in remaining else "%s"
                    )
                    parts.append(pre.rstrip("/"))
                    remaining = post
                else:
                    parts.append(
                        remaining.rstrip(
                            "/"
                            if "%v" in endpoint
                            or "%s" in endpoint
                            or "/v1/feature-profile/" in endpoint
                            else ""
                        )
                    )
                    break

            # Register the endpoint in the hierarchy
            register_endpoint(parts, name)

        # Convert the hierarchical map to a list format
        def build_hierarchy(node: dict[str, Any]) -> list[dict[str, Any]]:
            """
            Recursively build the YAML structure from the hierarchical dictionary.
            """
            output = []
            for part, content in node.items():
                # Create an entry for each name associated with this endpoint
                for name in content["names"]:
                    entry = {"name": name, "endpoint": part}
                    if content["children"]:
                        entry["children"] = build_hierarchy(content["children"])
                    output.append(entry)
            return output

        # Build the final list from the parent_map
        modified_endpoints = build_hierarchy(parent_map)

        return modified_endpoints

    def _delete_repo(self) -> None:
        """
        This private method is responsible for deleting the cloned GitHub repository
        from the local machine. It's called after the necessary data has been extracted
        from the repository.

        This method does not return any value.
        """
        # Check if the directory exists
        if Path(self.clone_dir).exists():
            # Delete the directory and its contents
            shutil.rmtree(self.clone_dir)
        self.logger.info("Deleted repository")
