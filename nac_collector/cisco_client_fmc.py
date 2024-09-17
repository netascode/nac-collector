import logging

import copy
import click
import requests
import urllib3
import json

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("main")

# Suppress urllib3 warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)


class CiscoClientFMC(CiscoClient):
    """
    This class inherits from the abstract class CiscoClient. It's used for authenticating
    with the Cisco FMC API and retrieving data from various endpoints.
    There is two stage authentication.
     - username/password is used to obtain authentication token
     - token is used to authenticate subsequent queries
    """

    FMC_AUTH_ENDPOINTS = [
        "/api/fmc_platform/v1/auth/generatetoken"
    ]
    SOLUTION = "fmc"

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
        self.X_auth_refresh_token = None

    def authenticate(self):
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

            response = requests.post(
                auth_url,
                auth=(self.username, self.password),
                headers=headers,
                verify=self.ssl_verify,
                timeout=self.timeout,
            )

            if response and response.status_code == 204:
                logger.info("Authentication Successful for URL: %s", auth_url)
                # Create a session after successful authentication
                self.session = requests.Session()
                self.session.headers.update(
                    {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-auth-access-token": response.headers.get("X-auth-access-token"),
                    }
                )
                self.X_auth_refresh_token = response.headers.get("X-auth-refresh-token")

                # Save a list of UUIDs of all available domains
                self.domains = [x["uuid"] for x in json.loads(response.headers.get("DOMAINS"))]
                return True

            logger.error(
                "Authentication failed with status code: %s",
                response.status_code,
            )
            return False

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

        # Initialize an empty list for endpoint with children (%v in endpoint['endpoint'])
        children_endpoints = []

        # Iterate over all endpoints
        with click.progressbar(endpoints, label="Processing endpoints") as endpoint_bar:
            for endpoint in endpoint_bar:
                logger.info("Processing endpoint: %s", endpoint)

                if all(x not in endpoint["endpoint"] for x in ["%v", "%i"]):
                    endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)

                    data = self.fetch_data(endpoint["endpoint"])

                    if data is None:
                        endpoint_dict[endpoint["name"]].append(
                            {"data": {}, "endpoint": endpoint["endpoint"]}
                        )

                    elif isinstance(data, list):
                        endpoint_dict[endpoint["name"]].append(
                            {"data": data, "endpoint": endpoint["endpoint"]}
                        )

                    elif "items" in data and data.get("items"):
                        for i in data.get("items"):
                            endpoint_dict[endpoint["name"]].append(
                                {
                                    "data": i,
                                    "endpoint": endpoint["endpoint"]
                                    + "/"
                                    + str(self.get_id_value(i)),
                                }
                            )

                    # Save results to dictionary
                    # Due to domain expansion, it may happen that same endpoint["name"] will occur multiple times
                    if endpoint["name"] not in final_dict:
                        final_dict.update(endpoint_dict)
                    else:
                        final_dict[endpoint["name"]].extend(endpoint_dict[endpoint["name"]])

                elif "%v" in endpoint["endpoint"]:
                    children_endpoints.append(endpoint)

        # Iterate over all children endpoints
        with click.progressbar(
            children_endpoints, label="Processing children endpoints"
        ) as children_endpoint_bar:
            for endpoint in children_endpoint_bar:
                logger.info("Processing children endpoint: %s", endpoint)

                parent_endpoint = endpoint["endpoint"].split("/%v")[0]

                # Iterate over the dictionary
                for _, value in final_dict.items():
                    index = 0
                    # Iterate over the items in final_dict[parent_endpoint]
                    for item in value:
                        if parent_endpoint == "/".join(
                            item.get("endpoint").split("/")[:-1]
                        ):
                            # Initialize an empty list for parent endpoint ids
                            parent_endpoint_ids = []

                            # Add the item's id to the list
                            try:
                                parent_endpoint_ids.append(item["data"]["id"])
                            except KeyError:
                                continue
                            # Iterate over the parent endpoint ids
                            for id_ in parent_endpoint_ids:
                                # Replace '%v' in the endpoint with the id
                                new_endpoint = endpoint["endpoint"].replace(
                                    "%v", str(id_)
                                )

                                data = self.fetch_data(new_endpoint)

                                # Get the JSON content of the response
                                if data is None:
                                    continue
                                if ( isinstance(data, list) or isinstance(data, dict) ) and len(data) == 0:
                                    continue

                                elif data.get("items"):
                                    for i in data.get("items"):
                                        # Check if the key exists
                                        if "children" not in value[index]:
                                            # If the key doesn't exist, create it and initialize it as an empty list
                                            value[index]["children"] = {}
                                        # Check if the key exists
                                        if (
                                            endpoint["name"]
                                            not in value[index]["children"]
                                        ):
                                            # If the key doesn't exist, create it and initialize it as an empty list
                                            value[index]["children"][
                                                endpoint["name"]
                                            ] = []

                                        value[index]["children"][
                                            endpoint["name"]
                                        ].append(
                                            {
                                                "data": i,
                                                "endpoint": new_endpoint
                                                + "/"
                                                + self.get_id_value(i),
                                            }
                                        )

                        index += 1
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

    def fetch_data(self, endpoint: str, expanded: bool = True, limit: int = 1000):
        """
        Fetches all data from a given endpoint (supports paging)

        Parameters:
            endpoint (str): Endpoint to collect data from
            expanded (bool): Download objects in expanded form
            limit (int): Maximum number of items obtained via single call (<=1000ś)

        Returns:
            dict: Merged dict with all objects
        """

        endpoint_url = f"{endpoint}?expanded={expanded}&limit={limit}"
        output = super().fetch_data(endpoint_url)

        if not output:
            return []

        if "paging" in output and "next" in output["paging"]:
            data = {
                "paging": output["paging"]
            }
            while True:
                next_url_params = data["paging"]["next"][0].split('?')[1]
                data = super().fetch_data(endpoint + "?" + next_url_params)
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
        filtered = {
            "items": [x for x in output["items"] if x["metadata"]["domain"]["id"] in endpoint]
        }

        return filtered

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
