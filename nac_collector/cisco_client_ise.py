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
                self.session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
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

        # Initialize an empty list for endpoint with children (%v in endpoint['endpoint'])
        children_endpoints = []

        # Iterate through the endpoints
        for endpoint in endpoints:
            if all(x not in endpoint["endpoint"] for x in ["%v", "%i"]):
                endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)

                #                endpoint_dict[endpoint["name"]]["endpoint"] = endpoint["endpoint"]
                response = self.get_request(self.base_url + endpoint["endpoint"])

                # Get the JSON content of the response
                data = response.json()
                # License API returns a list of dictionaries
                if isinstance(data, list):
                    endpoint_dict[endpoint["name"]].append({"data": data, "endpoint": endpoint["endpoint"]})

                elif data.get("response"):
                    for i in data.get("response"):
                        endpoint_dict[endpoint["name"]].append(
                            {
                                "data": i,
                                "endpoint": endpoint["endpoint"] + "/" + self.get_id_value(i),
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
                # Check if response is empty list
                elif data.get("response") == []:
                    endpoint_dict[endpoint["name"]]["items"] = data["response"]

                # Save results to dictionary
                final_dict.update(endpoint_dict)

                self.log_response(endpoint["endpoint"], response)

            elif "%v" in endpoint["endpoint"]:
                children_endpoints.append(endpoint)

        # Iterate through the children endpoints
        for endpoint in children_endpoints:
            parent_endpoint = endpoint["endpoint"].split("/%v")[0]

            # Iterate over the dictionary
            for _, value in final_dict.items():
                index = 0
                # Iterate over the items in final_dict[parent_endpoint]['items']
                for item in value:
                    if parent_endpoint == "/".join(item.get("endpoint").split("/")[:-1]):
                        # Initialize an empty list for parent endpoint ids
                        parent_endpoint_ids = []

                        # Add the item's id to the list
                        parent_endpoint_ids.append(item["data"]["id"])

                        # Iterate over the parent endpoint ids
                        for id_ in parent_endpoint_ids:
                            # Replace '%v' in the endpoint with the id
                            new_endpoint = endpoint["endpoint"].replace("%v", str(id_))
                            # Send a GET request to the new endpoint
                            response = self.get_request(self.base_url + new_endpoint)
                            # Get the JSON content of the response
                            data = response.json()

                            if data.get("response"):
                                for i in data.get("response"):
                                    # Check if the key exists
                                    if "children" not in value[index]:
                                        # If the key doesn't exist, create it and initialize it as an empty list
                                        value[index]["children"] = {}
                                    # Check if the key exists
                                    if endpoint["name"] not in value[index]["children"]:
                                        # If the key doesn't exist, create it and initialize it as an empty list
                                        value[index]["children"][endpoint["name"]] = []

                                    value[index]["children"][endpoint["name"]].append(
                                        {
                                            "data": i,
                                            "endpoint": new_endpoint + "/" + self.get_id_value(i),
                                        }
                                    )
                            self.log_response(new_endpoint, response)

                    index += 1
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

    def get_id_value(self, i):
        """
        Attempts to get the 'id' or 'name' value from a dictionary.

        Args:
            i (dict): The dictionary to get the 'id' or 'name' value from.

        Returns:
            str or None: The 'id' or 'name' value if it exists, None otherwise.
        """
        try:
            id_value = i["id"]
        except KeyError:
            try:
                id_value = i["rule"]["id"]
            except KeyError:
                try:
                    id_value = i["name"]
                except KeyError:
                    id_value = None

        return id_value
