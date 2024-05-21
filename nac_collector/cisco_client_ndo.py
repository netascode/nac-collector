from nac_collector.cisco_client import CiscoClient
import requests
import logging
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("main")

def merge_dict_list(source, destination):
    for key, value in source.items():
        if isinstance(value, dict):
            # get node or create one
            node = destination.setdefault(key, {})
            merge_dict_list(value, node)
        elif isinstance(value, list):
            if key not in destination:
                destination[key] = []
            if isinstance(destination[key], list):
                destination[key].extend(value)
        else:
            destination[key] = value
    return destination


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
                f"Authentication failed with status code: %s",
                response.status_code,
            )
            return

    def get_from_endpoints(self, endpoints_yaml_file):
        with open(endpoints_yaml_file, "r", encoding="utf-8") as f:
            endpoints = self.yaml.load(f)

        final_dict = {}


        for endpoint in endpoints:
            if all(x not in endpoint.get("endpoint",{}) for x in ["%v", "%i"]):

                endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)
                response = self.get_request(self.base_url + endpoint["endpoint"])

                data = response.json()


                if isinstance(data, list):
                    endpoint_dict[endpoint["name"]] = data
                elif isinstance(data, dict):
                    endpoint_dict[endpoint["name"]] = data[endpoint["name"]]

                if endpoint["name"] in final_dict and endpoint["key"]:
                    for i,v in enumerate(endpoint_dict[endpoint["name"]]):
                        for i1,v1 in enumerate(final_dict[endpoint["name"]]):
                            if v.get(endpoint["key"]) == v1.get(endpoint["key"]):
                                endpoint_dict[endpoint["name"]][i] = merge_dict_list(v1,v)
                                break

                final_dict.update(endpoint_dict)

            else:
                parent_endpoint = ""
                parent_path = "/".join(endpoint.get("endpoint").split("/")[:-1])
                for e in endpoints:
                    if parent_path in e.get("endpoint") and e != endpoint:
                        parent_endpoint = e
                        break
                if parent_endpoint and parent_endpoint.get("name") in final_dict:
                    endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)
                    
                    r = []

                    for tmpl in final_dict[parent_endpoint["name"]]:
                        reponse = self.get_request(self.base_url + endpoint["endpoint"].replace("%v",tmpl.get("templateId")))
                        
                        data = reponse.json()
                        r.append(data)

                    print(endpoint_dict)

                    final_dict.update(
                        {
                            endpoint["name"]: r
                        }
                    )

        
        return final_dict
