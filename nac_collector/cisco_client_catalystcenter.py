import logging

import click
import requests
import urllib3

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("main")

# Suppress urllib3 warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)


class CiscoClientCATALYSTCENTER(CiscoClient):
    """
    This class inherits from the abstract class CiscoClient. It's used for authenticating
    with the Cisco Catalyst Center API and retrieving data from various endpoints.
    Authentication is username/password based and a session is created upon successful
    authentication for subsequent requests.
    """

    DNAC_AUTH_ENDPOINT = "/dna/system/api/v1/auth/token"
    SOLUTION = "catalystcenter"

    "Used for mapping credentials to the correct endpoint"
    mappings = {
        "credentials_snmpv3": "snmpV3",
        "credentials_snmpv2_read": "snmpV2cRead",
        "credentials_snmpv2_write": "snmpV2cWrite",
        "credentials_cli": "cliCredential",
        "credentials_https_read": "httpsRead",
        "credentials_https_write": "httpsWrite",
    }

    def __init__(
        self,
        username,
        password,
        base_url,
        max_retries,
        retry_after,
        timeout,
        ssl_verify,
    ):
        super().__init__(
            username, password, base_url, max_retries, retry_after, timeout, ssl_verify
        )

    def authenticate(self):
        """
        Perform token-based authentication.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """

        auth_url = f"{self.base_url}{self.DNAC_AUTH_ENDPOINT}"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": "application/json",
        }
        response = requests.post(
            auth_url,
            auth=(self.username, self.password),
            headers=headers,
            verify=self.ssl_verify,
            timeout=self.timeout,
        )

        if response and response.status_code == 200:
            logger.info("Authentication Successful for URL: %s", auth_url)

            token = response.json()["Token"]

            # Create a session after successful authentication
            self.session = requests.Session()
            self.session.headers.update(
                {
                    "Content-Type": "application/json",
                    "x-auth-token": token,
                }
            )
            return True

        logger.error(
            "Authentication failed with status code: %s",
            response.status_code,
        )
        return False

    def process_endpoint_data(self, endpoint, endpoint_dict, data):
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
        elif isinstance(data.get("response"), dict):
            for k, v in data.get("response").items():
                if self.mappings[endpoint["name"]] == k:
                    for i in v:
                        endpoint_dict[endpoint["name"]].append(
                            {
                                "data": i,
                                "endpoint": endpoint["endpoint"]
                                + "/"
                                + self.get_id_value(i),
                            }
                        )
        elif data.get("response"):
            for i in data.get("response"):
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": i,
                        "endpoint": endpoint["endpoint"] + "/" + self.get_id_value(i),
                    }
                )

        return endpoint_dict  # Return the processed endpoint dictionary

    def get_from_endpoints(self, endpoints_yaml_file):
        """
        Retrieve data from a list of endpoints specified in a YAML file and
        run GET requests to download data from controller.

        Parameters:
            endpoints_yaml_file (str): The name of the YAML file containing the endpoints.

        Returns:
            dict: The final dictionary containing the data retrieved from the endpoints.
        """

        # Load endpoints from the YAML file
        logger.info("Loading endpoints from %s", endpoints_yaml_file)
        with open(endpoints_yaml_file, "r", encoding="utf-8") as f:
            endpoints = self.yaml.load(f)

        # Initialize an empty dictionary
        final_dict = {}

        # Iterate over all endpoints
        with click.progressbar(endpoints, label="Processing endpoints") as endpoint_bar:
            for endpoint in endpoint_bar:
                logger.info("Processing endpoint: %s", endpoint["name"])

                endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)

                data = self.fetch_data(endpoint["endpoint"])

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
                            children_endpoint_dict = CiscoClient.create_endpoint_dict(
                                children_endpoint
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

    @staticmethod
    def get_id_value(i):
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
                id_value = i["name"]
            except KeyError:
                id_value = None

        return id_value
