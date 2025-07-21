import logging
import os

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
        api_key,
        base_url,
        max_retries,
        retry_after,
        timeout,
        ssl_verify,
    ):
        self.domain = "DefaultAuth"
        super().__init__(
            username,
            password,
            api_key,
            base_url,
            max_retries,
            retry_after,
            timeout,
            ssl_verify,
        )

    def authenticate(self):
        auth_url = f"{self.base_url}{self.NDO_AUTH_ENDPOINT}"

        login_details = self.username.split("/")

        if len(login_details) > 1:
            self.username = login_details[1]
            self.domain = login_details[0]

        data = {
            "userName": self.username,
            "userPasswd": self.password,
            "domain": self.domain,
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
            return False
        return True

    def get_from_endpoints(self, endpoints_yaml_file):
        if os.path.isfile(endpoints_yaml_file):
            with open(endpoints_yaml_file, "r", encoding="utf-8") as f:
                endpoints = self.yaml.load(f)
        else:
            endpoints = [
                {"endpoint": "/mso/api/v1/tenants", "name": "tenants"},
                {"endpoint": "/mso/api/v1/schemas", "name": "schemas"},
                {"endpoint": "/mso/api/v1/schemas/sites", "name": "site_details"},
                {"endpoint": "/mso/api/v2/users", "name": "users"},
                {
                    "endpoint": "/mso/api/v2/sites/fabric-connectivity",
                    "name": "fabric_connectivity",
                },
                {
                    "endpoint": "/mso/api/v1/templates/summaries",
                    "name": "template_summary",
                },
                {"endpoint": "/mso/api/v1/templates/%v", "name": "templates"},
                {"endpoint": "/mso/api/v1/platform/version", "name": "version"},
                {
                    "endpoint": "/mso/api/v1/platform/systemConfig",
                    "name": "system_configs",
                },
                {
                    "endpoint": "/mso/api/v1/platform/remote-locations",
                    "name": "remote_locations",
                },
            ]
        final_dict = {}

        for endpoint in endpoints:
            if all(x not in endpoint.get("endpoint", {}) for x in ["%v", "%i"]):  # noqa
                endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)
                response = self.get_request(self.base_url + endpoint["endpoint"])  # noqa

                data = response.json()
                key = endpoint["name"]

                if isinstance(data, dict):
                    next_key = next(iter(data))
                    if key == next_key:
                        data = data[next_key]

                endpoint_dict[key] = data if isinstance(data, list) else data

                final_dict.update(endpoint_dict)

            else:
                parent_endpoint = ""
                parent_path = "/".join(endpoint.get("endpoint").split("/")[:-1])  # noqa
                for e in endpoints:
                    if parent_path in e.get("endpoint") and e != endpoint:
                        parent_endpoint = e
                        break
                if parent_endpoint and parent_endpoint.get("name") in final_dict:  # noqa
                    endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)

                    r = []

                    for tmpl in final_dict[parent_endpoint["name"]]:
                        reponse = self.get_request(
                            self.base_url
                            + endpoint["endpoint"].replace("%v", tmpl.get("templateId"))
                        )  # noqa

                        data = reponse.json()
                        r.append(data)

                    final_dict.update({endpoint["name"]: r})
        return final_dict
        return final_dict
        return final_dict
