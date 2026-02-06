import asyncio
import logging
import os
from json import JSONDecodeError
from typing import Any

from meraki.aio.rest_session import AsyncRestSession
from meraki.exceptions import AsyncAPIError
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from nac_collector.cli import console
from nac_collector.controller.base import CiscoClientController

logger = logging.getLogger("main")

# Suppress urllib3 warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)


class CiscoClientMERAKI(CiscoClientController):
    """
    This class inherits from the abstract class CiscoClientController. It's used for authenticating
    with the Cisco MERAKI API and retrieving data from various endpoints.
    This is a single step authentication.
     - API Token / Key is used for all queries - must be passed via "password" argument.
    """

    SOLUTION = "meraki"

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
            username,
            password,
            base_url,
            max_retries,
            retry_after,
            timeout,
            ssl_verify,
        )

        self.allowed_org_ids: list[str] | None = None
        allowed_org_ids_env = os.getenv("NAC_MERAKI_ORG_IDS", "")
        if allowed_org_ids_env != "":
            self.allowed_org_ids = allowed_org_ids_env.split(",")

    def authenticate(self) -> bool:
        """
        Check whether an API key is set (as password).
        Do nothing otherwise. -
        the Meraki session will be created in the async context
        when get_from_endpoints_data() is run.
        """

        if not self.password:
            logger.error(
                'API key (passed via "password") is required for authentication.'
            )
            return False

        return True

    async def init_session(self) -> None:
        """
        Create an async Meraki SDK Rest session.
        """

        # TODO Use self.ssl_verify, self.timeout?
        self.session = AsyncRestSession(
            logger, self.password, caller="NacCollector netascode"
        )
        self.request_throttle_semaphore = asyncio.Semaphore(1)
        self.request_throttle_delay = 0.1  # 10 requests per second rate limit
        self.total_requests = 0
        logger.info("Created Meraki REST session successful with API key.")

    async def close_session(self) -> None:
        """
        Close the async Meraki SDK Rest session.
        """

        await self.session.close()

    def process_endpoint_data(
        self,
        endpoint: dict[str, Any],
        endpoint_dict: dict[str, Any],
        data: dict[str, Any] | list[Any] | None,
        err_data: dict[str, Any] | None,
        parent_ids: list[str | int],
    ) -> dict[str, Any]:
        """
        Process the data for a given endpoint and update the endpoint_dict.

        Parameters:
            endpoint (dict): The endpoint configuration.
            endpoint_dict (dict): The dictionary to store processed data.
            data (dict or list or None): The data fetched from the endpoint (mutually exclusive with err_data).
            err_data (dict or None): The error message fetched from the endpoint (mutually exclusive with data).

        Returns:
            dict: The updated endpoint dictionary with processed data.
        """

        if data is None:
            endpoint_dict[endpoint["name"]] = {
                "error": err_data,
                "endpoint": endpoint["endpoint"],
            }
            return endpoint_dict

        # The response is a single resource instance.
        if isinstance(data, dict) and "items" not in data:
            endpoint_dict[endpoint["name"]] = self.process_single_resource_data(
                data, endpoint, parent_ids
            )
            return endpoint_dict

        # The response has multiple resource instances.

        if isinstance(data, list):
            items = data
        else:
            items = data["items"]
            if not isinstance(items, list):
                items = []

        for item in items:
            endpoint_dict[endpoint["name"]].append(
                self.process_single_resource_data(item, endpoint, parent_ids)
            )

        return endpoint_dict  # Return the processed endpoint dictionary

    @staticmethod
    def process_single_resource_data(
        data: dict[str, Any], endpoint: dict[str, Any], parent_ids: list[str | int]
    ) -> dict[str, Any]:
        result = {
            "data": data,
            "endpoint": endpoint["endpoint"],
        }

        terraform_import_ids = None
        if CiscoClientMERAKI.endpoint_has_own_id(endpoint):
            id = CiscoClientMERAKI.get_id_value(data, endpoint)
            # TODO If get_id_value() return None, this just gets put into the string as "/None".
            result["endpoint"] = f"{endpoint['endpoint']}/{id}"
            if id is not None:
                terraform_import_ids = parent_ids + [id]
        else:
            terraform_import_ids = parent_ids
        result["terraform_import_ids"] = terraform_import_ids

        return result

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

        return asyncio.run(self.async_get_from_endpoints_data(endpoints_data))

    async def async_get_from_endpoints_data(
        self, endpoints_data: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Asynchronously retrieve data from a list of endpoint definitions provided as data structure.
        """

        await self.init_session()

        # Initialize an empty dictionary
        final_dict = {}

        # Iterate over all endpoints
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            "requests done.",
            "Time elapsed:",
            TimeElapsedColumn(),
            "Time remaining (estimated):",
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            progress_task = progress.add_task("Fetching Meraki endpoints:", start=False)
            # Note: there is only one top-level endpoint: organization
            for endpoint in endpoints_data:
                endpoint_dict = CiscoClientController.create_endpoint_dict(endpoint)

                data, err_data = await self.fetch_data_with_error(
                    endpoint["endpoint"], progress, progress_task
                )

                data = self.filter_organizations(endpoint, data)

                endpoint_dict = self.process_endpoint_data(
                    endpoint,
                    endpoint_dict,
                    data,
                    err_data,
                    [],
                )

                if endpoint.get("children"):
                    await self.get_from_children_endpoints(
                        endpoint,
                        endpoint["endpoint"],
                        endpoint_dict[endpoint["name"]],
                        [],
                        {},
                        progress,
                        progress_task,
                    )

                # Save results to dictionary
                final_dict.update(endpoint_dict)

        await self.close_session()

        return final_dict

    def filter_organizations(
        self, endpoint: dict[str, Any], data: dict[str, Any] | list[Any] | None
    ) -> dict[str, Any] | list[Any] | None:
        if endpoint["name"] != "organization":
            return data

        if not isinstance(data, list):
            return data

        if self.allowed_org_ids is None:
            return data

        return [
            org
            for org in data
            if self.get_id_value(org, endpoint) in self.allowed_org_ids
        ]

    async def get_from_children_endpoints(
        self,
        parent_endpoint: dict[str, Any],
        parent_endpoint_uri: str,
        parent_endpoint_dict: list[dict[str, Any]] | dict[str, Any],
        grandparent_endpoints_ids: list[str | int],
        grandparent_conditions: dict[str, Any],
        progress: Progress,
        progress_task: TaskID,
    ) -> None:
        if isinstance(parent_endpoint_dict, dict):
            logger.info(
                "Skipping fetching children of %s (%s) as it returned no data",
                parent_endpoint["name"],
                parent_endpoint_uri,
            )
            return

        items: list[dict[str, Any]] = parent_endpoint_dict

        parent_instances = []
        for item in items:
            # Add the item's id to the list
            parent_id = self.get_id_value(item["data"], parent_endpoint)
            if parent_id is None:
                continue
            conditions = self.get_parent_conditions(
                item["data"], parent_endpoint, grandparent_conditions
            )
            parent_instance = {
                "endpoint_dict": item,
                "id": parent_id,
                "conditions": conditions,
            }
            parent_instances.append(parent_instance)

        if parent_endpoint.get("root"):
            # Use the parent as the root in the URI, ignoring the parent's parent.
            parent_endpoint_uri = parent_endpoint["endpoint"]
            # Ignore the parent's parent's ID.
            grandparent_endpoints_ids = []

        # Sort endpoints so that requests for children are queued first
        # so that the total number of requests for the progress bar hopefully becomes correct sooner.
        child_endpoints = self.sort_endpoints_with_children_first(
            parent_endpoint["children"]
        )

        await asyncio.gather(
            *(
                self.get_child_endpoint_for_parent_instance(
                    parent_endpoint_uri,
                    grandparent_endpoints_ids,
                    parent_instance,
                    children_endpoint,
                    progress,
                    progress_task,
                )
                for children_endpoint in child_endpoints
                for parent_instance in parent_instances
            )
        )

    async def get_child_endpoint_for_parent_instance(
        self,
        parent_endpoint_uri: str,
        grandparent_endpoints_ids: list[str | int],
        parent_instance: dict[str, Any],
        children_endpoint: dict[str, Any],
        progress: Progress,
        progress_task: TaskID,
    ) -> None:
        parent_id = parent_instance["id"]
        parent_conditions = parent_instance["conditions"]
        parent_instance_endpoint_dict = parent_instance["endpoint_dict"]

        children_endpoint_uri = (
            f"{parent_endpoint_uri}/{parent_id}{children_endpoint['endpoint']}"
        )

        should_skip, reason = self.should_skip_by_parent_conditions(
            children_endpoint, parent_conditions
        )
        if should_skip:
            logger.info(
                "Skipping fetching %s (%s): %s",
                children_endpoint["name"],
                children_endpoint_uri,
                reason,
            )
            return

        children_endpoint_dict = CiscoClientController.create_endpoint_dict(
            children_endpoint
        )

        data, err_data = await self.fetch_data_with_error(
            children_endpoint_uri, progress, progress_task
        )

        # Process the children endpoint data and get the updated dictionary
        children_endpoint_dict = self.process_endpoint_data(
            children_endpoint,
            children_endpoint_dict,
            data,
            err_data,
            grandparent_endpoints_ids + [parent_id],
        )

        if children_endpoint.get("children"):
            await self.get_from_children_endpoints(
                children_endpoint,
                children_endpoint_uri,
                children_endpoint_dict[children_endpoint["name"]],
                grandparent_endpoints_ids + [parent_id],
                parent_conditions,
                progress,
                progress_task,
            )

        parent_instance_endpoint_dict.setdefault("children", {})[
            children_endpoint["name"]
        ] = children_endpoint_dict[children_endpoint["name"]]

    async def fetch_data_with_error(
        self,
        uri: str,
        progress: Progress,
        progress_task: TaskID,
    ) -> tuple[dict[str, Any] | list[Any] | None, dict[str, Any] | None]:
        self.total_requests += 1
        progress.update(progress_task, total=self.total_requests)

        try:
            metadata = {
                "tags": ["no tag"],
                "operation": "no operation",
            }
            # Ensure only 10 requests are started per second.
            # This honors the rate limit (without taking into account the burst allowance).
            async with self.request_throttle_semaphore:
                await asyncio.sleep(self.request_throttle_delay)
            data = await self.session.get_pages(metadata, uri)
            return data, None
        except AsyncAPIError as e:
            return None, {
                "status_code": e.status,
                "message": e.message,
            }
        except JSONDecodeError as e:
            # For a 404 Not Found response,
            # RestSession raises a normal APIError,
            # with e.message being either decoded JSON or response text if decoding fails.
            # AsyncRestSession, though, tries to parse 404 response's body
            # (which can often be HTML instead of JSON) unconditionally
            # and does not handle the exception.
            # Catch the exception here, but the response code is already lost.
            return None, {
                "message": f"JSON decode error: {str(e)}",
            }
        finally:
            progress.start_task(progress_task)
            progress.update(progress_task, advance=1)

    @staticmethod
    def sort_endpoints_with_children_first(
        endpoints: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Return endpoints, with endpoints that have children first, then ones that don't.
        """
        endpoints_with_children = [
            endpoint for endpoint in endpoints if endpoint.get("children")
        ]
        endpoints_without_children = [
            endpoint for endpoint in endpoints if not endpoint.get("children")
        ]
        return endpoints_with_children + endpoints_without_children

    @staticmethod
    def endpoint_has_own_id(endpoint: dict[str, Any]) -> bool:
        result: bool = endpoint.get("has_own_id", False)
        return result

    @staticmethod
    def endpoint_id_property(endpoint: dict[str, Any]) -> str:
        result: str = endpoint.get("id_name", "id")
        return result

    @staticmethod
    def get_id_value(i: dict[str, Any], endpoint: dict[str, Any]) -> str | int | None:
        """
        Attempts to get the ID from an API resource's response.

        Parameters:
            i (dict): The resource response.
            endpoint (dict): The endpoint configuration.

        Returns:
            str or int or None: The ID if it exists (str or int),
                                None if the endpoint does not have its own ID or the ID field is missing.
        """

        id_name = CiscoClientMERAKI.endpoint_id_property(endpoint)
        try:
            return (
                i[id_name]
                if (isinstance(i[id_name], str) or isinstance(i[id_name], int))
                else None
            )
        except KeyError:
            return None

    @staticmethod
    def get_parent_conditions(
        parent_data: dict[str, Any],
        parent_endpoint: dict[str, Any],
        grandparent_conditions: dict[str, Any],
    ) -> dict[str, Any]:
        result = grandparent_conditions.copy()

        if parent_endpoint["name"] == "device":
            result["device_type"] = parent_data.get("productType")
            result["device_model"] = parent_data.get("model")

        return result

    @staticmethod
    def should_skip_by_parent_conditions(
        children_endpoint: dict[str, Any], parent_conditions: dict[str, Any]
    ) -> tuple[bool, str]:
        allowed_device_types = children_endpoint.get("allowed_device_types")
        device_type = parent_conditions.get("device_type")
        if (
            allowed_device_types is not None
            and device_type is not None
            and device_type not in allowed_device_types
        ):
            return True, f"the endpoint is not applicable for device type {device_type}"

        allowed_device_models = children_endpoint.get("allowed_device_models")
        device_model = parent_conditions.get("device_model")
        if allowed_device_models is not None and device_model is not None:
            if not any(
                device_model.startswith(allowed_model_prefix)
                for allowed_model_prefix in allowed_device_models
            ):
                return (
                    True,
                    f"the endpoint is not applicable for device model {device_model}",
                )

        return False, ""
