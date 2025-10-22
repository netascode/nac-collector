import json
import logging
from typing import Any

import httpx
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from nac_collector.controller.base import CiscoClientController

logger = logging.getLogger("main")


class CiscoClientSDWAN(CiscoClientController):
    """
    This class inherits from the abstract class CiscoClientController. It's used for authenticating with the Cisco SD-WAN API
    and retrieving data from various endpoints. Authentication is token-based and a session is created upon successful
    authentication for subsequent requests.
    """

    SDWAN_AUTH_ENDPOINT = "/j_security_check"
    SOLUTION = "sdwan"

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str,
        max_retries: int,
        retry_after: int,
        timeout: int,
        ssl_verify: bool,
    ) -> None:
        super().__init__(
            username, password, base_url, max_retries, retry_after, timeout, ssl_verify
        )

    def authenticate(self) -> bool:
        """
        Perform token-based authentication.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """

        auth_url = f"{self.base_url}{self.SDWAN_AUTH_ENDPOINT}"

        data = {"j_username": self.username, "j_password": self.password}

        response = httpx.post(
            auth_url, data=data, verify=self.ssl_verify, timeout=self.timeout
        )

        try:
            cookies = response.headers["Set-Cookie"]
            jsessionid = cookies.split(";")[0]
        except (KeyError, IndexError):
            logger.error("No valid JSESSION ID returned")
            jsessionid = None

        headers = {"Cookie": jsessionid} if jsessionid else {}
        url = self.base_url + "/dataservice/client/token"
        response = httpx.get(
            url=url, headers=headers, verify=self.ssl_verify, timeout=self.timeout
        )

        if response and response.status_code == 200:
            logger.info("Authentication Successful for URL: %s", auth_url)

            # Create a client after successful authentication
            self.client = httpx.Client(
                verify=self.ssl_verify,
                timeout=self.timeout,
            )
            self.client.headers.update(
                {
                    "Content-Type": "application/json",
                    "Cookie": jsessionid or "",
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

    def get_from_endpoints_data(
        self, endpoints_data: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Retrieve data from a list of endpoint definitions provided as data structure.

        Parameters:
            endpoints_data (list[dict[str, Any]]): List of endpoint definitions with name and endpoint keys.

        Returns:
            dict: The final dictionary containing the data retrieved from the endpoints.
        """
        # Initialize an empty dictionary
        final_dict = {}

        # Iterate over all endpoints
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=None,
        ) as progress:
            task = progress.add_task("Processing endpoints", total=len(endpoints_data))
            for endpoint in endpoints_data:
                progress.advance(task)
                endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)

                if all(
                    x not in endpoint["endpoint"]
                    for x in [
                        "%v",
                        "%i",
                        "/v1/config-group/",
                        "/v1/feature-profile/",
                        "/template/device/",
                        "/template/policy/definition",
                        "/template/policy/vedge",
                        "/template/policy/vsmart",
                        "/template/policy/security",
                    ]
                ):
                    response = self.get_request(self.base_url + endpoint["endpoint"])

                    if response:
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
                                            {
                                                "data": i,
                                                "endpoint": endpoint["endpoint"],
                                            }
                                        )
                            else:
                                endpoint_dict[endpoint["name"]].append(
                                    {
                                        "data": data["data"],
                                        "endpoint": endpoint["endpoint"],
                                    }
                                )

                        # Save results to dictionary
                        final_dict.update(endpoint_dict)
                        self.log_response(endpoint["endpoint"], response)

                # config groups
                elif "/v1/config-group/" in endpoint["endpoint"]:
                    endpoint_dict = self.get_config_groups(endpoint, endpoint_dict)
                    final_dict.update(endpoint_dict)
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
                elif "%i" in endpoint["endpoint"]:
                    endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)
                    new_endpoint = endpoint["endpoint"].replace(
                        "/object/%i", ""
                    )  # Replace '/object/%i' with ''
                    response = self.get_request(self.base_url + new_endpoint)
                    if response is None:
                        continue
                    for item in response.json()["data"]:
                        template_endpoint = (
                            new_endpoint + "/object/" + str(item["templateId"])
                        )
                        response = self.get_request(self.base_url + template_endpoint)
                        if response is None:
                            continue

                        # Get the JSON content of the response
                        data = response.json()
                        endpoint_dict[endpoint["name"]].append(
                            {"data": data, "endpoint": template_endpoint}
                        )
                        # Save results to dictionary
                        final_dict.update(endpoint_dict)

                        self.log_response(endpoint["endpoint"], response)
                else:
                    pass
        return final_dict

    def get_device_templates(
        self, endpoint: dict[str, Any], endpoint_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Process device template variables.

        Args:
            endpoint (dict): The endpoint to process.
            endpoint_dict (dict): The dictionary to append items to.
            final_dict (dict): The final dictionary to update.
        """
        response = self.get_request(self.base_url + endpoint["endpoint"])
        if response is None:
            return endpoint_dict

        for item in response.json()["data"]:
            if item["deviceType"] == "vsmart":
                continue
            if item["devicesAttached"] != 0:
                device_template_endpoint = (
                    endpoint["endpoint"] + "config/attached/" + str(item["templateId"])
                )
                response = self.get_request(
                    self.base_url + device_template_endpoint,
                )
                if response is None:
                    continue
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
                if response is None:
                    continue

                data = response.json()
                if isinstance(data.get("data"), list):
                    for i in data["data"]:
                        try:
                            endpoint_dict[endpoint["name"]].append(
                                {
                                    "header": data.get("header", {}),
                                    "data": i,
                                    "endpoint": device_template_endpoint,
                                }
                            )
                        except TypeError:
                            endpoint_dict[endpoint["name"]].append(
                                {
                                    "header": data.get("header", {}),
                                    "data": i,
                                    "endpoint": device_template_endpoint,
                                }
                            )
                else:
                    endpoint_dict[endpoint["name"]].append(
                        {
                            "header": data.get("header", {}),
                            "data": data.get("data", {}),
                            "endpoint": device_template_endpoint,
                        }
                    )

                self.log_response(endpoint["endpoint"], response)

        return endpoint_dict

    def get_policy_definitions(
        self, endpoint: dict[str, Any], endpoint_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Process policy definitions

        Args:
            endpoint (dict): The endpoint to process.
            endpoint_dict (dict): The dictionary to append items to.

        Returns:
            enpdoint_dict: The updated endpoint_dict with the processed policy definitions.

        """
        response = self.get_request(self.base_url + endpoint["endpoint"])
        if response is None:
            return endpoint_dict

        for item in response.json()["data"]:
            if "definitionId" in item.keys():
                new_endpoint = endpoint["endpoint"] + item["definitionId"]
            else:
                new_endpoint = endpoint["endpoint"] + "definition/" + item["policyId"]
            response = self.get_request(self.base_url + new_endpoint)
            if response is None:
                continue

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

    def get_feature_templates(
        self, endpoint: dict[str, Any], endpoint_dict: dict[str, Any]
    ) -> dict[str, Any]:
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
        if response is None:
            return endpoint_dict
        for item in response.json()["data"]:
            template_endpoint = new_endpoint + "/object/" + str(item["templateId"])
            response = self.get_request(self.base_url + template_endpoint)
            if response is None:
                continue

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

    def get_config_groups(
        self, endpoint: dict[str, Any], endpoint_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Process config groups

        Args:
            endpoint (dict): The endpoint to process.
            endpoint_dict (dict): The dictionary to append items to.

        Returns:
            enpdoint_dict: The updated endpoint_dict with the processed config groups.

        """
        endpoint_dict["configuration_group_devices"] = []
        response = self.get_request(self.base_url + endpoint["endpoint"])
        if response is None:
            return endpoint_dict
        for item in response.json():
            config_group_endpoint = endpoint["endpoint"] + self.get_id_value(item)
            response = self.get_request(self.base_url + config_group_endpoint)
            if response is None:
                continue

            data = response.json()

            if data.get("solution") == "sdwan":
                try:
                    endpoint_dict[endpoint["name"]].append(
                        {
                            "data": data,
                            "endpoint": config_group_endpoint,
                        }
                    )
                except TypeError:
                    endpoint_dict[endpoint["name"]].append(
                        {"data": data, "endpoint": endpoint["endpoint"]}
                    )
                self.log_response(config_group_endpoint, response)

                # If configuration group has devices assigned, extract devices details to configuration_group_devices
                if data.get("numberOfDevices") > 0:
                    config_group_devices_endpoint = (
                        config_group_endpoint + "/device/variables"
                    )
                    response = self.get_request(
                        self.base_url + config_group_devices_endpoint
                    )
                    if response is None:
                        continue
                    for device_data in response.json().get("devices", []):
                        endpoint_dict["configuration_group_devices"].append(
                            {
                                "data": device_data,
                                "endpoint": config_group_devices_endpoint,
                            }
                        )
                    self.log_response(config_group_devices_endpoint, response)

        return endpoint_dict

    def get_feature_profiles(
        self, endpoint: dict[str, Any], endpoint_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Process feature profiles

        Args:
            endpoint (dict): The endpoint to process.
            endpoint_dict (dict): The dictionary to append items to.

        Returns:
            enpdoint_dict: The updated endpoint_dict with the processed profiles.

        """
        response = self.get_request(self.base_url + endpoint["endpoint"])
        if response is None:
            return endpoint_dict

        try:
            data_loop = response.json()
        except AttributeError:
            data_loop = []
        for item in data_loop:
            profile_endpoint = endpoint["endpoint"] + "/" + str(item["profileId"])
            response = self.get_request(self.base_url + profile_endpoint)
            if response is None:
                continue
            main_entry = {
                "data": response.json(),
                "endpoint": self.base_url + profile_endpoint,
            }
            children_entries = []
            associated_parcels = response.json().get("associatedProfileParcels", [])
            for children_endpoint in endpoint.get("children", []):
                children_endpoint_type = children_endpoint["endpoint"]
                children_endpoint_type = self.strip_backslash(children_endpoint_type)
                for parcel in associated_parcels:
                    if parcel["parcelType"] == children_endpoint_type:
                        children_entries.append(
                            self.extract_feature_parcel(
                                profile_endpoint,
                                "",
                                children_endpoint.get("children", []),
                                parcel,
                            )
                        )
            if children_entries:
                main_entry["children"] = children_entries
            endpoint_dict[endpoint["name"]].append(main_entry)

        return endpoint_dict

    def extract_feature_parcel(
        self,
        upstream_endpoint: str,
        upstream_parcel_type: str,
        children_endpoints: list[dict[str, Any]],
        parcel: dict[str, Any],
    ) -> dict[str, Any]:
        parcel_type = parcel["parcelType"]
        if parcel_type.startswith(upstream_parcel_type):
            parcel_type = parcel_type[len(upstream_parcel_type) :].lstrip("/")
        parcel_id = parcel["parcelId"]
        new_endpoint = upstream_endpoint + "/" + parcel_type + "/" + parcel_id
        response = self.get_request(self.base_url + new_endpoint)
        if response is None:
            return {"data": {}, "endpoint": new_endpoint}
        entry = {
            "data": response.json(),
            "endpoint": new_endpoint,
        }
        children_entries = []
        for children_endpoint in children_endpoints:
            children_endpoint_type = (
                parcel_type + "/" + self.strip_backslash(children_endpoint["endpoint"])
            )
            children_endpoint_type1 = self.strip_backslash(children_endpoint_type)
            children_endpoint_type2 = self.strip_backslash(children_endpoint_type)
            if children_endpoint_type.startswith(parcel_type):
                children_endpoint_type2 = children_endpoint_type1[
                    len(parcel_type) :
                ].lstrip("/")
            for subparcel in parcel.get("subparcels", []):
                if subparcel["parcelType"] in [
                    children_endpoint_type1,
                    children_endpoint_type2,
                ]:
                    children_entries.append(
                        self.extract_feature_parcel(
                            new_endpoint,
                            parcel_type,
                            children_endpoint.get("children", []),
                            subparcel,
                        )
                    )
        if children_entries:
            entry["children"] = children_entries
        return entry

    @staticmethod
    def strip_backslash(endpoint_string: str) -> str:
        if endpoint_string.startswith("/"):
            endpoint_string = endpoint_string[1:]
        if endpoint_string.endswith("/"):
            endpoint_string = endpoint_string[:-1]
        return endpoint_string

    @staticmethod
    def get_id_value(i: dict[str, Any]) -> str | None:
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
            if isinstance(i, dict) and key in i:
                return str(i[key])

        return None
