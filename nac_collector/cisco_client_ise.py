import logging
import requests
import urllib3

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("main")


class CiscoClientISE(CiscoClient):
    """
    This class inherits from the abstract class CiscoClient. It's used for authenticating
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
        username,
        password,
        base_url,
        max_retries,
        retry_after,
        timeout,
        ssl_verify,
    ):
        super().__init__(username, password, base_url, max_retries, retry_after, timeout, ssl_verify)

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
                timeout=self.timeout,
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

                endpoint_dict[endpoint["name"]]["endpoint"] = endpoint["endpoint"]
                response = self.get_request(self.base_url + endpoint["endpoint"])

                # Get the JSON content of the response
                data = response.json()
                # License API returns a list of dictionaries
                if isinstance(data, list):
                    endpoint_dict[endpoint["name"]]["items"] = data
                elif data.get("response"):
                    endpoint_dict[endpoint["name"]]["items"] = data["response"]
                # Pagination for ERS API results
                elif data.get("SearchResult"):
                    ers_data = self.process_ers_api_results(data)
                    endpoint_dict[endpoint["name"]]["items"] = ers_data
                # Check if response is empty list
                elif data.get("response") == []:
                    endpoint_dict[endpoint["name"]]["items"] = data["response"]

                # Save results to dictionary
                final_dict.update(endpoint_dict)

                self.log_response(endpoint["endpoint"], response)

            elif "%v" in endpoint["endpoint"]:
                endpoints_with_children.append(endpoint)

        # Iterate through the endpoints with children
        for endpoint in endpoints_with_children:
            parent_endpoint = endpoint["endpoint"].split("/%v")[0]

            # Iterate over the dictionary
            for key, value in final_dict.items():
                if value.get("endpoint") == parent_endpoint:
                    # Initialize an empty list for parent endpoint ids
                    parent_endpoint_ids = []

                    # Iterate over the items in final_dict[parent_endpoint]['items']
                    for item in final_dict.get(key, {}).get("items", []):
                        # Add the item's id to the list
                        parent_endpoint_ids.append(item["id"])

                    # Iterate over the parent endpoint ids
                    for id_ in parent_endpoint_ids:
                        # Replace '%v' in the endpoint with the id
                        new_endpoint = endpoint["endpoint"].replace("%v", str(id_))

                        # Send a GET request to the new endpoint
                        response = self.get_request(self.base_url + new_endpoint)

                        # Get the JSON content of the response
                        data = response.json()

                        if isinstance(data.get("response"), list):
                            # Check if the children endpoint name already exists in the 'children' dictionary
                            if endpoint["name"] not in value["children"]:
                                # If not, create a new list for it
                                value["children"][endpoint["name"]] = {
                                    "items": [],
                                    "children": {},
                                    "endpoint": endpoint["endpoint"],
                                }

                                # Add the data to the list
                                value["children"][endpoint["name"]]["items"].extend(data["response"])

                        self.log_response(new_endpoint, response)

        return final_dict

    def process_ers_api_results(self, data):
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
            url = data["SearchResult"]["nextPage"]["href"]
            # Send a GET request to the URL
            response = self.get_request(url)
            # Get the JSON content of the response
            data = response.json()
            paginated_data.extend(data["SearchResult"]["resources"])

        # For ERS API retrieve details querying all elements from paginated_data
        ers_data = []
        for element in paginated_data:
            url = element["link"]["href"]
            response = self.get_request(url)
            # Get the JSON content of the response
            data = response.json()

            for _, value in data.items():
                ers_data.append(value)

        return ers_data
