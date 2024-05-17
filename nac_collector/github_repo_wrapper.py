import logging
import os
import shutil

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
        self.yaml = YAML(typ="safe", pure=True)
        self.yaml.default_flow_style = False
        self.yaml.sort_keys = False

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
        endpoint format to the endpoints_dict list. For other files, it appends a dictionary
        with the 'rest_endpoint' value from the file content.

        If the method encounters a directory named 'feature_templates', it appends a specific
        endpoint format to the endpoints list and a corresponding dictionary to the endpoints_dict list.

        After traversing all files and directories, it saves the endpoints_dict list to a new
        YAML file named 'endpoints_{self.solution}.yaml' and then deletes the cloned repository.

        This method does not return any value.
        """
        definitions_dir = os.path.join(self.clone_dir, "gen", "definitions")
        self.logger.info("Inspecting YAML files in %s", definitions_dir)
        endpoints = []
        endpoints_dict = []
        for root, _, files in os.walk(definitions_dir):
            for file in files:
                if file.endswith(".yaml"):
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
                                endpoints_dict.append(
                                    {
                                        "name": file.split(".yaml")[0],
                                        "endpoint": "/template/device/object/%i",
                                    }
                                )
                            else:
                                endpoints_dict.append(
                                    {
                                        "name": file.split(".yaml")[0],
                                        "endpoint": data["rest_endpoint"],
                                    }
                                )

                # for SDWAN feature_templates
                if root.endswith("feature_templates"):
                    self.logger.debug("Found feature_templates directory")
                    endpoints.append("/template/feature/object/%i")
                    endpoints_dict.append(
                        {
                            "name": "feature_templates",
                            "endpoint": "/template/feature/object/%i",
                        }
                    )
                    break

        # Save endpoints to a YAML file
        filename = f"endpoints_{self.solution}.yaml"

        with open(filename, "w", encoding="utf-8") as f:
            self.yaml.dump(endpoints_dict, f)
        self.logger.info("Saved endpoints to %s", filename)

        self._delete_repo()

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
