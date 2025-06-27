import logging

import copy
import json
import click
import requests
import urllib3

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("main")

# Suppress urllib3 warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)


class CiscoClientMERAKI(CiscoClient):
    """
    This class inherits from the abstract class CiscoClient. It's used for authenticating
    with the Cisco MERAKI API and retrieving data from various endpoints.
    This is a single step authentication.
     - API Token / Key is used for all queries
    """

    SOLUTION = "meraki"

    def __init__(
        self,
        username,
        password,
        api_key,
        base_url,
        max_retries,
        retry_after,
        timeout,
        ssl_verify,
    ):
        super().__init__(
            username,
            password,
            api_key,
            base_url,
            max_retries,
            retry_after,
            timeout,
            ssl_verify,
        )
        self.x_auth_refresh_token = None
        self.domains = []

    def authenticate(self):
        """
        Perform basic authentication.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """

        if not self.api_key:
            logger.error("API key is required for authentication.")
            return False

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "nac-collector",
            }
        )
        logger.info("Authentication successful with API key.")
        return True

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

        elif isinstance(data, list):
            for i in data:
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": i,
                        "endpoint": endpoint["endpoint"] + "/" + self.get_id_value(i),
                    }
                )

        elif data.get("items", None):
            for i in data.get("items"):
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": i,
                        "endpoint": f'{endpoint["endpoint"]}/{self.get_id_value(i)}',
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

        # Recreate endpoints per-domain
        endpoints = self.resolve_domains(endpoints, self.domains)

        # Iterate over all endpoints
        with click.progressbar(endpoints, label="Processing endpoints") as endpoint_bar:
            for endpoint in endpoint_bar:
                logger.info("Processing endpoint: %s", endpoint)

                endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)

                data = self.fetch_data(endpoint["endpoint"])

                endpoint_dict = self.process_endpoint_data(
                    endpoint, endpoint_dict, data
                )

                if endpoint.get("children"):
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
                                    logger.info(
                                        "Updated endpoint_dict: %s",
                                        json.dumps(
                                            endpoint_dict, sort_keys=True, indent=4
                                        ),
                                    )

                # Save results to dictionary
                # Due to domain expansion, it may happen that same endpoint["name"] will occur multiple times
                if endpoint["name"] not in final_dict:
                    final_dict.update(endpoint_dict)
                else:
                    final_dict[endpoint["name"]].extend(endpoint_dict[endpoint["name"]])

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
                id_value = i["uuid"]
            except KeyError:
                try:
                    id_value = i["name"]
                except KeyError:
                    id_value = None

        return id_value

    def resolve_domains(self, endpoints: list, domains: list):
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
