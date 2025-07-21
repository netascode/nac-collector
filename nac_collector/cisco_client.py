from abc import ABC, abstractmethod
import json
import logging
import time

import requests
from ruamel.yaml import YAML
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CiscoClient(ABC):
    """
    Abstract Base Class for a CiscoClient instance.
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
        username,
        password,
        api_key,
        base_url,
        max_retries,
        retry_after,
        timeout,
        ssl_verify=False,
    ):
        self.username = username
        self.password = password
        self.api_key = api_key
        self.base_url = base_url
        self.max_retries = max_retries
        self.retry_after = retry_after
        self.timeout = timeout
        self.ssl_verify = ssl_verify
        self.session = None
        # Create an instance of the YAML class
        self.yaml = YAML(typ="safe", pure=True)
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def authenticate(self):
        """
        Abstract method to authenticate the client using the specified authentication type.

        This method should be implemented by any concrete subclass. The implementation should handle
        the authentication process required for the client to successfully communicate with the API.

        Raises:
            NotImplementedError: If this method is not overridden in a concrete subclass.
        """

    @abstractmethod
    def get_from_endpoints(self, endpoints_yaml_file):
        """
        Abstract method to get data from specified endpoints.

        This method should be implemented by any concrete subclass.

        Parameters:
            endpoints_yaml_file (str): The path to a YAML file containing the endpoints to get data from.

        Returns:
            This method should return the data obtained from the endpoints.

        Raises:
            NotImplementedError: If this method is not overridden in a concrete subclass.
        """

    def get_request(self, url):
        """
        Send a GET request to a specific URL and handle a 429 status code.

        Parameters:
            url (str): The URL to send the GET request to.

        Returns:
            response (requests.Response): The response from the GET request.
        """

        for _ in range(self.max_retries):
            try:
                # Send a GET request to the URL
                response = self.session.get(
                    url, verify=self.ssl_verify, timeout=self.timeout
                )

            except requests.exceptions.Timeout:
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
                response = []
        # If the status code is 429 after max_retries attempts,
        # or if no successful response was received, return the last response
        return response

    def post_request(self, url, data):
        """
        Send a POST request to a specific URL and handle a 429 status code.

        Parameters:
            url (str): The URL to send the POST request to.
            data (dict): The data to send in the body of the POST request.

        Returns:
            response (requests.Response): The response from the GET request.
        """
        for _ in range(self.max_retries):
            try:
                # Send a POST request to the URL
                response = self.session.post(
                    url, data=data, verify=self.ssl_verify, timeout=self.timeout
                )
            except requests.exceptions.Timeout:
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
                    "GET %s returned an unexpected status code: %s",
                    url,
                    response.status_code,
                )

        # If the status code is 429 after max_retries attempts,
        # or if no successful response was received, return the last response
        return response

    def log_response(self, endpoint, response):
        """
        Logs the response from a GET request.

        Parameters:
            endpoint (str): The endpoint the request was sent to.
            response (Response): The response from the request.
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

    def fetch_data(self, endpoint):
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
                return data
            except ValueError:
                self.logger.error(
                    "Failed to decode JSON from response for endpoint: %s", endpoint
                )
                return None
        else:
            self.logger.error("No valid response received for endpoint: %s", endpoint)
            return None

    def write_to_json(self, final_dict, output):
        """
        Writes the final dictionary to a JSON file.

        Parameters:
            final_dict (dict): The final dictionary to write to the file.
            output (str): Filename
        """
        with open(output, "w", encoding="utf-8") as f:
            json.dump(final_dict, f, indent=4)
        self.logger.info("Data written to %s", output)

    @staticmethod
    def create_endpoint_dict(endpoint):
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
