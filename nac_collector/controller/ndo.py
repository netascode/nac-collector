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


class CiscoClientNDO(CiscoClientController):
    NDO_AUTH_ENDPOINT = "/login"
    SOLUTION = "ndo"

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
        self.domain = "DefaultAuth"
        super().__init__(
            username, password, base_url, max_retries, retry_after, timeout, ssl_verify
        )

    def authenticate(self) -> bool:
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

        self.client = httpx.Client(
            verify=self.ssl_verify,
            timeout=self.timeout,
        )

        response = self.client.post(auth_url, json=data)

        if response.status_code != 200:
            logger.error(
                "Authentication failed with status code: %s",
                response.status_code,
            )
            return False
        return True

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
            for endpoint in endpoints:
                progress.advance(task)
                if all(x not in endpoint.get("endpoint", "") for x in ["%v", "%i"]):  # noqa
                    endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)
                    response = self.get_request(self.base_url + endpoint["endpoint"])  # noqa
                    if response is None:
                        continue
                    data = response.json()
                    key = endpoint["name"]

                    if isinstance(data, dict):
                        next_key = next(iter(data))
                        if key == next_key:
                            data = data[next_key]

                    endpoint_dict[key] = data if isinstance(data, list) else data

                    final_dict.update(endpoint_dict)

                else:
                    parent_endpoint: dict[str, Any] | str = ""
                    parent_path = "/".join(endpoint.get("endpoint", "").split("/")[:-1])  # noqa
                    for e in endpoints:
                        if parent_path in e.get("endpoint", "") and e != endpoint:
                            parent_endpoint = e
                            break
                    if (
                        isinstance(parent_endpoint, dict)
                        and parent_endpoint.get("name") in final_dict
                    ):  # noqa
                        endpoint_dict = CiscoClientController.create_endpoint_dict(
                            endpoint
                        )

                        r = []

                        parent_data = final_dict.get(parent_endpoint["name"])
                        if not isinstance(parent_data, list | tuple):
                            continue

                        for tmpl in parent_data:
                            if isinstance(tmpl, dict) and "templateId" in tmpl:
                                response_inner = self.get_request(
                                    self.base_url
                                    + endpoint["endpoint"].replace(
                                        "%v", tmpl.get("templateId", "")
                                    )
                                )  # noqa
                                if response_inner is None:
                                    continue
                                data = response_inner.json()
                            else:
                                continue
                            r.append(data)

                        final_dict.update({endpoint["name"]: r})
        return final_dict
