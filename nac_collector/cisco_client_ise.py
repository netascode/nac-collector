import logging
import requests
import urllib3
import json

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("main")


class CiscoClientISE(CiscoClient):
    ISE_AUTH_ENDPOINTS = [
        "/admin/API/NetworkAccessConfig/ERS",
        "/admin/API/apiService/get",
    ]
    SOLUTION = "ise"

    def __init__(self, username, password, base_url, ssl_verify):
        super().__init__(username, password, base_url, ssl_verify)

    def authenticate(self):
        """
        Perform basic authentication.
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

            response = requests.get(
                auth_url,
                auth=(self.username, self.password),
                headers=headers,
                verify=self.ssl_verify,
            )

            if response and response.status_code == 200:
                logger.info("Authentication Successful for URL: %s", auth_url)
                # Create a session after successful authentication
                self.session = requests.Session()
                self.session.auth = (self.username, self.password)
                self.session.headers.update(headers)
            else:
                logger.error(
                    "Authentication failed with status code: %s",
                    response.status_code,
                )

            self.session = requests.Session()
            self.session.auth = (self.username, self.password)
            self.session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

    def get_from_endpoints(self, endpoints_yaml_file, max_retries, retry_after, timeout):
        """
        Retrieve data from a list of endpoints specified in a YAML file and
        run GET requests to download data from controller.

        Parameters:
            endpoints_yaml_file (str): The name of the YAML file containing the endpoints.
            max_retries (int): The maximum number of times to retry the request if the status code is 429.
            retry_after (int): The number of seconds to wait before retrying the request if the status code is 429.
            timeout (int): The number of seconds to wait for the server to send data before giving up.

        Returns:
            None
        """
        # Load endpoints from the YAML file
        logger.info("Loading endpoints from %s", endpoints_yaml_file)
        with open(endpoints_yaml_file, "r") as f:
            endpoints = self.yaml.load(f)

        # Initialize an empty dictionary
        final_dict = {}

        # Initialize an empty list for endpoint with children (%v in endpoint['endpoint'])
        endpoints_with_children = []

        # Iterate through the endpoints
        for endpoint in endpoints:
            if all(x not in endpoint["endpoint"] for x in ["%v", "%i"]):
                endpoint_dict = {
                    endpoint["name"]: {
                        "items": [],
                        "children": {},
                        "endpoint": endpoint["endpoint"],
                    }
                }

                response = self.get_request(
                    self.base_url + endpoint["endpoint"],
                    max_retries,
                    retry_after,
                    timeout,
                )

                # Check if the request was successful
                if response.status_code == 200:
                    # Get the JSON content of the response
                    data = response.json()

                    if isinstance(data, list):
                        endpoint_dict[endpoint["name"]]["items"] = data
                    elif data.get("response"):
                        if isinstance(data.get("response"), list):
                            endpoint_dict[endpoint["name"]]["items"] = data["response"]
                    elif data.get("SearchResult"):
                        paginated_data = data["SearchResult"]["resources"]

                        # Loop through all pages until there are no more pages
                        while data["SearchResult"].get("nextPage"):
                            url = data["SearchResult"]["nextPage"]["href"]

                            # Send a GET request to the URL
                            response = self.get_request(url, max_retries, retry_after, timeout)

                            if response.status_code == 200:
                                # Get the JSON content of the response
                                data = response.json()

                            paginated_data.extend(data["SearchResult"]["resources"])

                        # For ERS API retrieve details querying all elements from paginated_data
                        ers_data = []
                        for element in paginated_data:
                            url = element["link"]["href"]
                            response = self.get_request(url, max_retries, retry_after, timeout)

                            if response.status_code == 200:
                                # Get the JSON content of the response
                                data = response.json()

                                for key, value in data.items():
                                    ers_data.append(value)

                        endpoint_dict[endpoint["name"]]["items"] = ers_data
                    elif data.get("response") == []:
                        endpoint_dict[endpoint["name"]]["items"] = data["response"]
                    else:
                        endpoint_dict[endpoint["name"]]["items"] = data

                    # Save results to dictionary
                    final_dict.update(endpoint_dict)

                    logger.info(f"GET {endpoint} succeeded with status code {response.status_code}")
                else:
                    logger.error(f"GET {endpoint} failed with status code {response.status_code}")

            elif "%v" in endpoint["endpoint"]:
                endpoints_with_children.append(endpoint)

        # Iterate over the items in the final_dict dictionary
        for key in list(final_dict.keys()):
            # Add the current key to the 'name' field
            final_dict[key]["name"] = key

            # Extract the endpoint value
            endpoint = final_dict[key].pop("endpoint")

            # Create a new dictionary with the endpoint as the key
            final_dict[endpoint] = final_dict.pop(key)

        # Iterate through the endpoints with children
        for endpoint in endpoints_with_children:
            parent_endpoint = endpoint["endpoint"].split("/%v")[0]

            # Check if final_dict[parent_endpoint] exists
            if parent_endpoint in final_dict:
                # Initialize an empty list for parent endpoint ids
                parent_endpoint_ids = []

                # Iterate over the items in final_dict[parent_endpoint]['items']
                for item in final_dict[parent_endpoint]["items"]:
                    # Add the item's id to the list
                    parent_endpoint_ids.append(item["id"])

                # Iterate over the parent endpoint ids
                for id_ in parent_endpoint_ids:
                    # Replace '%v' in the endpoint with the id
                    new_endpoint = endpoint["endpoint"].replace("%v", str(id_))

                    # Send a GET request to the new endpoint
                    response = self.get_request(self.base_url + new_endpoint, max_retries, retry_after, timeout)

                    if response.status_code == 200:
                        # Get the JSON content of the response
                        data = response.json()

                        if isinstance(data.get("response"), list):
                            # Get the children endpoint name (e.g., 'authentication', 'authorization')
                            children_endpoint_name = endpoint["endpoint"].split("/%v/")[1]

                            print(children_endpoint_name)
                            # Check if the children endpoint name already exists in the 'children' dictionary
                            if children_endpoint_name not in final_dict[parent_endpoint]["children"]:
                                # If not, create a new list for it
                                final_dict[parent_endpoint]["children"][children_endpoint_name] = []

                            # Add the data to the list
                            final_dict[parent_endpoint]["children"][children_endpoint_name].extend(data["response"])

                        logger.info(f"GET {endpoint} succeeded with status code {response.status_code}")
                    else:
                        logger.error(f"GET {endpoint} failed with status code {response.status_code}")

        # Write the final dictionary to a JSON file
        with open(f"{self.SOLUTION}.json", "w") as f:
            json.dump(final_dict, f, indent=4)
            logger.info("GET requests finished")
