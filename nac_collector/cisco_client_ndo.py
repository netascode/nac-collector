import logging

import requests
import urllib3

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("main")


class CiscoClientNDO(CiscoClient):
    NDO_AUTH_ENDPOINT = "/login"
    SOLUTION = "ndo"

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
        auth_url = f"{self.base_url}{self.NDO_AUTH_ENDPOINT}"

        data = {
            "userName": self.username,
            "userPasswd": self.password,
            "domain": "DefaultAuth",
        }

        self.session = requests.Session()

        response = self.session.post(
            auth_url, json=data, verify=self.ssl_verify, timeout=self.timeout
        )

        if response.status_code != requests.codes.ok:
            logger.error(
                "Authentication failed with status code: %s",
                response.status_code,
            )
            return True
        return False

    def get_from_endpoints(self, endpoints_yaml_file):
        with open(endpoints_yaml_file, "r", encoding="utf-8") as f:
            endpoints = self.yaml.load(f)

        final_dict = {}

        for endpoint in endpoints:
            if all(x not in endpoint.get("endpoint", {}) for x in ["%v", "%i"]):
                endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)
                response = self.get_request(self.base_url + endpoint["endpoint"])

                data = response.json()

                if isinstance(data, list):
                    endpoint_dict[endpoint["name"]]["items"] = data
                elif isinstance(data, dict):
                    endpoint_dict[endpoint["name"]]["items"] = data[endpoint["name"]]

                final_dict.update(endpoint_dict)

        return final_dict
