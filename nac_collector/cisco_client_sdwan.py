import logging
import requests
import urllib3
import json

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("main")


class CiscoClientSDWAN(CiscoClient):
    SDWAN_AUTH_ENDPOINT = "/j_security_check"
    SOLUTION = "sdwan"

    def __init__(self, username, password, base_url, ssl_verify):
        super().__init__(username, password, base_url, ssl_verify)

    def authenticate(self):
        """
        Perform token-based authentication.
        """

        auth_url = f"{self.base_url}{self.SDWAN_AUTH_ENDPOINT}"

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
            logger.info("Authentication Successful for URL: %s", auth_url)

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
            endpoints = self.yaml.load(f)

        # Initialize an empty dictionary
        final_dict = {}

        # Initialize an empty list for endpoint feature templates
        # endpoints_feature_templates = []
        endpoints_with_errors = []

        # Iterate through the endpoints excluding the ones which has %i and %v in endpoint['endpoint']
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
                    elif data.get("data"):
                        endpoint_dict[endpoint["name"]]["items"] = data["data"]
                    else:
                        endpoint_dict[endpoint["name"]]["items"] = data

                    # Save results to dictionary
                    final_dict.update(endpoint_dict)

                    logger.info(f"GET {endpoint} succeeded with status code {response.status_code}")
                else:
                    logger.error(f"GET {endpoint} failed with status code {response.status_code}")
                    endpoints_with_errors.append(endpoint)

            elif "%i" in endpoint["endpoint"]:
                endpoint_dict = {
                    endpoint["name"]: {
                        "items": [],
                        "children": {},
                        "endpoint": endpoint["endpoint"],
                    }
                }
                new_endpoint = endpoint["endpoint"].replace("/object/%i", "")  # Replace '/object/%i' with ''
                response = self.get_request(self.base_url + new_endpoint, max_retries, retry_after, timeout)
                for item in response.json()["data"]:
                    template_endpoint = new_endpoint + "/object/" + str(item["templateId"])
                    response = self.get_request(
                        self.base_url + template_endpoint,
                        max_retries,
                        retry_after,
                        timeout,
                    )
                    if response.status_code == 200:
                        # Get the JSON content of the response
                        data = response.json()
                        endpoint_dict[endpoint["name"]]["items"].append(data)
                        # Save results to dictionary
                        final_dict.update(endpoint_dict)
                        logger.info(f"GET {template_endpoint} succeeded with status code {response.status_code}")
                    else:
                        logger.error(f"GET {template_endpoint} failed with status code {response.status_code}")

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
                        response = self.get_request(
                            self.base_url + new_endpoint,
                            max_retries,
                            retry_after,
                            timeout,
                        )

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
                    response = self.get_request(
                        self.base_url + template_endpoint,
                        max_retries,
                        retry_after,
                        timeout,
                    )
                    if response.status_code == 200:
                        # Get the JSON content of the response
                        data = response.json()
                        endpoint_dict[endpoint["name"]]["items"].append(data)
                        # Save results to dictionary
                        final_dict.update(endpoint_dict)
                        logger.info(f"GET {template_endpoint} succeeded with status code {response.status_code}")
                    else:
                        logger.error(f"GET {template_endpoint} failed with status code {response.status_code}")

        # Write the final dictionary to a JSON file
        with open(f"{self.SOLUTION}.json", "w") as f:
            json.dump(final_dict, f, indent=4)
            logger.info("GET requests finished")
