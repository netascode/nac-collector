import copy
import json
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


class CiscoClientFMC(CiscoClientController):
    """
    This class inherits from the abstract class CiscoClientController. It's used for authenticating
    with the Cisco FMC API and retrieving data from various endpoints.
    There is two stage authentication.
     - username/password is used to obtain authentication token
     - token is used to authenticate subsequent queries
    """

    FMC_AUTH_ENDPOINTS = ["/api/fmc_platform/v1/auth/generatetoken"]
    SOLUTION = "fmc"

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
            username, password, base_url, max_retries, retry_after, timeout, ssl_verify
        )
        self.x_auth_refresh_token: str | None = None
        self.domains: list[str] = []

    def authenticate(self) -> bool:
        """
        Perform basic authentication.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """

        for api in self.FMC_AUTH_ENDPOINTS:
            auth_url = f"{self.base_url}{api}"

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            response = httpx.post(
                auth_url,
                auth=(self.username, self.password),
                headers=headers,
                verify=self.ssl_verify,
                timeout=self.timeout,
            )

            if response and response.status_code == 204:
                logger.info("Authentication Successful for URL: %s", auth_url)
                # Create a client after successful authentication
                self.client = httpx.Client(
                    verify=self.ssl_verify,
                    timeout=self.timeout,
                )
                self.client.headers.update(
                    {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-auth-access-token": response.headers.get(
                            "X-auth-access-token", ""
                        ),
                    }
                )
                self.x_auth_refresh_token = response.headers.get("X-auth-refresh-token")

                # Save a list of UUIDs of all available domains
                domains_header = response.headers.get("DOMAINS")
                if domains_header:
                    self.domains = [
                        x["uuid"]
                        for x in json.loads(domains_header)
                        if isinstance(x, dict) and "uuid" in x
                    ]
                return True

            logger.error(
                "Authentication failed with status code: %s",
                response.status_code,
            )

        # If all authentication endpoints failed
        return False

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
            # Transparent FTD devices have Global VRF, which is not returned by API
            if endpoint["name"] == "device_vrf":
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": {
                            "description": "This is a Global Virtual Router",
                            "name": "Global",
                        },
                        "endpoint": endpoint["endpoint"],
                    }
                )
            else:
                endpoint_dict[endpoint["name"]] = []

        elif isinstance(data, list):
            endpoint_dict[endpoint["name"]].append(
                {
                    "data": data,
                    "endpoint": endpoint["endpoint"],
                }
            )

        elif "items" in data:
            for i in data.get("items", []):
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": i,
                        "endpoint": f"{endpoint['endpoint']}/{self.get_id_value(i)}",
                    }
                )

        elif "items" not in data and data["paging"]["count"] == 0:
            pass

        else:
            raise ValueError("Unexpected data format received from endpoint")

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

        # Recreate endpoints per-domain
        endpoints = self.resolve_domains(endpoints_data, self.domains)

        # Iterate over all endpoints
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=None,
        ) as progress:
            task = progress.add_task("Processing endpoints", total=len(endpoints))
            for endpoint in endpoints:
                progress.advance(task)
                logger.info("Processing endpoint: %s", endpoint)

                endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)

                data = self.fetch_data(endpoint["endpoint"])

                endpoint_dict = self.process_endpoint_data(
                    endpoint, endpoint_dict, data
                )

                self.process_children(endpoint, endpoint_dict)

                # Save results to dictionary
                # Due to domain expansion, it may happen that same endpoint["name"] will occur multiple times
                if endpoint["name"] not in final_dict:
                    final_dict.update(endpoint_dict)
                else:
                    final_dict[endpoint["name"]].extend(endpoint_dict[endpoint["name"]])

        return final_dict

    def process_children(
        self,
        endpoint: dict[str, Any],
        endpoint_dict: dict[str, Any],
        parent_full_endpoint: str = "",
    ) -> None:
        if not endpoint.get("children"):
            return

        parent_endpoint_ids = []

        for item in endpoint_dict[endpoint["name"]]:
            # Add the item's id to the list
            try:
                parent_endpoint_ids.append(item["data"]["id"])
            except KeyError:
                continue

        for children_endpoint in endpoint["children"]:
            logger.info(
                "Processing children endpoint: %s",
                endpoint["endpoint"] + "/%v" + children_endpoint["endpoint"],
            )

            for id_ in parent_endpoint_ids:
                children_endpoint_dict = CiscoClientController.create_endpoint_dict(
                    children_endpoint
                )

                # Build the full endpoint path
                # Use parent_full_endpoint if provided (for nested children), otherwise use endpoint["endpoint"]
                base_endpoint = (
                    parent_full_endpoint
                    if parent_full_endpoint != ""
                    else endpoint["endpoint"]
                )
                children_joined_endpoint = (
                    base_endpoint + "/" + id_ + children_endpoint["endpoint"]
                )

                data = self.fetch_data(children_joined_endpoint)

                # Process the children endpoint data and get the updated dictionary
                children_endpoint_dict = self.process_endpoint_data(
                    children_endpoint, children_endpoint_dict, data
                )

                for index, value in enumerate(endpoint_dict[endpoint["name"]]):
                    if value.get("data").get("id") == id_:
                        endpoint_dict[endpoint["name"]][index].setdefault(
                            "children", {}
                        )[children_endpoint["name"]] = children_endpoint_dict[
                            children_endpoint["name"]
                        ]

                        # Pass the full accumulated path for nested children
                        self.process_children(
                            children_endpoint,
                            endpoint_dict[endpoint["name"]][index]["children"],
                            children_joined_endpoint,
                        )

    @staticmethod
    def get_id_value(i: dict[str, Any]) -> str | None:
        """
        Attempts to get the 'id' or 'name' value from a dictionary.

        Parameters:
            i (dict): The dictionary to get the 'id' or 'name' value from.

        Returns:
            str or None: The 'id' or 'name' value if it exists, None otherwise.
        """
        try:
            id_value = i["id"]
        except KeyError:
            try:
                id_value = i["uuid"]
            except KeyError:
                try:
                    id_value = i["name"]
                except KeyError:
                    id_value = None

        return str(id_value) if id_value is not None else None

    def fetch_data(
        self, endpoint: str, expanded: bool = True, limit: int = 1000
    ) -> dict[str, Any] | None:
        """
        Fetches all data from a given endpoint (supports paging)

        Parameters:
            endpoint (str): Endpoint to collect data from
            expanded (bool): Download objects in expanded form
            limit (int): Maximum number of items obtained via single call (<=1000)

        Returns:
            dict: Merged dict with all objects
        """

        endpoint_url = f"{endpoint}?expanded={expanded}&limit={limit}"
        output = super().fetch_data(endpoint_url)

        if not output:
            return None

        if "paging" in output and "next" in output["paging"]:
            data = {"paging": output["paging"]}
            while True:
                next_url_params = data["paging"]["next"][0].split("?")[1]
                next_data = super().fetch_data(endpoint + "?" + next_url_params)
                if next_data is None:
                    break
                data = next_data
                output["items"].extend(data["items"])
                if "next" not in data["paging"]:
                    break

        # Check if returned data structure has domain information
        try:
            output["items"][0]["metadata"]["domain"]["id"]
        # If it doesn't, return data as is
        except KeyError:
            return output

        # If returned data structure has domain information
        # Filter output by the domain
        # Child domains will include objects from parent domain, which we need to exclude
        filtered = {
            "items": [
                x for x in output["items"] if x["metadata"]["domain"]["id"] in endpoint
            ]
        }

        return filtered

    def resolve_domains(
        self, endpoints: list[dict[str, Any]], domains: list[str]
    ) -> list[dict[str, Any]]:
        """
        Replace endpoint containing domain reference '{DOMAIN_UUID}' with one per domain.

        Parameters:
            endpoints (list): List of endpoints
            domains (list): List of domains' UUIDs

        Returns:
            list: Per-domain list of endpoints
        """

        new_endpoints = []
        for endpoint in endpoints:
            # Endpoint is NOT domain specific
            if "{DOMAIN_UUID}" not in endpoint["endpoint"]:
                new_endpoints.append(copy.deepcopy(endpoint))
                continue

            # Endpoint is domain specific
            base_endpoint = endpoint["endpoint"]
            for domain in domains:
                endpoint["endpoint"] = base_endpoint.replace("{DOMAIN_UUID}", domain)
                new_endpoints.append(copy.deepcopy(endpoint))

        return new_endpoints
