import json
import logging
import time
import zipfile
from abc import ABC, abstractmethod
from typing import Any

import httpx
from ruamel.yaml import YAML


class CiscoClientController(ABC):
    """
    Abstract Base Class for a CiscoClientController instance.
    This class should be subclassed and not instantiated directly.

    Parameters:
        username (str): The username for authentication.
        password (str): The password for authentication.
        base_url (str): The base URL of the API endpoint.
        ssl_verify (bool, optional): Whether to verify SSL certificates for HTTPS requests. Defaults to False.
        max_retries (int): The maximum number of times to retry the request if the status code is 429.
        retry_after (int): The number of seconds to wait before retrying the request if the status code is 429.
        timeout (int): The number of seconds to wait for the server to send data before giving up.
    """

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str,
        max_retries: int,
        retry_after: int,
        timeout: int,
        ssl_verify: bool = False,
    ) -> None:
        self.username = username
        self.password = password
        self.base_url = base_url
        self.max_retries = max_retries
        self.retry_after = retry_after
        self.timeout = timeout
        self.ssl_verify = ssl_verify
        self.client: httpx.Client | None = None
        # Create an instance of the YAML class
        self.yaml = YAML(typ="safe", pure=True)
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Abstract method to authenticate the client using the specified authentication type.

        This method should be implemented by any concrete subclass. The implementation should handle
        the authentication process required for the client to successfully communicate with the API.

        Raises:
            NotImplementedError: If this method is not overridden in a concrete subclass.
        """

    @abstractmethod
    def get_from_endpoints_data(
        self, endpoints_data: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Abstract method to get data from endpoints provided as a data structure.

        This method should be implemented by any concrete subclass.

        Parameters:
            endpoints_data (list[dict[str, Any]]): List of endpoint definitions with name and endpoint keys.

        Returns:
            This method should return the data obtained from the endpoints.

        Raises:
            NotImplementedError: If this method is not overridden in a concrete subclass.
        """

    def get_request(self, url: str) -> httpx.Response | None:
        """
        Send a GET request to a specific URL and handle a 429 status code.

        Parameters:
            url (str): The URL to send the GET request to.

        Returns:
            response (httpx.Response): The response from the GET request.
        """
        response = None
        for _ in range(self.max_retries):
            try:
                # Send a GET request to the URL
                if self.client is None:
                    self.logger.error("Client not initialized")
                    return None
                response = self.client.get(url)

            except httpx.TimeoutException:
                self.logger.error(
                    "GET %s timed out after %s seconds.", url, self.timeout
                )
                continue

            if response.status_code == 429:
                # If the status code is 429 (Too Many Requests), wait for a certain amount of time before retrying
                self.retry_after = int(
                    response.headers.get("Retry-After", self.retry_after)
                )  # Default to retry_after if 'Retry-After' header is not present
                self.logger.info(
                    "GET %s rate limited. Retrying in %s seconds.",
                    url,
                    self.retry_after,
                )
                time.sleep(self.retry_after)

            elif response.status_code == 401:
                self.logger.info("token outdated, getting new")
                self.authenticate()

            elif response.status_code == 200:
                # If the status code is 200 (OK), return the response
                return response
            else:
                # If the status code is neither 429 nor 200, log an error and continue to the next iteration
                self.logger.error(
                    "GET %s returned an unexpected status code: %s",
                    url,
                    response.status_code,
                )
                return None
        # If the status code is 429 after max_retries attempts,
        # or if no successful response was received, return the last response
        return response

    def post_request(self, url: str, data: dict[str, Any]) -> httpx.Response | None:
        """
        Send a POST request to a specific URL and handle a 429 status code.

        Parameters:
            url (str): The URL to send the POST request to.
            data (dict): The data to send in the body of the POST request.

        Returns:
            response (httpx.Response): The response from the POST request.
        """
        for _ in range(self.max_retries):
            try:
                # Send a POST request to the URL
                if self.client is None:
                    self.logger.error("Client not initialized")
                    return None
                response = self.client.post(url, data=data)
            except httpx.TimeoutException:
                self.logger.error(
                    "POST %s timed out after %s seconds.", url, self.timeout
                )
                continue

            if response.status_code == 429:
                # If the status code is 429 (Too Many Requests), wait for a certain amount of time before retrying
                self.retry_after = int(
                    response.headers.get("Retry-After", self.retry_after)
                )  # Default to retry_after if 'Retry-After' header is not present
                self.logger.info(
                    "POST %s rate limited. Retrying in %s seconds.",
                    url,
                    self.retry_after,
                )
                time.sleep(self.retry_after)
            elif 200 <= response.status_code < 300:
                # If the status code is 2XX (success), return the response
                return response
            else:
                # If the status code is neither 429 nor 200, log an error and continue to the next iteration
                self.logger.error(
                    "POST %s returned an unexpected status code: %s",
                    url,
                    response.status_code,
                )

        # If the status code is 429 after max_retries attempts,
        # or if no successful response was received, return the last response
        return response

    def log_response(self, endpoint: str, response: httpx.Response) -> None:
        """
        Logs the response from a GET request.

        Parameters:
            endpoint (str): The endpoint the request was sent to.
            response (httpx.Response): The response from the request.
        """
        if response.status_code == 200:
            self.logger.info(
                "GET %s succeeded with status code %s",
                endpoint,
                response.status_code,
            )
        else:
            self.logger.error(
                "GET %s failed with status code %s",
                endpoint,
                response.status_code,
            )

    def fetch_data_pagination(self, endpoint: str) -> dict[str, Any] | list[Any] | None:
        """
        Fetch all data from a specified endpoint, handling pagination via the "offset" parameter.

        Parameters:
            endpoint (str): Endpoint URL.

        Returns:
            data (dict): The combined JSON content of all responses or None if an error occurred.
        """
        offset = 1  # Start with an offset of 1
        limit = 500  # The hidden limit per request
        all_responses = []  # To collect all response data

        while True:
            # Append the offset to the endpoint URL as a query parameter
            connector = "?" if "?" not in endpoint else "&"
            paginated_endpoint = f"{endpoint}{connector}offset={offset}"

            # Make the request to the given endpoint
            response = self.get_request(self.base_url + paginated_endpoint)
            if not response:
                self.logger.error(
                    "No valid response received for endpoint: %s", paginated_endpoint
                )
                return None

            try:
                # Get the JSON content of the response
                response_data = response.json()
                in_response = False
                if "response" in response_data:
                    current_response = response_data.get("response", [])
                    in_response = True
                else:
                    current_response = response_data

                # Log and collect the current batch of data
                self.logger.info(
                    "GET %s succeeded with status code %s, fetched %d items",
                    paginated_endpoint,
                    response.status_code,
                    len(current_response),
                )
                current_response = (
                    current_response
                    if type(current_response) is list
                    else [current_response]
                )
                all_responses.extend(current_response)

                # Check if the current response has fewer items than the limit, meaning no more data
                if len(current_response) < limit:
                    break

                # Increment the offset for the next request
                offset += limit
            except ValueError:
                self.logger.error(
                    "Failed to decode JSON from response for endpoint: %s",
                    paginated_endpoint,
                )
                return None

        # Combine all the collected data into the desired format
        data = {"response": all_responses} if in_response else all_responses
        return data

    def fetch_data(self, endpoint: str) -> dict[str, Any] | list[Any] | None:
        """
        Fetch data from a specified endpoint.

        Parameters:
            endpoint (str): Endpoint URL.

        Returns:
            data (dict): The JSON content of the response or None if an error occurred.
        """
        # Make the request to the given endpoint
        response = self.get_request(self.base_url + endpoint)
        if response:
            try:
                # Get the JSON content of the response
                data = response.json()
                self.logger.info(
                    "GET %s succeeded with status code %s",
                    endpoint,
                    response.status_code,
                )
                return (
                    data if (isinstance(data, dict) or isinstance(data, list)) else None
                )
            except ValueError:
                self.logger.error(
                    "Failed to decode JSON from response for endpoint: %s", endpoint
                )
                return None
        else:
            self.logger.error("No valid response received for endpoint: %s", endpoint)
            return None

    def write_to_archive(
        self, final_dict: dict[str, Any], output: str, technology: str
    ) -> None:
        """
        Writes the final dictionary to a ZIP archive containing a JSON file named after the technology.

        Parameters:
            final_dict (dict): The final dictionary to write to the archive.
            output (str): ZIP archive filename
            technology (str): Technology name for the JSON file inside the archive
        """
        json_filename = f"{technology}.json"

        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zip_file:
            json_content = json.dumps(final_dict, indent=4)
            zip_file.writestr(json_filename, json_content)

        self.logger.info("Data written to %s (containing %s)", output, json_filename)

    @staticmethod
    def create_endpoint_dict(endpoint: dict[str, str]) -> dict[str, list[Any]]:
        """
        Creates a dictionary for a given endpoint.

        The dictionary contains the endpoint's name as the key, and a dictionary as the value.
        The value dictionary contains "items" and "children" as empty lists and dictionaries,
        respectively, and "endpoint" as the endpoint's endpoint.

        Parameters:
            endpoint (dict): The endpoint to create a dictionary for. It should contain "name"
                and "endpoint" keys.

        Returns:
            dict: A dictionary with the endpoint's name as the key and a empty list as the value.
        """
        return {endpoint["name"]: []}
