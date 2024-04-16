from git import Repo
import os
import shutil
import logging
from ruamel.yaml import YAML

logger = logging.getLogger("main")


class GithubRepoWrapper:
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
        self.logger.info("Cloning repository from %s to %s", self.repo_url, self.clone_dir)

        # Clone the repository
        Repo.clone_from(self.repo_url, self.clone_dir)
        self.logger.info(
            "Successfully cloned repository from %s to %s",
            self.repo_url,
            self.clone_dir,
        )

    def get_definitions(self):
        definitions_dir = os.path.join(self.clone_dir, "gen", "definitions")
        self.logger.info("Inspecting YAML files in %s", definitions_dir)
        endpoints = []
        endpoints_dict = []
        for root, dirs, files in os.walk(definitions_dir):
            for file in files:
                if file.endswith(".yaml"):
                    with open(os.path.join(root, file), "r") as f:
                        data = self.yaml.load(f)
                        if "rest_endpoint" in data:
                            self.logger.info(
                                "Found rest_endpoint: %s in file: %s",
                                data["rest_endpoint"],
                                file,
                            )
                            endpoints.append(data["rest_endpoint"])
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

        with open(filename, "w") as f:
            self.yaml.dump(endpoints_dict, f)
        self.logger.info("Saved endpoints to %s", filename)

        self._delete_repo()

    def _delete_repo(self):
        # Check if the directory exists
        if os.path.exists(self.clone_dir):
            # Delete the directory and its contents
            shutil.rmtree(self.clone_dir)
        self.logger.info("Deleted repository")
