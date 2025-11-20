import logging
import os
from typing import Any

from meraki.exceptions import APIError
from meraki.rest_session import RestSession
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from nac_collector.cli import console
from nac_collector.controller.base import CiscoClientController

logger = logging.getLogger("main")

# Suppress urllib3 warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)


class CiscoClientMERAKI(CiscoClientController):
    """
    This class inherits from the abstract class CiscoClientController. It's used for authenticating
    with the Cisco MERAKI API and retrieving data from various endpoints.
    This is a single step authentication.
     - API Token / Key is used for all queries - must be passed via "password" argument.
    """

    SOLUTION = "meraki"

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str,
        max_retries: int,
        retry_after: int,
        timeout: int,
        ssl_verify: bool,
    ) -> None:
        super().__init__(
            username,
            password,
            base_url,
            max_retries,
            retry_after,
            timeout,
            ssl_verify,
        )

        self.allowed_org_ids: list[str] | None = None
        allowed_org_ids_env = os.getenv("NAC_MERAKI_ORG_IDS", "")
        if allowed_org_ids_env != "":
            self.allowed_org_ids = allowed_org_ids_env.split(",")

    def authenticate(self) -> bool:
        """
        Perform basic authentication.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """

        if not self.password:
            logger.error(
                'API key (passed via "password") is required for authentication.'
            )
            return False

        # TODO Use self.ssl_verify, self.timeout?
        self.session = RestSession(
            logger, self.password, caller="NacCollector netascode"
        )
        logger.info("Authentication successful with API key.")
        return True

    def process_endpoint_data(
        self,
        endpoint: dict[str, Any],
        endpoint_dict: dict[str, Any],
        data: dict[str, Any] | list[Any] | None,
        err_data: dict[str, Any] | None,
        parent_ids: list[str | int],
    ) -> dict[str, Any]:
        """
        Process the data for a given endpoint and update the endpoint_dict.

        Parameters:
            endpoint (dict): The endpoint configuration.
            endpoint_dict (dict): The dictionary to store processed data.
            data (dict or list or None): The data fetched from the endpoint (mutually exclusive with err_data).
            err_data (dict or None): The error message fetched from the endpoint (mutually exclusive with data).

        Returns:
            dict: The updated endpoint dictionary with processed data.
        """

        if data is None:
            endpoint_dict[endpoint["name"]] = {
                "error": err_data,
                "endpoint": endpoint["endpoint"],
            }
            return endpoint_dict

        # The response is a single resource instance.
        if isinstance(data, dict) and "items" not in data:
            endpoint_dict[endpoint["name"]] = self.process_single_resource_data(
                data, endpoint, parent_ids
            )
            return endpoint_dict

        # The response has multiple resource instances.

        if isinstance(data, list):
            items = data
        else:
            items = data["items"]
            if not isinstance(items, list):
                items = []

        for item in items:
            endpoint_dict[endpoint["name"]].append(
                self.process_single_resource_data(item, endpoint, parent_ids)
            )

        return endpoint_dict  # Return the processed endpoint dictionary

    @staticmethod
    def process_single_resource_data(
        data: dict[str, Any], endpoint: dict[str, Any], parent_ids: list[str | int]
    ) -> dict[str, Any]:
        result = {
            "data": data,
            "endpoint": endpoint["endpoint"],
        }

        terraform_import_ids = None
        if CiscoClientMERAKI.endpoint_has_own_id(endpoint):
            id = CiscoClientMERAKI.get_id_value(data, endpoint)
            # TODO If get_id_value() return None, this just gets put into the string as "/None".
            result["endpoint"] = f"{endpoint['endpoint']}/{id}"
            if id is not None:
                terraform_import_ids = parent_ids + [id]
        else:
            terraform_import_ids = parent_ids
        result["terraform_import_ids"] = terraform_import_ids

        return result

    def get_from_endpoints_data(
        self, endpoints_data: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Retrieve data from a list of endpoint definitions provided as data structure.

        Parameters:
            endpoints_data (list[dict[str, Any]]): List of endpoint definitions with name and endpoint keys.

        Returns:
            dict: The final dictionary containing the data retrieved from the endpoints.
        """

        # Initialize an empty dictionary
        final_dict = {}

        # Iterate over all endpoints
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            for endpoint in endpoints_data:
                endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)

                data, err_data = self.fetch_data_with_error(endpoint["endpoint"])

                data = self.filter_organizations(endpoint, data)

                endpoint_dict = self.process_endpoint_data(
                    endpoint,
                    endpoint_dict,
                    data,
                    err_data,
                    [],
                )

                if endpoint.get("children"):
                    self.get_from_children_endpoints(
                        endpoint,
                        endpoint["endpoint"],
                        endpoint_dict[endpoint["name"]],
                        [],
                        {},
                        progress,
                    )

                # Save results to dictionary
                final_dict.update(endpoint_dict)

        return final_dict

    def filter_organizations(
        self, endpoint: dict[str, Any], data: dict[str, Any] | list[Any] | None
    ) -> dict[str, Any] | list[Any] | None:
        if endpoint["name"] != "organization":
            return data

        if not isinstance(data, list):
            return data

        if self.allowed_org_ids is None:
            return data

        return [
            org
            for org in data
            if self.get_id_value(org, endpoint) in self.allowed_org_ids
        ]

    def get_from_children_endpoints(
        self,
        parent_endpoint: dict[str, Any],
        parent_endpoint_uri: str,
        parent_endpoint_dict: list[dict[str, Any]] | dict[str, Any],
        grandparent_endpoints_ids: list[str | int],
        grandparent_conditions: dict[str, Any],
        progress: Progress,
    ) -> None:
        if isinstance(parent_endpoint_dict, dict):
            logger.info(
                "Skipping fetching children of %s (%s) as it returned no data",
                parent_endpoint["name"],
                parent_endpoint_uri,
            )
            return

        items: list[dict[str, Any]] = parent_endpoint_dict

        parent_instances = []
        for item in items:
            # Add the item's id to the list
            parent_id = self.get_id_value(item["data"], parent_endpoint)
            if parent_id is None:
                continue
            conditions = self.get_parent_conditions(
                item["data"], parent_endpoint, grandparent_conditions
            )
            parent_instance = {
                "id": parent_id,
                "conditions": conditions,
            }
            parent_instances.append(parent_instance)

        if parent_endpoint.get("root"):
            # Use the parent as the root in the URI, ignoring the parent's parent.
            parent_endpoint_uri = parent_endpoint["endpoint"]
            # Ignore the parent's parent's ID.
            grandparent_endpoints_ids = []

        children_endpoints_task = progress.add_task(
            f"Fetching children of {parent_endpoint_uri}"
        )
        for children_endpoint in progress.track(
            parent_endpoint["children"], task_id=children_endpoints_task
        ):
            children_endpoint_task = progress.add_task(
                f"Fetching {children_endpoint['endpoint']} for each {parent_endpoint['name']}"
            )
            for parent_instance in progress.track(
                parent_instances, task_id=children_endpoint_task
            ):
                parent_id = parent_instance["id"]
                parent_conditions = parent_instance["conditions"]
                children_endpoint_uri = (
                    f"{parent_endpoint_uri}/{parent_id}{children_endpoint['endpoint']}"
                )

                should_skip, reason = self.should_skip_by_parent_conditions(
                    children_endpoint, parent_conditions
                )
                if should_skip:
                    logger.info(
                        "Skipping fetching %s (%s): %s",
                        children_endpoint["name"],
                        children_endpoint_uri,
                        reason,
                    )
                    continue

                children_endpoint_dict = CiscoClientController.create_endpoint_dict(
                    children_endpoint
                )

                data, err_data = self.fetch_data_with_error(children_endpoint_uri)

                # Process the children endpoint data and get the updated dictionary
                children_endpoint_dict = self.process_endpoint_data(
                    children_endpoint,
                    children_endpoint_dict,
                    data,
                    err_data,
                    grandparent_endpoints_ids + [parent_id],
                )

                if children_endpoint.get("children"):
                    self.get_from_children_endpoints(
                        children_endpoint,
                        children_endpoint_uri,
                        children_endpoint_dict[children_endpoint["name"]],
                        grandparent_endpoints_ids + [parent_id],
                        parent_conditions,
                        progress,
                    )

                for index, value in enumerate(items):
                    value_data = value.get("data")
                    if not isinstance(value_data, dict):
                        value_data = {}
                    if self.get_id_value(value_data, parent_endpoint) == parent_id:
                        items[index].setdefault("children", {})[
                            children_endpoint["name"]
                        ] = children_endpoint_dict[children_endpoint["name"]]

            progress.remove_task(children_endpoint_task)

        progress.remove_task(children_endpoints_task)

    def fetch_data_with_error(
        self, uri: str
    ) -> tuple[dict[str, Any] | list[Any] | None, dict[str, Any] | None]:
        try:
            metadata = {
                "tags": ["no tag"],
                "operation": "no operation",
            }
            data = self.session.get_pages(metadata, uri)
            return data, None
        except APIError as e:
            return None, {
                "status_code": e.status,
                "message": e.message,
            }

    @staticmethod
    def endpoint_has_own_id(endpoint: dict[str, Any]) -> bool:
        result: bool = endpoint.get("has_own_id", False)
        return result

    @staticmethod
    def endpoint_id_property(endpoint: dict[str, Any]) -> str:
        result: str = endpoint.get("id_name", "id")
        return result

    @staticmethod
    def get_id_value(i: dict[str, Any], endpoint: dict[str, Any]) -> str | int | None:
        """
        Attempts to get the ID from an API resource's response.

        Parameters:
            i (dict): The resource response.
            endpoint (dict): The endpoint configuration.

        Returns:
            str or int or None: The ID if it exists (str or int),
                                None if the endpoint does not have its own ID or the ID field is missing.
        """

        id_name = CiscoClientMERAKI.endpoint_id_property(endpoint)
        try:
            return (
                i[id_name]
                if (isinstance(i[id_name], str) or isinstance(i[id_name], int))
                else None
            )
        except KeyError:
            return None

    @staticmethod
    def get_parent_conditions(
        parent_data: dict[str, Any],
        parent_endpoint: dict[str, Any],
        grandparent_conditions: dict[str, Any],
    ) -> dict[str, Any]:
        result = grandparent_conditions.copy()

        if parent_endpoint["name"] == "device":
            result["device_type"] = parent_data.get("productType")
            result["device_model"] = parent_data.get("model")

        return result

    @staticmethod
    def should_skip_by_parent_conditions(
        children_endpoint: dict[str, Any], parent_conditions: dict[str, Any]
    ) -> tuple[bool, str]:
        allowed_device_types = children_endpoint.get("allowed_device_types")
        device_type = parent_conditions.get("device_type")
        if (
            allowed_device_types is not None
            and device_type is not None
            and device_type not in allowed_device_types
        ):
            return True, f"the endpoint is not applicable for device type {device_type}"

        allowed_device_models = children_endpoint.get("allowed_device_models")
        device_model = parent_conditions.get("device_model")
        if allowed_device_models is not None and device_model is not None:
            if not any(
                device_model.startswith(allowed_model_prefix)
                for allowed_model_prefix in allowed_device_models
            ):
                return (
                    True,
                    f"the endpoint is not applicable for device model {device_model}",
                )

        return False, ""
