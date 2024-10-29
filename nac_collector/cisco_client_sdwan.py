import json
import logging

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
        super().__init__(
            username, password, base_url, max_retries, retry_after, timeout, ssl_verify
        )

    def authenticate(self):
        """
        Perform token-based authentication.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """

        auth_url = f"{self.base_url}{self.SDWAN_AUTH_ENDPOINT}"

        data = {"j_username": self.username, "j_password": self.password}

        response = requests.post(
            auth_url, data=data, verify=self.ssl_verify, timeout=self.timeout
        )

        try:
            cookies = response.headers["Set-Cookie"]
            jsessionid = cookies.split(";")[0]
        except requests.exceptions.InvalidHeader:
            logger.error("No valid JSESSION ID returned")
            jsessionid = None

        headers = {"Cookie": jsessionid}
        url = self.base_url + "/dataservice/client/token"
        response = requests.get(
            url=url, headers=headers, verify=self.ssl_verify, timeout=self.timeout
        )

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

        # Iterate through the endpoints
        for endpoint in endpoints:
            endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)

            if all(
                x not in endpoint["endpoint"]
                for x in [
                    "%v",
                    "%i",
                    "/v1/feature-profile/",
                    "/template/device/",
                    "/template/policy/definition",
                    "/template/policy/vedge",
                    "/template/policy/vsmart",
                    "/template/policy/security",
                ]
            ):
                response = self.get_request(self.base_url + endpoint["endpoint"])

                # Get the JSON content of the response
                data = response.json()

                if isinstance(data, list):
                    for i in data:
                        endpoint_dict[endpoint["name"]].append(
                            {
                                "data": i,
                                "endpoint": endpoint["endpoint"]
                                + "/"
                                + self.get_id_value(i),
                            }
                        )
                elif data.get("data"):
                    if isinstance(data["data"], list):
                        for i in data["data"]:
                            try:
                                endpoint_dict[endpoint["name"]].append(
                                    {
                                        "data": i,
                                        "endpoint": endpoint["endpoint"]
                                        + "/"
                                        + self.get_id_value(i),
                                    }
                                )
                            except TypeError:
                                endpoint_dict[endpoint["name"]].append(
                                    {"data": i, "endpoint": endpoint["endpoint"]}
                                )
                    else:
                        endpoint_dict[endpoint["name"]].append(
                            {"data": data["data"], "endpoint": endpoint["endpoint"]}
                        )

                # Save results to dictionary
                final_dict.update(endpoint_dict)
                self.log_response(endpoint["endpoint"], response)

            # feature profiles
            elif "/v1/feature-profile/" in endpoint["endpoint"]:
                endpoint_dict = self.get_feature_profiles(endpoint, endpoint_dict)
                final_dict.update(endpoint_dict)
            # device templates
            elif endpoint["name"] == "cli_device_template":
                endpoint_dict = self.get_device_templates(endpoint, endpoint_dict)
                final_dict.update(endpoint_dict)
            # policy definitions
            elif any(
                substring in endpoint["endpoint"]
                for substring in [
                    "/template/policy/definition",
                    "/template/policy/vedge",
                    "/template/policy/vsmart",
                    "/template/policy/security",
                ]
            ):
                endpoint_dict = self.get_policy_definitions(endpoint, endpoint_dict)
                final_dict.update(endpoint_dict)
            # for feature templates and device templates
            elif "%i" in endpoint["endpoint"]:
                endpoint_dict = self.get_feature_templates(endpoint, endpoint_dict)
                final_dict.update(endpoint_dict)

            # resolve feature templates
            elif "%i" in endpoint:
                endpoint_dict = {endpoint: {"items": [], "children": {}}}
                new_endpoint = endpoint.replace(
                    "/object/%i", ""
                )  # Replace '/object/%i' with ''
                response = self.get_request(self.base_url + new_endpoint)
                for item in response.json()["data"]:
                    template_endpoint = (
                        new_endpoint + "/object/" + str(item["templateId"])
                    )
                    response = self.get_request(self.base_url + template_endpoint)

                    # Get the JSON content of the response
                    data = response.json()
                    endpoint_dict[endpoint["name"]]["items"].append(data)
                    # Save results to dictionary
                    final_dict.update(endpoint_dict)

                    self.log_response(endpoint, response)
            else:
                pass
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
                device_template_endpoint = (
                    endpoint["endpoint"] + "config/attached/" + str(item["templateId"])
                )
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
                if isinstance(data["data"], list):
                    for i in data["data"]:
                        try:
                            endpoint_dict[endpoint["name"]].append(
                                {
                                    "header": data["header"],
                                    "data": i,
                                    "endpoint": device_template_endpoint,
                                }
                            )
                        except TypeError:
                            endpoint_dict[endpoint["name"]].append(
                                {
                                    "header": data["header"],
                                    "data": i,
                                    "endpoint": device_template_endpoint,
                                }
                            )
                else:
                    endpoint_dict[endpoint["name"]].append(
                        {
                            "header": data["header"],
                            "data": data["data"],
                            "endpoint": device_template_endpoint,
                        }
                    )

                self.log_response(endpoint, response)

        return endpoint_dict

    def get_policy_definitions(self, endpoint, endpoint_dict):
        """
        Process policy definitions

        Args:
            endpoint (dict): The endpoint to process.
            endpoint_dict (dict): The dictionary to append items to.

        Returns:
            enpdoint_dict: The updated endpoint_dict with the processed policy definitions.

        """
        response = self.get_request(self.base_url + endpoint["endpoint"])

        for item in response.json()["data"]:
            if "definitionId" in item.keys():
                new_endpoint = endpoint["endpoint"] + item["definitionId"]
            else:
                new_endpoint = endpoint["endpoint"] + "definition/" + item["policyId"]
            response = self.get_request(self.base_url + new_endpoint)

            data = response.json()
            try:
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": data,
                        "endpoint": new_endpoint,
                    }
                )
            except TypeError:
                endpoint_dict[endpoint["name"]].append(
                    {"data": data, "endpoint": endpoint["endpoint"]}
                )

            self.log_response(new_endpoint, response)

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
        new_endpoint = endpoint["endpoint"].replace(
            "/object/%i", ""
        )  # Replace '/object/%i' with ''
        response = self.get_request(self.base_url + new_endpoint)
        for item in response.json()["data"]:
            template_endpoint = new_endpoint + "/object/" + str(item["templateId"])
            response = self.get_request(self.base_url + template_endpoint)

            data = response.json()
            try:
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": data,
                        "endpoint": endpoint["endpoint"].split("/%i")[0]
                        + "/"
                        + self.get_id_value(data),
                    }
                )
            except TypeError:
                endpoint_dict[endpoint["name"]].append(
                    {"data": data, "endpoint": endpoint["endpoint"]}
                )

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
            profile_endpoint = endpoint["endpoint"] + "/" + str(item["profileId"])
            response = self.get_request(self.base_url + profile_endpoint)
            main_entry = {
                "data": response.json(),
                "endpoint": self.base_url + profile_endpoint,
            }
            l1_children = []
            for k, v in response.json().items():
                if k == "associatedProfileParcels":
                    for parcel in v:
                        parcel_type = parcel["parcelType"]
                        new_endpoint = profile_endpoint + "/" + parcel_type
                        response = self.get_request(self.base_url + new_endpoint)
                        for l1_item in response.json()["data"]:
                            self.log_response(new_endpoint, response)
                            response = self.get_request(
                                self.base_url + new_endpoint + "/" + l1_item["parcelId"]
                            )
                            data = response.json()
                            if not self.id_exists(l1_children, data["parcelId"]):
                                l1_children.append(
                                    {
                                        "data": data,
                                        "endpoint": new_endpoint
                                        + "/"
                                        + self.get_id_value(data),
                                    }
                                )
            endpoint_dict[endpoint["name"]].append(
                main_entry
                if not l1_children
                else {**main_entry, "children": l1_children}
            )

            for profile_parcel in endpoint_dict.get(endpoint.get("name"), []):
                for associatedProfileParcel in profile_parcel.get("data", {}).get(
                    "associatedProfileParcels", []
                ):
                    subparcels = associatedProfileParcel.get("subparcels", [])
                    if isinstance(subparcels, list) and subparcels:
                        for subparcel in subparcels:
                            l2_parcel_type = subparcel.get("parcelType", "")[
                                len(associatedProfileParcel.get("parcelType", "")) :
                            ].lstrip("/")
                            l2_new_endpoint = f"{self.base_url}{endpoint.get('endpoint', '')}/{profile_parcel.get('data', {}).get('profileId', '')}/{associatedProfileParcel.get('parcelType', '')}/{associatedProfileParcel.get('parcelId', '')}/{l2_parcel_type}"
                            l2_response = self.get_request(l2_new_endpoint)
                            self.log_response(l2_new_endpoint, l2_response)
                            for subparcel_item in l2_response.json().get("data", []):
                                subparcel_endpoint = f"{l2_new_endpoint}/{subparcel_item.get('parcelId', '')}"
                                subparcel_data = self.get_request(
                                    subparcel_endpoint
                                ).json()
                                for profile_parcel_item in profile_parcel.get(
                                    "children", []
                                ):
                                    if profile_parcel_item.get("data", {}).get(
                                        "parcelType"
                                    ) == associatedProfileParcel.get("parcelType"):
                                        profile_parcel_item.setdefault(
                                            "children", []
                                        ).append(
                                            {
                                                "data": subparcel_data,
                                                "endpoint": subparcel_endpoint,
                                            }
                                        )
        return endpoint_dict

    def id_exists(self, l1_children, data_id):
        return any(child["data"]["parcelId"] == data_id for child in l1_children)

    @staticmethod
    def get_id_value(i):
        """
        Attempts to get the 'id', 'parcelId', 'name', 'policyId' 'deviceId' or 'definitionId' value from a dictionary.

        Args:
            i (dict): The dictionary to get the 'id' or 'name' value from.

        Returns:
            str or None: The value if it exists, None otherwise.
        """
        keys = [
            "id",
            "definitionId",
            "parcelId",
            "policyId",
            "templateId",
            "deviceId",
            "name",
        ]

        for key in keys:
            try:
                return i[key]
            except KeyError:
                continue

        return None
