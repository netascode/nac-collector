import logging
import os
import shutil

import click
from git import Repo
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

    def __init__(self, repo_url, clone_dir, solution):
        self.repo_url = repo_url
        self.clone_dir = clone_dir
        self.solution = solution
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing GithubRepoWrapper")
        self._clone_repo()
        # Create an instance of the YAML class
        # elf.yaml = YAML(typ="safe", pure=True)
        # self.yaml.default_flow_style = False
        # self.yaml.sort_keys = False
        self.yaml = YAML()
        self.yaml.default_flow_style = False  # Use block style
        self.yaml.indent(sequence=2)

    def _clone_repo(self):
        # Check if the directory exists and is not empty
        if os.path.exists(self.clone_dir) and os.listdir(self.clone_dir):
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

    def get_definitions(self):
        """
        This method inspects YAML files in a specific directory, extracts endpoint information,
        and saves it to a new YAML file. It specifically looks for files ending with '.yaml'
        and keys named 'rest_endpoint' in the file content.

        For files named 'feature_device_template.yaml', it appends a dictionary with a specific
        endpoint format to the endpoints_list list. For other files, it appends a dictionary
        with the 'rest_endpoint' value from the file content.

        If the method encounters a directory named 'feature_templates', it appends a specific
        endpoint format to the endpoints list and a corresponding dictionary to the endpoints_list list.

        After traversing all files and directories, it saves the endpoints_list list to a new
        YAML file named 'endpoints_{self.solution}.yaml' and then deletes the cloned repository.

        This method does not return any value.
        """
        definitions_dir = os.path.join(self.clone_dir, "gen", "definitions")
        self.logger.info("Inspecting YAML files in %s", definitions_dir)
        endpoints = []
        endpoints_list = []

        for root, _, files in os.walk(definitions_dir):
            # Iterate over all endpoints
            with click.progressbar(
                files, label="Processing terraform provider definitions"
            ) as files_bar:
                for file in files_bar:
                    if file.endswith(".yaml") and not file.endswith("update_rank.yaml"):
                        with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                            data = self.yaml.load(f)
                            if "rest_endpoint" in data:
                                self.logger.info(
                                    "Found rest_endpoint: %s in file: %s",
                                    data["rest_endpoint"],
                                    file,
                                )
                                endpoints.append(data["rest_endpoint"])
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
                                            "endpoint": data["rest_endpoint"],
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

        # Save endpoints to a YAML file
        self._save_to_yaml(endpoints_list)

        self._delete_repo()

    def parent_children(self, endpoints_list):
        """
        Adjusts the endpoints_list list to include parent-child relationships
        for endpoints containing `%v`. It separates the endpoints into parent and
        child entries, modifying the YAML output structure to reflect this hierarchy.

        Args:
            endpoints_list (list): List of endpoint dictionaries containing name and endpoint keys.

        Returns:
            list: The modified list of endpoint dictionaries with parent-child relationships.
        """
        self.logger.info("Adjusting endpoints for parent-child relationships")
        modified_endpoints = []

        # Dictionary to hold parents and their children
        parent_map = {}

        # First, identify all potential children with '%v'
        for endpoint_data in endpoints_list:
            endpoint = endpoint_data["endpoint"]
            name = endpoint_data["name"]

            if "%v" in endpoint:
                base_endpoint, child_path = endpoint.split("/%v", 1)
                # Identify the base endpoint and treat this entry as a child
                child_entry = {"name": name, "endpoint": child_path}

                # Add this child to the corresponding parent in parent_map
                if base_endpoint in parent_map:
                    parent_map[base_endpoint]["children"].append(child_entry)
                else:
                    # If parent doesn't exist, create it
                    parent_map[base_endpoint] = {
                        "name": None,  # Parent name to be set later
                        "endpoint": base_endpoint,
                        "children": [child_entry],
                    }
            if "%s" in endpoint:
                for parent_map_key in parent_map:
                    children = parent_map[parent_map_key]["children"]
                    to_add = []
                    for l1_children in children:
                        if "%s" in l1_children["endpoint"]:
                            base_endpoint, child_path = l1_children["endpoint"].split(
                                "%s", 1
                            )
                            child_entry = {"name": name, "endpoint": child_path}
                            # Collect all child entries to be added
                            for child in children:
                                if base_endpoint.rstrip("/") == child[
                                    "endpoint"
                                ].rstrip("/"):
                                    value_exists = any(
                                        child_entry["endpoint"] in d.values()
                                        for d in child.get("children", "")
                                    )
                                    if not value_exists:
                                        to_add.append((child, child_entry))
                    # Add all collected child entries
                    for parent, child_entry in to_add:
                        if "children" in parent:
                            parent["children"].append(child_entry)
                        else:
                            parent["children"] = [child_entry]

        # Now go through endpoints to fill out parent details
        for endpoint_data in endpoints_list:
            endpoint = endpoint_data["endpoint"]
            name = endpoint_data["name"]

            # Normalize the input path by removing any trailing slashes
            endpoint = endpoint.rstrip("/")

            if endpoint in parent_map:
                # This is a confirmed parent endpoint
                parent_map[endpoint]["name"] = name
            else:
                # This endpoint is not a parent; no children reference it
                if "%v" not in endpoint and "%s" not in endpoint:
                    # Standalone endpoint, add directly to modified_endpoints
                    modified_endpoints.append(endpoint_data)

        # Add all valid parent-child structures to the modified_endpoints list
        for _, parent_data in parent_map.items():
            # Add to modified list only if it has children
            if parent_data["children"]:
                # Remove the entry of child object with %s
                parent_data["children"] = [
                    child
                    for child in parent_data["children"]
                    if "%s" not in child.get("endpoint", "")
                ]
                modified_endpoints.append(parent_data)

        # Return the modified endpoints list
        return modified_endpoints

    def _delete_repo(self):
        """
        This private method is responsible for deleting the cloned GitHub repository
        from the local machine. It's called after the necessary data has been extracted
        from the repository.

        This method does not return any value.
        """
        # Check if the directory exists
        if os.path.exists(self.clone_dir):
            # Delete the directory and its contents
            shutil.rmtree(self.clone_dir)
        self.logger.info("Deleted repository")

    def _save_to_yaml(self, data):
        """
        Saves the given data to a YAML file named 'endpoints_{solution}.yaml'.

        Args:
            data (list): The data to be saved into the YAML file.

        This method does not return any value.
        """
        filename = f"endpoints_{self.solution}.yaml"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                self.yaml.dump(data, f)
            self.logger.info("Saved endpoints to %s", filename)
        except Exception as e:
            self.logger.error("Failed to save YAML file %s: %s", filename, str(e))
            raise
