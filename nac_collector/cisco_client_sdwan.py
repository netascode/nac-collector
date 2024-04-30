import logging
import json
import requests
import urllib3

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("main")


class CiscoClientSDWAN(CiscoClient):
    """
    This class inherits from the abstract class CiscoClient. It's used for authenticating with the Cisco SD-WAN API
    and retrieving data from various endpoints. Authentication is token-based and a session is created upon successful
    authentication for subsequent requests.
    """

    SDWAN_AUTH_ENDPOINT = "/j_security_check"
    SOLUTION = "sdwan"

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
        Perform token-based authentication.
        """

        auth_url = f"{self.base_url}{self.SDWAN_AUTH_ENDPOINT}"

        data = {"j_username": self.username, "j_password": self.password}

        response = requests.post(auth_url, data=data, verify=self.ssl_verify, timeout=self.timeout)

        try:
            cookies = response.headers["Set-Cookie"]
            jsessionid = cookies.split(";")[0]
        except requests.exceptions.InvalidHeader:
            logger.error("No valid JSESSION ID returned")
            jsessionid = None

        headers = {"Cookie": jsessionid}
        url = self.base_url + "/dataservice/client/token"
        response = requests.get(url=url, headers=headers, verify=self.ssl_verify, timeout=self.timeout)

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

        # Initialize an empty list for endpoint feature templates
        # endpoints_feature_templates = []
        endpoints_with_errors = []

        # Iterate through the endpoints
        for endpoint in endpoints:
            endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)

            if all(x not in endpoint["endpoint"] for x in ["%v", "%i", "/v1/feature-profile/"]):
                endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)

                endpoint_dict[endpoint["name"]]["endpoint"] = endpoint["endpoint"]

                response = self.get_request(self.base_url + endpoint["endpoint"])

                # Get the JSON content of the response
                data = response.json()

                if isinstance(data, list):
                    endpoint_dict[endpoint["name"]]["items"] = data
                elif data.get("data"):
                    endpoint_dict[endpoint["name"]]["items"] = data["data"]

                # Save results to dictionary
                final_dict.update(endpoint_dict)

                self.log_response(endpoint, response)

            # feature profiles
            elif "/v1/feature-profile/" in endpoint["endpoint"]:
                print(endpoint["name"], endpoint["endpoint"])
                endpoint_dict = self.get_feature_profiles(endpoint, endpoint_dict)
                final_dict.update(endpoint_dict)
            # device templates
            elif endpoint["name"] == "cli_device_template":
                endpoint_dict = self.get_device_templates(endpoint, endpoint_dict)
            # for feature templates and device templates
            elif "%i" in endpoint["endpoint"]:
                endpoint_dict = self.get_feature_templates(endpoint, endpoint_dict)
                # Save results to dictionary
                final_dict.update(endpoint_dict)

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
                    for id_ in parent_endpoint_ids:
                        # Replace '%v' in the endpoint with the id
                        new_endpoint = endpoint.replace("%v", str(id_))

                        # Send a GET request to the new endpoint
                        response = self.get_request(self.base_url + new_endpoint)

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

                        self.log_response(endpoint, response)

            # resolve feature templates
            elif "%i" in endpoint:
                endpoint_dict = {endpoint: {"items": [], "children": {}}}
                new_endpoint = endpoint.replace("/object/%i", "")  # Replace '/object/%i' with ''
                response = self.get_request(self.base_url + new_endpoint)
                for item in response.json()["data"]:
                    template_endpoint = new_endpoint + "/object/" + str(item["templateId"])
                    response = self.get_request(self.base_url + template_endpoint)

                    # Get the JSON content of the response
                    data = response.json()
                    endpoint_dict[endpoint["name"]]["items"].append(data)
                    # Save results to dictionary
                    final_dict.update(endpoint_dict)

                    self.log_response(endpoint, response)

        return final_dict

    def get_device_templates(self, endpoint, endpoint_dict):
        """
        Process CLI device templates.

        Args:
            endpoint (dict): The endpoint to process.
            endpoint_dict (dict): The dictionary to append items to.
            final_dict (dict): The final dictionary to update.
        """
        response = self.get_request(self.base_url + endpoint["endpoint"])

        for item in response.json()["data"]:
            if item["devicesAttached"] != 0:
                device_template_endpoint = endpoint["endpoint"] + "config/attached/" + str(item["templateId"])
                response = self.get_request(
                    self.base_url + device_template_endpoint,
                )
                attached_uuids = [device["uuid"] for device in response.json()["data"]]
                data = {
                    "templateId": str(item["templateId"]),
                    "deviceIds": attached_uuids,
                    "isEdited": False,
                    "isMasterEdited": False,
                }

                response = self.post_request(
                    self.base_url + "/template/device/config/input/",
                    json.dumps(data),
                )

                data = response.json()
                endpoint_dict[endpoint["name"]]["items"].extend(data["data"])
                self.log_response(endpoint, response)

        return endpoint_dict

    def get_feature_templates(self, endpoint, endpoint_dict):
        """
        Process feature templates and feature device templates

        Args:
            endpoint (dict): The endpoint to process.
            endpoint_dict (dict): The dictionary to append items to.

        Returns:
            enpdoint_dict: The updated endpoint_dict with the processed templates.

        """
        new_endpoint = endpoint["endpoint"].replace("/object/%i", "")  # Replace '/object/%i' with ''
        response = self.get_request(self.base_url + new_endpoint)
        for item in response.json()["data"]:
            template_endpoint = new_endpoint + "/object/" + str(item["templateId"])
            response = self.get_request(self.base_url + template_endpoint)

            data = response.json()
            endpoint_dict[endpoint["name"]]["items"].append(data)

            self.log_response(template_endpoint, response)

        return endpoint_dict

    def get_feature_profiles(self, endpoint, endpoint_dict):
        """
        Process feature profiles

        Args:
            endpoint (dict): The endpoint to process.
            endpoint_dict (dict): The dictionary to append items to.

        Returns:
            enpdoint_dict: The updated endpoint_dict with the processed profiles.

        """
        response = self.get_request(self.base_url + endpoint["endpoint"])

        try:
            data_loop = response.json()
        except AttributeError:
            data_loop = []
        for item in data_loop:
            profile_endpoint = endpoint["endpoint"] + str(item["profileId"])
            response = self.get_request(self.base_url + profile_endpoint)

            for k, v in response.json().items():
                if k == "associatedProfileParcels":
                    for parcel in v:
                        parcel_id = parcel["parcelId"]
                        parcel_type = parcel["parcelType"]
                        new_endpoint = profile_endpoint + "/" + parcel_type + "/" + parcel_id
                        response = self.get_request(self.base_url + new_endpoint)
                        self.log_response(new_endpoint, response)
                        data = response.json()
                        endpoint_dict[endpoint["name"]]["items"].append(data)

        return endpoint_dict
