from abc import ABC, abstractmethod
import requests
import logging
import urllib3
from ruamel.yaml import YAML
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("main")


class CiscoClient(ABC):
    def __init__(self, username, password, base_url, auth_type, ssl_verify=False):
        """
        Abstract Base Class for a CiscoClient instance.
        This class should be subclassed and not instantiated directly.

        Parameters:
            username (str): The username for authentication.
            password (str): The password for authentication.
            base_url (str): The base URL of the API endpoint.
            auth_type (str): The type of authentication
        """
        self.username = username
        self.password = password
        self.base_url = base_url
        self.session = None
        self.ssl_verify = ssl_verify
        self.auth_type = auth_type
        # Create an instance of the YAML class
        self.yaml = YAML(typ="safe", pure=True)

    @abstractmethod
    def authenticate(self):
        """
        Authenticate using the specified authentication type.
        """
        pass

    @abstractmethod
    def get_from_endpoints(self, endpoints_yaml_file, max_retries, retry_after, timeout):
        pass

    def get_request(self, url, max_retries, retry_after, timeout=10):
        """
        Send a GET request to a specific URL and handle a 429 status code.

        Parameters:
            url (str): The URL to send the GET request to.
            max_retries (int): The maximum number of times to retry the request if the status code is 429.
            retry_after (int): The number of seconds to wait before retrying the request if the status code is 429.
            timeout (int): The number of seconds to wait for the server to send data before giving up.

        Returns:
            response (aiohttp.ClientResponse): The response from the GET request.
        """
        for _ in range(max_retries):
            try:
                # Send a GET request to the URL
                response = self.session.get(url, verify=self.ssl_verify, timeout=timeout)
            except requests.exceptions.Timeout:
                logger.error(f"GET {url} timed out after {timeout} seconds.")
                continue

            if response.status_code == 429:
                # If the status code is 429 (Too Many Requests), wait for a certain amount of time before retrying
                retry_after = int(
                    response.headers.get("Retry-After", retry_after)
                )  # Default to retry_after if 'Retry-After' header is not present
                logger.info(f"GET {url} rate limited. Retrying in {retry_after} seconds.")
                time.sleep(retry_after)
            else:
                # If the status code is not 429, return the response
                return response

        # If the status code is 429 after max_retries attempts, return the last response
        return response
