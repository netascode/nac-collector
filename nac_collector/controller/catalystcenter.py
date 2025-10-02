import concurrent.futures
import datetime
import logging
import os
import threading
from typing import Any

import httpx
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from tinydb import Query, TinyDB

from nac_collector.controller.base import CiscoClientController
from nac_collector.resource_manager import ResourceManager

logger = logging.getLogger("main")


class CiscoClientCATALYSTCENTER(CiscoClientController):
    """
    This class inherits from the abstract class CiscoClientController. It's used for authenticating
    with the Cisco Catalyst Center API and retrieving data from various endpoints.
    Authentication is username/password based and a session is created upon successful
    authentication for subsequent requests.
    """

    DNAC_AUTH_ENDPOINT = "/dna/system/api/v1/auth/token"
    SOLUTION = "catalystcenter"
    SKIP_TMPS = os.environ.get("NAC_SKIP_TMP", "").lower()

    global_site_id: str | None = None

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

    # Load ID lookup data using ResourceManager
    # Lookups are essential because some endpoint IDs required in Catalyst Center do not follow simple child URL patterns.
    # Instead, they have a fixed structure that cannot be inferred directly from the provider file.
    # As a result, a lookup file is necessary to retrieve the correct IDs.
    @staticmethod
    def _load_id_lookup() -> dict[str, Any]:
        """Load and convert the YAML list format to dictionary format for internal use."""
        yaml_data = ResourceManager.get_packaged_lookup_content("catalystcenter")
        if not yaml_data or not isinstance(yaml_data, list):
            return {}

        # Convert list format to dictionary format for internal use
        lookup_dict: dict[str, Any] = {}
        for entry in yaml_data:
            if isinstance(entry, dict) and "endpoint" in entry:
                endpoint_key = entry["endpoint"]
                # Create lookup entry without the 'endpoint' key
                lookup_entry = {k: v for k, v in entry.items() if k != "endpoint"}
                lookup_dict[endpoint_key] = lookup_entry

        return lookup_dict

    id_lookup = _load_id_lookup()

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
        self.db = TinyDB("./tmp_db.json")
        self.job = Query()
        self.start_time = datetime.datetime.now().isoformat()
        self.lock = threading.Lock()
        super().__init__(
            username, password, base_url, max_retries, retry_after, timeout, ssl_verify
        )
        with self.lock:
            existing = self.db.get(self.job.url == self.base_url)
        if existing and self.SKIP_TMPS != "true":
            choice = input(
                f"Detected unfinished job for {self.base_url}"
                f"Do you want to (r)esume it or delete it and (s)tart from scratch"
            )
            if choice == "r":
                logger.info("Resuming...")
            else:
                logger.info(
                    "Starting from scratch, removing existing temporary data..."
                )
                self.db.remove(self.job.url == self.base_url)

    def authenticate(self) -> bool:
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

        # Create httpx session (retry logic handled by base class)
        session = httpx.Client(
            verify=self.ssl_verify,
            timeout=self.timeout,
        )

        response = session.post(
            auth_url,
            auth=(self.username, self.password),
            headers=headers,
        )

        if response and response.status_code == 200:
            logger.info("Authentication Successful for URL: %s", auth_url)

            token = response.json()["Token"]

            self.client = httpx.Client(
                verify=self.ssl_verify,
                timeout=self.timeout,
            )
            self.client.headers.update(
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

    def process_endpoint_data(
        self,
        endpoint: dict[str, Any],
        endpoint_dict: dict[str, Any],
        data: dict[str, Any] | list[Any] | None,
        id_: str | None = None,
    ) -> dict[str, Any]:
        """
        Process the data for a given endpoint and update the endpoint_dict.

        Parameters:
            endpoint (dict): The endpoint configuration.
            endpoint_dict (dict): The dictionary to store processed data.
            data (dict or list): The data fetched from the endpoint.

        Returns:
            dict: The updated endpoint dictionary with processed data.
        """
        endpoint_key = endpoint.get("endpoint")
        if endpoint_key and endpoint_key in self.id_lookup:
            new_endpoint = self.id_lookup[endpoint_key]["target_endpoint"]
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
        elif data and isinstance(data.get("response"), dict):
            response_data = data.get("response")
            if response_data:
                for k, v in response_data.items():
                    if (
                        self.mappings.get(endpoint["name"])
                        and self.mappings[endpoint["name"]] == k
                    ):
                        for i in v:
                            endpoint_dict[endpoint["name"]].append(
                                {
                                    "data": i,
                                    "endpoint": new_endpoint
                                    + "/"
                                    + self.get_id_value(i),
                                }
                            )
                    else:
                        elem = {"data": v, "endpoint": new_endpoint, "name": k}
                        if id_ is not None:
                            elem["id"] = id_
                        endpoint_dict[endpoint["name"]].append(elem)

        elif isinstance(data.get("response"), list):
            endpoint_dict[endpoint["name"]].append(
                {"data": data.get("response"), "endpoint": endpoint["endpoint"]}
            )
        elif data and data.get("response"):
            response_items = data.get("response")
            if response_items:
                for i in response_items:
                    endpoint_dict[endpoint["name"]].append(
                        {
                            "data": i,
                            "endpoint": new_endpoint + "/" + self.get_id_value(i),
                        }
                    )

        return endpoint_dict  # Return the processed endpoint dictionary

    def fetch_data_alternate(self, endpoint: dict[str, Any]) -> dict[str, Any] | None:
        """
        Retrieve data from an alternate endpoint if defined in id_lookup.
        Parameters:
            endpoint (dict): The endpoint configuration.
        Returns:
            dict: The dictionary containing the data retrieved from the alternate endpoint.
        """

        endpoint_key = endpoint.get("endpoint")
        if not endpoint_key or endpoint_key not in self.id_lookup:
            return None

        id_lookup_data = self.fetch_data_pagination(
            self.id_lookup[endpoint_key]["source_endpoint"]
        )
        if id_lookup_data is None:
            return None
        if isinstance(id_lookup_data, dict) and "response" in id_lookup_data:
            look_data = id_lookup_data["response"]
        else:
            return None
        if "/template-programmer/template/version" in endpoint.get(
            "endpoint", ""
        ):  # bandaid, this endpoint contains ids deeper than usual
            if isinstance(look_data, list):
                look_data = [
                    tpl
                    for el in look_data
                    for tpl in el.get("templates", [])
                    if isinstance(el, dict)
                ]
        endpoint_key = endpoint.get("endpoint", "")
        if endpoint_key in self.id_lookup:
            source_key = self.id_lookup[endpoint_key]["source_key"]
            id_list = [
                i.get(source_key)
                for i in look_data
                if isinstance(i, dict) and source_key in i
            ]
        else:
            id_list = []
        data_list = []
        for id_ in id_list:
            lookup_endpoint = self.id_lookup[endpoint_key]["target_endpoint"].replace(
                "%v", id_
            )
            data = self.fetch_data_pagination(lookup_endpoint)
            if isinstance(data, dict) and data.get("response"):
                data = data["response"]
            if isinstance(data, dict):
                data[self.id_lookup[endpoint_key].get("target_key", "id")] = id_
            elif isinstance(data, list):
                data = {
                    self.id_lookup[endpoint_key].get("target_key", "id"): id_,
                    "data": data,
                }
            data_list.append(data)
        data = {"response": data_list}
        return data

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
        endpoints = endpoints_data
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
            task = progress.add_task("Processing endpoints", total=len(endpoints))
            with concurrent.futures.ThreadPoolExecutor() as executor:
                results = []
                futures = [
                    executor.submit(self.process_endpoint, endpoint)
                    for endpoint in endpoints
                ]
                for future in concurrent.futures.as_completed(futures):
                    results.append(future.result())
                    progress.advance(task)
            for r in results:
                if r is not None:
                    final_dict.update(r)
            return final_dict

    @staticmethod
    def get_id_value(i: dict[str, Any]) -> str | None:
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
                return str(x)
        return None

    def process_endpoint(self, endpoint: dict[str, Any]) -> dict[str, Any] | None:
        with self.lock:
            existing = self.db.get(
                (self.job.url == self.base_url)
                & (self.job.endpoint_name == endpoint["name"])
            )
        if existing and self.SKIP_TMPS != "true":
            logger.info("Got endpoint: %s data from tmp db", endpoint["name"])
            content = existing.get("content")
            if isinstance(content, dict):
                return content
            return None

        logger.info("Processing endpoint: %s", endpoint["name"])

        endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)
        endpoint_key = endpoint.get("endpoint")
        if endpoint_key and endpoint_key in self.id_lookup:
            logger.info(
                "Alternate endpoint found: %s",
                self.id_lookup[endpoint_key]["source_endpoint"],
            )
            data = self.fetch_data_alternate(endpoint)
            if data is None:
                return None
        else:
            fetched_data = self.fetch_data_pagination(endpoint["endpoint"])
            if isinstance(fetched_data, dict):
                data = fetched_data
            else:
                data = None

        if (
            endpoint["name"] == "site" and data and "response" in data
        ):  # save global site id for other purposes
            global_sites = [
                x
                for x in data["response"]
                if isinstance(x, dict) and x.get("name") == "Global"
            ]
            if global_sites:
                self.global_site_id = str(global_sites[0].get("id", ""))

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

            def _process_child(children_endpoint: dict[str, Any]) -> None:
                """
                Process a single children_endpoint for all parent IDs.
                Runs sequentially for the given child, but in parallel
                with other children.
                """
                log_msg = "{}/%v{}".format(
                    endpoint["endpoint"],
                    children_endpoint["endpoint"],
                )
                logger.info("Processing children endpoint: %s", log_msg)

                parent_ids = parent_endpoint_ids
                if (
                    children_endpoint["name"] == "wireless_ssid"
                ):  # bandaid - This child endpoint only has data for global site, so we skip every other site
                    parent_ids = [self.global_site_id]

                for parent_id in parent_ids:
                    child_dict = CiscoClientController.create_endpoint_dict(
                        children_endpoint
                    )

                    joined_endpoint = f"{endpoint['endpoint']}/{parent_id}{children_endpoint['endpoint']}"
                    data = self.fetch_data_pagination(joined_endpoint)
                    child_dict = self.process_endpoint_data(
                        children_endpoint, child_dict, data, parent_id
                    )
                    if len(child_dict.get(children_endpoint["name"], [])) > 0:
                        child_dict[children_endpoint["name"]][0]["id"] = parent_id
                    with lock:
                        for _idx, entry in enumerate(endpoint_dict[endpoint["name"]]):
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
                                        current.append(
                                            child_dict[children_endpoint["name"]]
                                        )
                                    break

                            else:
                                if entry.get("data", {}).get("id") == parent_id:
                                    entry.setdefault("children", {})[
                                        children_endpoint["name"]
                                    ] = child_dict[children_endpoint["name"]]

            with concurrent.futures.ThreadPoolExecutor() as executor:
                list(executor.map(_process_child, endpoint["children"]))
        with self.lock:
            self.db.upsert(
                {
                    "url": self.base_url,
                    "content": endpoint_dict,
                    "endpoint_name": endpoint["name"],
                    "job_start": self.start_time,
                },
                (self.job.url == self.base_url)
                & (self.job.endpoint_name == endpoint["name"]),
            )

        return endpoint_dict
