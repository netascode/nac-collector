import logging

import click
import requests
import urllib3
import json
import os
import concurrent.futures

from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from nac_collector.cisco_client import CiscoClient
import threading

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("main")

# Suppress urllib3 warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)


class CiscoClientCATALYSTCENTER(CiscoClient):
    """
    This class inherits from the abstract class CiscoClient. It's used for authenticating
    with the Cisco Catalyst Center API and retrieving data from various endpoints.
    Authentication is username/password based and a session is created upon successful
    authentication for subsequent requests.
    """

    LOOKUP_FILE = os.path.join(
        os.path.dirname(__file__), "resources/catalystcenter_lookups.json"
    )
    DNAC_AUTH_ENDPOINT = "/dna/system/api/v1/auth/token"
    SOLUTION = "catalystcenter"
    TMP_DIR = './tmp'
    USE_TMPS = True # TODO: Make this and env option?
    USE_IGNORE_LIST = True # TODO: here as well
    ENDPOINT_IGNORE_NAMES = ['tag', 'discovery', 'sites', 'assign_devices_to_tag', 'assign_templates_to_tag', 'device']
    ADDITIONAL_URLS = [{"name": "extended_templates", "endpoint": "/api/v1/template-programmer/extendedTemplates"}]
    SWAP_URLS = {"/dna/intent/api/v1/template-programmer/template": "/dna/intent/api/v2/template-programmer/template"}

    global_site_id = None

    "Used for mapping credentials to the correct endpoint"
    mappings = {
        "credentials_snmpv3": "snmpV3",
        "credentials_snmpv2_read": "snmpV2cRead",
        "credentials_snmpv2_write": "snmpV2cWrite",
        "credentials_cli": "cliCredential",
        "credentials_https_read": "httpsRead",
        "credentials_https_write": "httpsWrite",
        "user": "users",
        "role": "roles",
    }

    """
    Lookups are essential because some endpoint IDs required in Catalyst Center do not follow simple child URL patterns. 
    Instead, they have a fixed structure that cannot be inferred directly from the provider file. 
    As a result, a lookup file is necessary to retrieve the correct IDs.
    """
    with open(LOOKUP_FILE, "r") as json_file:
        id_lookup = json.load(json_file)

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

        auth_url = f"{self.base_url}{self.DNAC_AUTH_ENDPOINT}"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": "application/json",
        }

        # retries = self.max_retries # standard use
        retries = 30

        retry_cfg = Retry(
            connect=retries,
            read=retries,
            status=0,
            backoff_factor=1,
            allowed_methods={"POST"},
            raise_on_status=False,
        )

        session = requests.Session()
        session.mount("https://", HTTPAdapter(max_retries=retry_cfg))

        response = session.post(
            auth_url,
            auth=(self.username, self.password),
            headers=headers,
            verify=self.ssl_verify,
            timeout=self.timeout,
        )

        if response and response.status_code == 200:
            logger.info("Authentication Successful for URL: %s", auth_url)

            token = response.json()["Token"]

            self.session = requests.Session()
            self.session.headers.update(
                {
                    "Content-Type": "application/json",
                    "x-auth-token": token,
                }
            )
            return True

        logger.error(
            "Authentication failed with status code: %s",
            response.status_code,
        )
        return False

    def process_endpoint_data(self, endpoint, endpoint_dict, data, id_=None):
        """
        Process the data for a given endpoint and update the endpoint_dict.

        Parameters:
            endpoint (dict): The endpoint configuration.
            endpoint_dict (dict): The dictionary to store processed data.
            data (dict or list): The data fetched from the endpoint.

        Returns:
            dict: The updated endpoint dictionary with processed data.
        """
        if endpoint.get("endpoint") in self.id_lookup:
            new_endpoint = self.id_lookup[endpoint.get("endpoint")]["target_endpoint"]
        else:
            new_endpoint = endpoint["endpoint"]

        if data is None:
            endpoint_dict[endpoint["name"]].append(
                {"data": {}, "endpoint": new_endpoint}
            )

        # License API returns a list of dictionaries
        elif isinstance(data, list):
            endpoint_dict[endpoint["name"]].append(
                {"data": data, "endpoint": new_endpoint}
            )
        elif isinstance(data.get("response"), dict):
            for k, v in data.get("response").items():
                if (
                    self.mappings.get(endpoint["name"])
                    and self.mappings[endpoint["name"]] == k
                ):
                    for i in v:
                        endpoint_dict[endpoint["name"]].append(
                            {
                                "data": i,
                                "endpoint": new_endpoint + "/" + self.get_id_value(i),
                            }
                        )
                else:
                    elem = (
                        {"data": v, "endpoint": new_endpoint, "name": k}
                    )
                    if id_ is not None:
                        elem["id"] = id_
                    endpoint_dict[endpoint["name"]].append(elem)
                    

        elif isinstance(data.get("response"), list):
            endpoint_dict[endpoint["name"]].append(
                {"data": data.get("response"), "endpoint": endpoint["endpoint"]}
            )
        elif data.get("response"):
            for i in data.get("response"):
                endpoint_dict[endpoint["name"]].append(
                    {
                        "data": i,
                        "endpoint": new_endpoint + "/" + self.get_id_value(i),
                    }
                )

        return endpoint_dict  # Return the processed endpoint dictionary

    def fetch_data_alternate(self, endpoint):
        """
        Retrieve data from an alternate endpoint if defined in id_lookup.
        Parameters:
            endpoint (dict): The endpoint configuration.
        Returns:
            dict: The dictionary containing the data retrieved from the alternate endpoint.
        """

        id_lookup_data = self.fetch_data_pagination(
            self.id_lookup[endpoint.get("endpoint")]["source_endpoint"]
        )
        if id_lookup_data is None:
            return None
        look_data = id_lookup_data["response"]
        if "/template-programmer/template/version" in endpoint.get(
            "endpoint"
        ):  # bandaid, this endpoint contains ids deeper than usual 
            look_data = [tpl for el in look_data for tpl in el["templates"]]
        id_list = [
            i[self.id_lookup[endpoint.get("endpoint")]["source_key"]] for i in look_data
        ]
        data_list = []
        for id_ in id_list:
            lookup_endpoint = self.id_lookup[endpoint.get("endpoint")][
                "target_endpoint"
            ].replace("%v", id_)
            data = self.fetch_data_pagination(lookup_endpoint)
            if isinstance(data, dict) and data.get("response"):
                data = data["response"]
            if isinstance(data, dict):
                data[
                    self.id_lookup[endpoint.get("endpoint")].get("target_key", "id")
                ] = id_
            elif isinstance(data, list):
                data = {
                    self.id_lookup[endpoint.get("endpoint")].get(
                        "target_key", "id"
                    ): id_,
                    "data": data,
                }
            data_list.append(data)
        data = {"response": data_list}
        return data

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
        endpoints.extend(self.ADDITIONAL_URLS)
        # Initialize an empty dictionary
        final_dict = {}

        # Iterate over all endpoints
        os.makedirs(self.TMP_DIR, exist_ok=True)
        with click.progressbar(endpoints, label="Processing endpoints") as endpoint_bar:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                results = list(executor.map(self.process_endpoint, endpoint_bar))
            for r in results:
                if r is not None:
                    final_dict.update(r)
            return final_dict
      

    @staticmethod
    def get_id_value(i):
        """
        Attempts to get the 'id' or 'name' value from a dictionary.

        Parameters:
            i (dict): The dictionary to get the 'id', 'name', 'userId' or 'siteId' value from.

        Returns:
            str or None: The 'id', 'name', 'userId' or 'siteId' value if it exists, None otherwise.
        """
        params = ["id", "name", "userId", "siteId"]
        for p in params:
            x = i.get(p)
            if x is not None:
                return x
        return None

    def process_endpoint(self, endpoint):
        if self.USE_IGNORE_LIST and endpoint["name"] in self.ENDPOINT_IGNORE_NAMES:
            return
        if endpoint.get("endpoint") in self.SWAP_URLS.keys():
            endpoint["endpoint"] = self.SWAP_URLS[endpoint["endpoint"]]
        tmp_file_name = os.path.join(self.TMP_DIR, endpoint["name"])
        try:
            if self.USE_TMPS and os.path.exists(tmp_file_name):
                with open(tmp_file_name, "r") as json_file:
                    return json.load(json_file)
        except Exception as e:
            logger.info("encountered error while proceeding data from tmp file %s: %s, continue fetching data normally",tmp_file_name, e)

        logger.info("Processing endpoint: %s", endpoint["name"])

        endpoint_dict = CiscoClient.create_endpoint_dict(endpoint)
        if endpoint.get("endpoint") in self.id_lookup:
            logger.info(
                "Alternate endpoint found: %s",
                self.id_lookup[endpoint.get("endpoint")]["source_endpoint"],
            )
            data = self.fetch_data_alternate(endpoint)
            if data is None:
                return
        else:
            data = self.fetch_data_pagination(endpoint["endpoint"])

        if endpoint['name'] == "site":
            self.global_site_id = [x for x in data['response'] if x['name'] == 'Global'][0]['id']

        endpoint_dict = self.process_endpoint_data(endpoint, endpoint_dict, data)

        if endpoint.get("children"):

            parent_endpoint_ids = []
            for item in endpoint_dict[endpoint["name"]]:
                try:
                    if isinstance(item["data"], list):
                        parent_endpoint_ids.extend([x["id"] for x in item["data"]])
                    else:
                        parent_endpoint_ids.append(item["data"]["id"])
                except KeyError:
                    continue



            lock = threading.Lock()

            def _process_child(children_endpoint):
                """
                Process a single children_endpoint for all parent IDs.
                Runs sequentially for the given child, but in parallel
                with other children.
                """
                log_msg = "%s/%%v%s" % (endpoint["endpoint"], children_endpoint["endpoint"])
                logger.info("Processing children endpoint: %s", log_msg)
                
                parent_ids = parent_endpoint_ids
                if children_endpoint['name'] == "wireless_ssid":
                    parent_ids = [self.global_site_id]
                    

                for parent_id in parent_ids:
                    child_dict = CiscoClient.create_endpoint_dict(children_endpoint)

                    joined_endpoint = (
                        f"{endpoint['endpoint']}/{parent_id}{children_endpoint['endpoint']}"
                    )
                    data = self.fetch_data_pagination(joined_endpoint)

                    child_dict = self.process_endpoint_data(
                        children_endpoint, child_dict, data, parent_id
                    )

                    with lock:
                        for idx, entry in enumerate(endpoint_dict[endpoint["name"]]):
                            if isinstance(entry.get("data"), list):
                                for _ in entry["data"]:
                                    current = entry.setdefault("children", {}).get(
                                        children_endpoint["name"]
                                    )
                                    if current is None:
                                        entry["children"][children_endpoint["name"]] = [
                                            child_dict[children_endpoint["name"]]
                                        ]
                                    else:
                                        current.append(child_dict[children_endpoint["name"]])
                                    break

                            else:
                                if entry.get("data", {}).get("id") == parent_id:
                                    entry.setdefault("children", {})[
                                        children_endpoint["name"]
                                    ] = child_dict[children_endpoint["name"]]


            with concurrent.futures.ThreadPoolExecutor()  as executor:
                list(executor.map(_process_child, endpoint["children"]))

        if self.USE_TMPS:
            with open(tmp_file_name, "w") as json_file:
                json.dump(endpoint_dict, json_file)

        return endpoint_dict