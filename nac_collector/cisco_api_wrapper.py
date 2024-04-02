import requests
import logging
import urllib3
import yaml
import json
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("main")


class CiscoClient:
    def __init__(self, username, password, base_url, auth_type, solution, ssl_verify=False):
        """
        Initialize CiscoClient instance.

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
        self.solution = solution

    def authenticate(self, auth_endpoint):
        """
        Authenticate using the specified authentication type.

        Parameters:
            auth_endpoint (str): The endpoint for authentication.
        """
        auth_url = f"{self.base_url}{auth_endpoint}"

        if self.auth_type == "basic":
            self._authenticate_basic(auth_url)
        elif self.auth_type == "token":
            self._authenticate_token(auth_url)
        else:
            logger.error("Unsupported authentication type: %s", self.auth_type)

    def _authenticate_basic(self, auth_url):
        """
        Perform basic authentication.

        Parameters:
            auth_url (str): The complete authentication URL.
        """
        # Set headers based on auth_url
        # If it's ERS API, then set up content-type and accept as application/xml
        if "API/NetworkAccessConfig/ERS" in auth_url:
            headers = {"Content-Type": "application/xml", "Accept": "application/xml"}
        else:
            headers = {"Content-Type": "application/json", "Accept": "application/json"}

        response = requests.get(
            auth_url,
            auth=(self.username, self.password),
            headers=headers,
            verify=self.ssl_verify,
        )

        if response and response.status_code == 200:
            logger.info("%s Authentication Successful for URL: %s", self.auth_type, auth_url)
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

    def _authenticate_token(self, auth_url):
        """
        Perform token-based authentication.

        Parameters:
            auth_url (str): The complete authentication URL.
        """
        data = {"j_username": self.username, "j_password": self.password}
        response = requests.post(auth_url, data=data, verify=self.ssl_verify)
        try:
            cookies = response.headers["Set-Cookie"]
            jsessionid = cookies.split(";")[0]
        except requests.exceptions.InvalidHeader:
            logger.error("No valid JSESSION ID returned")
            jsessionid = None

        headers = {"Cookie": jsessionid}
        url = self.base_url + "/dataservice/client/token"
        response = requests.get(url=url, headers=headers, verify=self.ssl_verify)

        if response and response.status_code == 200:
            logger.info("%s Authentication Successful for URL: %s", self.auth_type, auth_url)

            # Create a session after successful authentication
            self.session = requests.Session()
            self.session.headers.update(
                {
                    "Content-Type": "application/json",
                    "Cookie": jsessionid,
                    "X-XSRF-TOKEN": response.text,
                }
            )
            self.base_url = self.base_url + "/dataservice"

        else:
            logger.error(
                "Authentication failed with status code: %s",
                response.status_code,
            )

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
            endpoints = yaml.safe_load(f)

        # Initialize an empty dictionary
        final_dict = {}

        # Initialize an empty list for endpoint with error 4XX
        endpoints_with_errors = []

        # Iterate through the endpoints
        for endpoint in endpoints:
            endpoint_dict = {endpoint: {"items": [], "children": {}}}

            response = self.get_request(self.base_url + endpoint, max_retries, retry_after, timeout)

            # Check if the request was successful
            if response.status_code == 200:
                # Get the JSON content of the response
                data = response.json()

                if isinstance(data, list):
                    endpoint_dict[endpoint]["items"] = data
                elif data.get("response"):
                    if isinstance(data.get("response"), list):
                        endpoint_dict[endpoint]["items"] = data["response"]
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

                    endpoint_dict[endpoint]["items"] = ers_data
                elif data.get("response") == []:
                    endpoint_dict[endpoint]["items"] = data["response"]
                elif data.get("data"):
                    endpoint_dict[endpoint]["items"] = data["data"]
                else:
                    endpoint_dict[endpoint]["items"] = data

                # Save results to dictionary
                final_dict.update(endpoint_dict)

                logger.info(f"GET {endpoint} succeeded with status code {response.status_code}")
            else:
                logger.error(f"GET {endpoint} failed with status code {response.status_code}")
                endpoints_with_errors.append(endpoint)

        # Iterate through the endpoints with errors
        for endpoint in endpoints_with_errors:
            # Resolve children
            if "%v" in endpoint:
                parent_endpoint = endpoint.split("/%v")[0]

                # Check if final_dict[parent_endpoint] exists
                if parent_endpoint in final_dict:
                    # Initialize an empty list for parent endpoint ids
                    parent_endpoint_ids = []

                    # Iterate over the items in final_dict[parent_endpoint]['items']
                    for item in final_dict[parent_endpoint]["items"]:
                        # Add the item's id to the list
                        parent_endpoint_ids.append(item["id"])

                    # Iterate over the parent endpoint ids
                    for id in parent_endpoint_ids:
                        # Replace '%v' in the endpoint with the id
                        new_endpoint = endpoint.replace("%v", str(id))

                        # Send a GET request to the new endpoint
                        response = self.get_request(self.base_url + new_endpoint, max_retries, retry_after, timeout)

                        if response.status_code == 200:
                            # Get the JSON content of the response
                            data = response.json()

                            if isinstance(data.get("response"), list):
                                # Get the children endpoint name (e.g., 'authentication', 'authorization')
                                children_endpoint_name = endpoint.split("/%v/")[1]

                                # Check if the children endpoint name already exists in the 'children' dictionary
                                if children_endpoint_name not in final_dict[parent_endpoint]["children"]:
                                    # If not, create a new list for it
                                    final_dict[parent_endpoint]["children"][children_endpoint_name] = []

                                # Add the data to the list
                                final_dict[parent_endpoint]["children"][children_endpoint_name].extend(data["response"])

                            logger.info(f"GET {endpoint} succeeded with status code {response.status_code}")
                        else:
                            logger.error(f"GET {endpoint} failed with status code {response.status_code}")
            # resolve feature templates
            elif "%i" in endpoint:
                endpoint_dict = {endpoint: {"items": [], "children": {}}}
                new_endpoint = endpoint.replace("/object/%i", "")  # Replace '/object/%i' with ''
                response = self.get_request(self.base_url + new_endpoint, max_retries, retry_after, timeout)
                for item in response.json()["data"]:
                    template_endpoint = new_endpoint + "/object/" + str(item["templateId"])
                    response = self.get_request(self.base_url + template_endpoint, max_retries, retry_after, timeout)
                    if response.status_code == 200:
                        # Get the JSON content of the response
                        data = response.json()
                        endpoint_dict[endpoint]["items"].append(data)
                        # Save results to dictionary
                        final_dict.update(endpoint_dict)
                        logger.info(f"GET {template_endpoint} succeeded with status code {response.status_code}")
                    else:
                        logger.error(f"GET {template_endpoint} failed with status code {response.status_code}")

        # Write the final dictionary to a JSON file
        with open(f"{self.solution}.json", "w") as f:
            json.dump(final_dict, f, indent=4)
            logger.info("GET requests finished")

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
