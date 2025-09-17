import logging
from typing import Any

import httpx
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

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
        self.x_auth_refresh_token = None

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

        self.client = httpx.Client(
            verify=self.ssl_verify,
            timeout=self.timeout,
        )
        self.client.headers.update(
            {
                "Authorization": "Bearer " + self.password,
                "Content-Type": "application/json",
                "User-Agent": "nac-collector",
            }
        )
        logger.info("Authentication successful with API key.")
        return True

    def process_endpoint_data(
        self,
        endpoint: dict[str, Any],
        endpoint_dict: dict[str, Any],
        data: dict[str, Any] | list[Any] | None,
    ) -> dict[str, Any]:
        """
        Process the data for a given endpoint and update the endpoint_dict.

        Parameters:
            endpoint (dict): The endpoint configuration.
            endpoint_dict (dict): The dictionary to store processed data.
            data (dict or list): The data fetched from the endpoint.

        Returns:
            dict: The updated endpoint dictionary with processed data.
        """

        if data is None:
            endpoint_dict[endpoint["name"]].append(
                {"data": {}, "endpoint": endpoint["endpoint"]}
            )

        elif isinstance(data, list):
            for i in data:
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": i,
                        # TODO If get_id_value() return None, this just gets put into the string as "/None".
                        "endpoint": f"{endpoint['endpoint']}/{self.get_id_value(i, endpoint)}",
                    }
                )

        elif data.get("items", None):
            items = data.get("items")
            if not isinstance(items, list):
                items = []
            for i in items:
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": i,
                        # TODO If get_id_value() return None, this just gets put into the string as "/None".
                        "endpoint": f"{endpoint['endpoint']}/{self.get_id_value(i, endpoint)}",
                    }
                )

        else:
            endpoint_dict[endpoint["name"]] = {
                "data": data,
                "endpoint": endpoint["endpoint"],
            }

        return endpoint_dict  # Return the processed endpoint dictionary

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
            console=None,
        ) as progress:
            task = progress.add_task("Processing endpoints", total=len(endpoints_data))
            for endpoint in endpoints_data:
                progress.advance(task)
                endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)

                data = self.fetch_data(endpoint["endpoint"])

                endpoint_dict = self.process_endpoint_data(
                    endpoint, endpoint_dict, data
                )

                if endpoint.get("children"):
                    self.get_from_children_endpoints(
                        endpoint, endpoint["endpoint"], endpoint_dict[endpoint["name"]]
                    )

                # Save results to dictionary
                final_dict.update(endpoint_dict)

        return final_dict

    def get_from_children_endpoints(
        self,
        parent_endpoint: dict[str, Any],
        parent_endpoint_uri: str,
        parent_endpoint_dict: list[dict[str, Any]],
    ) -> None:
        parent_endpoint_ids = []
        for item in parent_endpoint_dict:
            # Add the item's id to the list
            parent_id = self.get_id_value(item["data"], parent_endpoint)
            if parent_id is None:
                continue
            parent_endpoint_ids.append(parent_id)

        if parent_endpoint.get("root"):
            # Use the parent as the root in the URI, ignoring the parent's parent.
            parent_endpoint_uri = parent_endpoint["endpoint"]

        for children_endpoint in parent_endpoint["children"]:
            logger.info(
                "Processing children endpoint: %s",
                f"{parent_endpoint_uri}/%v{children_endpoint['endpoint']}",
            )

            for parent_id in parent_endpoint_ids:
                children_endpoint_dict = CiscoClientController.create_endpoint_dict(
                    children_endpoint
                )

                children_endpoint_uri = (
                    f"{parent_endpoint_uri}/{parent_id}{children_endpoint['endpoint']}"
                )

                data = self.fetch_data(children_endpoint_uri)

                # Process the children endpoint data and get the updated dictionary
                children_endpoint_dict = self.process_endpoint_data(
                    children_endpoint, children_endpoint_dict, data
                )

                if children_endpoint.get("children"):
                    self.get_from_children_endpoints(
                        children_endpoint,
                        children_endpoint_uri,
                        children_endpoint_dict[children_endpoint["name"]],
                    )

                for index, value in enumerate(parent_endpoint_dict):
                    value_data = value.get("data")
                    if not isinstance(value_data, dict):
                        value_data = {}
                    if self.get_id_value(value_data, parent_endpoint) == parent_id:
                        parent_endpoint_dict[index].setdefault("children", {})[
                            children_endpoint["name"]
                        ] = children_endpoint_dict[children_endpoint["name"]]

    @staticmethod
    def get_id_value(i: dict[str, Any], endpoint: dict[str, Any]) -> str | int | None:
        """
        Attempts to get the 'id' or 'name' value from a dictionary.

        Parameters:
            i (dict): The dictionary to get the 'id' or 'name' value from.
            endpoint (dict): The endpoint configuration.

        Returns:
            str or None: The 'id' or 'name' value if it exists, None otherwise.
        """
        id_name = endpoint.get("id_name", "id")
        try:
            return (
                i[id_name]
                if (isinstance(i[id_name], str) or isinstance(i[id_name], int))
                else None
            )
        except KeyError:
            return None
