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

from nac_collector.constants import ISE_ERS_PAGE_SIZE
from nac_collector.controller.base import CiscoClientController

logger = logging.getLogger("main")


class CiscoClientISE(CiscoClientController):
    """
    This class inherits from the abstract class CiscoClientController. It's used for authenticating
    with the Cisco ISE API and retrieving data from various endpoints.
    Authentication is username/password based and a session is created upon successful
    authentication for subsequent requests.
    """

    ISE_AUTH_ENDPOINTS = [
        "/admin/API/NetworkAccessConfig/ERS",
        "/admin/API/apiService/get",
    ]
    SOLUTION = "ise"

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

    def reconstruct_url_with_base(self, href: str) -> str:
        """
        Reconstruct URL using the configured base_url instead of the href's host.

        This is critical for proxy scenarios where ISE returns internal IP addresses
        in href values, but the proxy can only reach the external domain name.

        Parameters:
            href (str): The href URL from ISE API response (may contain internal IP)

        Returns:
            str: Reconstructed URL using self.base_url with the path and query from href

        Example:
            href: "https://10.247.67.80/ers/config/sgt?size=20&page=3"
            base_url: "https://ise.company.com"
            result: "https://ise.company.com/ers/config/sgt?size=20&page=3"
        """
        from urllib.parse import urlparse

        # Parse the href to extract path and query
        parsed_href = urlparse(href)

        # Reconstruct using our base_url (which is accessible via proxy)
        # Extract path and query string from href
        path_and_query = parsed_href.path
        if parsed_href.query:
            path_and_query += f"?{parsed_href.query}"

        reconstructed_url = f"{self.base_url}{path_and_query}"

        # Log the transformation for debugging proxy issues
        if parsed_href.netloc and parsed_href.netloc not in self.base_url:
            logger.debug(
                "Reconstructed URL: %s (original href had different host: %s)",
                reconstructed_url,
                parsed_href.netloc,
            )

        return reconstructed_url

    def authenticate(self) -> bool:
        """
        Perform basic authentication.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """

        for api in self.ISE_AUTH_ENDPOINTS:
            auth_url = f"{self.base_url}{api}"

            # Set headers based on auth_url
            # If it's ERS API, then set up content-type and accept as application/xml
            if "API/NetworkAccessConfig/ERS" in auth_url:
                headers = {
                    "Content-Type": "application/xml",
                    "Accept": "application/xml",
                }
            else:
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }

            response = httpx.get(
                auth_url,
                auth=(self.username, self.password),
                headers=headers,
                verify=self.ssl_verify,
                timeout=self.timeout,
            )

            if response and response.status_code == 200:
                logger.info("Authentication Successful for URL: %s", auth_url)
                # Create a client after successful authentication
                self.client = httpx.Client(
                    auth=(self.username, self.password),
                    verify=self.ssl_verify,
                    timeout=self.timeout,
                )
                self.client.headers.update(headers)
                self.client.headers.update(
                    {"Content-Type": "application/json", "Accept": "application/json"}
                )
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
            endpoint_dict[endpoint["name"]].append(
                {"data": {}, "endpoint": endpoint["endpoint"]}
            )

        # License API returns a list of dictionaries
        elif isinstance(data, list):
            endpoint_dict[endpoint["name"]].append(
                {"data": data, "endpoint": endpoint["endpoint"]}
            )

        elif data and data.get("response"):
            response_items = data.get("response")
            if response_items:
                for i in response_items:
                    endpoint_dict[endpoint["name"]].append(
                        {
                            "data": i,
                            "endpoint": endpoint["endpoint"]
                            + "/"
                            + self.get_id_value(i),
                        }
                    )

        # Pagination for ERS API results
        elif data.get("SearchResult"):
            ers_data = self.process_ers_api_results(data)

            for i in ers_data:
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": i,
                        "endpoint": endpoint["endpoint"] + "/" + self.get_id_value(i),
                    }
                )

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
                logger.info("Processing endpoint: %s", endpoint["name"])

                endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)

                # Optimize ERS API calls by adding page size parameter
                # ERS endpoints contain '/ers/config/' in their path
                endpoint_url = endpoint["endpoint"]
                if "/ers/config/" in endpoint_url:
                    # Add size parameter to reduce number of pagination calls
                    # Check if URL already has query parameters
                    separator = "&" if "?" in endpoint_url else "?"
                    endpoint_url = f"{endpoint_url}{separator}size={ISE_ERS_PAGE_SIZE}"
                    logger.debug(
                        "ERS endpoint detected, adding pagination size parameter: %s",
                        endpoint_url,
                    )

                data = self.fetch_data(endpoint_url)

                # Process the endpoint data and get the updated dictionary
                endpoint_dict = self.process_endpoint_data(
                    endpoint, endpoint_dict, data
                )

                if endpoint.get("children"):
                    # Create empty list of parent_endpoint_ids
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
                            endpoint["endpoint"]
                            + "/%v"
                            + children_endpoint["endpoint"],
                        )

                        # Iterate over the parent endpoint ids
                        for id_ in parent_endpoint_ids:
                            children_endpoint_dict = (
                                CiscoClientController.create_endpoint_dict(
                                    children_endpoint
                                )
                            )

                            # Replace '%v' in the endpoint with the id
                            children_joined_endpoint = (
                                endpoint["endpoint"]
                                + "/"
                                + id_
                                + children_endpoint["endpoint"]
                            )

                            data = self.fetch_data(children_joined_endpoint)

                            # Process the children endpoint data and get the updated dictionary
                            children_endpoint_dict = self.process_endpoint_data(
                                children_endpoint, children_endpoint_dict, data
                            )

                            for index, value in enumerate(
                                endpoint_dict[endpoint["name"]]
                            ):
                                if value.get("data").get("id") == id_:
                                    endpoint_dict[endpoint["name"]][index].setdefault(
                                        "children", {}
                                    )[
                                        children_endpoint["name"]
                                    ] = children_endpoint_dict[
                                        children_endpoint["name"]
                                    ]

                # Save results to dictionary
                final_dict.update(endpoint_dict)
        return final_dict

    def process_ers_api_results(self, data: dict[str, Any]) -> list[Any]:
        """
        Process ERS API results and handle pagination.

        Parameters:
            data (dict): The data received from the ERS API.

        Returns:
            ers_data (list): The processed data.
        """
        # Pagination for ERS API results
        paginated_data = data["SearchResult"]["resources"]
        # Loop through all pages until there are no more pages
        while data["SearchResult"].get("nextPage"):
            # Reconstruct URL using base_url to support proxy scenarios
            # ISE may return internal IP addresses in href that aren't reachable via proxy
            href = data["SearchResult"]["nextPage"]["href"]
            url = self.reconstruct_url_with_base(href)
            # Send a GET request to the URL
            response = self.get_request(url)
            if response is None:
                break
            # Get the JSON content of the response
            data = response.json()
            paginated_data.extend(data["SearchResult"]["resources"])

        # For ERS API retrieve details querying all elements from paginated_data
        ers_data = []
        for element in paginated_data:
            # Reconstruct URL using base_url to support proxy scenarios
            # ISE may return internal IP addresses in href that aren't reachable via proxy
            href = element["link"]["href"]
            url = self.reconstruct_url_with_base(href)
            response = self.get_request(url)
            if response is None:
                continue
            # Get the JSON content of the response
            data = response.json()

            for _, value in data.items():
                ers_data.append(value)

        return ers_data

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
            return str(i["id"])
        except KeyError:
            try:
                return str(i["rule"]["id"])
            except KeyError:
                try:
                    return str(i["name"])
                except KeyError:
                    return None
