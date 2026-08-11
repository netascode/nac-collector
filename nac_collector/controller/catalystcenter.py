import concurrent.futures
import datetime
import logging
import os
import re
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
            entry = {"data": data, "endpoint": new_endpoint}
            endpoint_dict[endpoint["name"]].append(entry)
        elif data and isinstance(data.get("response"), dict):
            response_data = data.get("response")
            if response_data:
                for k, v in response_data.items():
                    if (
                        self.mappings.get(endpoint["name"])
                        and self.mappings[endpoint["name"]] == k
                    ):
                        for i in v:
                            child_entry = {
                                "data": i,
                                "endpoint": new_endpoint + "/" + self.get_id_value(i),
                            }
                            endpoint_dict[endpoint["name"]].append(child_entry)
                    else:
                        elem = {"data": v, "endpoint": new_endpoint, "name": k}
                        if id_ is not None:
                            elem["id"] = id_
                        endpoint_dict[endpoint["name"]].append(elem)

        elif isinstance(data.get("response"), list):
            response_list = data.get("response")
            entry = {"data": response_list, "endpoint": endpoint["endpoint"]}
            endpoint_dict[endpoint["name"]].append(entry)
        elif data and data.get("response"):
            response_items = data.get("response")
            if response_items:
                for i in response_items:
                    item_entry = {
                        "data": i,
                        "endpoint": new_endpoint + "/" + self.get_id_value(i),
                    }
                    endpoint_dict[endpoint["name"]].append(item_entry)

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
            id_ = self._sanitize_id(str(id_))
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
            self.attach_keyed_import_ids(final_dict, endpoints)
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
                return CiscoClientCATALYSTCENTER._sanitize_id(str(x))
        return None

    @staticmethod
    def _sanitize_id(value: str) -> str:
        """
        Strip whitespace and non-printable characters from an ID value.
        """
        return re.sub(r"[\x00-\x1f\x7f-\x9f\s]", "", value)

    @staticmethod
    def build_terraform_import_ids(
        endpoint: dict[str, Any],
        obj: dict[str, Any],
        parent_id: str | None,
    ) -> list[str] | None:
        """
        Assemble the ordered Terraform import ID parts for a single resource
        instance, following the pre-composed recipe shipped on the endpoint
        as ``import_id_attributes`` (see github_repo_wrapper.py, which ports the
        provider's ``ImportAttributes``).

        Each recipe part self-describes its source:
          - ``{"source": "parent"}`` -> the threaded parent id (``parent_id``),
            i.e. the ``%v`` path segment (e.g. site_id for wireless_ssid).
          - ``{"field": "<name>"}``  -> ``obj["<name>"]`` read from the collected
            response body (query_param/reference-with-response-body attrs, and
            the synthetic id part).

        Returns:
            list[str]: the ordered parts, joined with "," downstream by the
                consumer to form the import ID.
            None: if the endpoint has no ``import_id_attributes`` recipe
                (``no_import`` resources), or a required part is missing.
        """
        recipe = endpoint.get("import_id_attributes")
        if not recipe:
            return None

        parts: list[str] = []
        for part in recipe:
            if part.get("source") == "parent":
                if parent_id is None:
                    logger.warning(
                        "Failed to generate terraform_import_ids for endpoint %s: "
                        "missing parent id for 'source: parent' part",
                        endpoint["name"],
                    )
                    return None
                parts.append(CiscoClientCATALYSTCENTER._sanitize_id(str(parent_id)))
                continue

            field = part.get("field")
            if field is None:
                logger.warning(
                    "Failed to generate terraform_import_ids for endpoint %s: "
                    "malformed import_id_attributes part %s",
                    endpoint["name"],
                    part,
                )
                return None

            value = obj.get(field)
            if value is None:
                logger.warning(
                    "Failed to generate terraform_import_ids for endpoint %s: "
                    "missing field '%s' in the response",
                    endpoint["name"],
                    field,
                )
                return None
            parts.append(CiscoClientCATALYSTCENTER._sanitize_id(str(value)))

        return parts

    @classmethod
    def _build_site_hierarchy_index(
        cls, final_dict: dict[str, Any]
    ) -> dict[str, str]:
        """
        Map every site UUID -> its ``nameHierarchy`` path (e.g.
        ``Global/Poland/Krakow``). Built once from the collected ``site`` tree so
        the keying post-pass can resolve a leaf's ``siteId``/``fabricId`` back to
        the hierarchy string the Terraform plan indexes on.

        The ``Global`` root carries ``nameHierarchy: None`` in the API, so its
        hierarchy is synthesized as its own name (``Global``).
        """
        index: dict[str, str] = {}
        for entry in final_dict.get("site", []):
            leaves = entry.get("data")
            if not isinstance(leaves, list):
                continue
            for leaf in leaves:
                if not isinstance(leaf, dict):
                    continue
                site_id = leaf.get("id")
                if site_id is None:
                    continue
                hierarchy = leaf.get("nameHierarchy")
                if hierarchy is None and leaf.get("name") == "Global":
                    hierarchy = "Global"
                if hierarchy is not None:
                    index[str(site_id)] = str(hierarchy)
        return index

    @classmethod
    def _build_fabric_to_site_index(
        cls, final_dict: dict[str, Any]
    ) -> dict[str, str]:
        """
        Map every fabric UUID -> the site UUID it belongs to, from the collected
        ``fabric_site`` leaves (``id`` = fabric uuid, ``siteId`` = site uuid).
        Lets ``site_hierarchy`` resolve a ``fabricId`` by hopping fabric -> site
        -> hierarchy.
        """
        index: dict[str, str] = {}
        for entry in final_dict.get("fabric_site", []):
            leaves = entry.get("data")
            if not isinstance(leaves, list):
                continue
            for leaf in leaves:
                if not isinstance(leaf, dict):
                    continue
                fabric_id = leaf.get("id")
                site_id = leaf.get("siteId")
                if fabric_id is not None and site_id is not None:
                    index[str(fabric_id)] = str(site_id)
        return index

    @classmethod
    def _build_device_hostname_index(
        cls, final_dict: dict[str, Any]
    ) -> dict[str, str]:
        """
        Map every network-device UUID -> its short hostname (the segment before
        the first dot, e.g. ``BR10.cisco.eu`` -> ``BR10``), from the collected
        ``network_devices`` leaves. Lets ``device_hostname`` resolve a leaf's
        ``networkDeviceId`` to the name the Terraform plan indexes on.
        """
        index: dict[str, str] = {}
        for entry in final_dict.get("network_devices", []):
            leaves = entry.get("data")
            if not isinstance(leaves, list):
                continue
            for leaf in leaves:
                if not isinstance(leaf, dict):
                    continue
                dev_id = leaf.get("id")
                hostname = leaf.get("hostname")
                if dev_id is not None and hostname is not None:
                    index[str(dev_id)] = str(hostname).split(".")[0]
        return index

    @staticmethod
    def _group_wrapper_leaves(obj: dict[str, Any]) -> list[Any] | None:
        """
        Detect a lookup group-wrapper and return its nested leaf list.

        Endpoints fetched via ``resources/lookups/catalystcenter.yaml`` (the
        nested handoffs — layer2Handoffs, layer3Handoffs/ipTransits|sdaTransits)
        are stored by ``fetch_data_alternate`` as a list of *group wrappers*, each
        carrying the group key (``fabricId`` or ``siteId``) alongside the API
        ``response`` nested under ``response`` or ``data``. The recipe fields
        (``networkDeviceId``, ``fabricId``, ``id``) live on the *leaf*, not the
        wrapper, so the consumer must descend one level before applying the recipe.

        Returns the leaf list when ``obj`` looks like such a wrapper (a small dict
        of exactly {group key(s)} + one nested list), else ``None`` for a flat leaf
        (e.g. ``fabric_port_assignments``) that carries the recipe fields directly.
        """
        nested = None
        for list_key in ("response", "data"):
            val = obj.get(list_key)
            if isinstance(val, list):
                nested = val
                break
        if nested is None:
            return None
        # A genuine wrapper's only non-list keys are group keys (uuids), never the
        # recipe fields. If the object itself carries recipe-shaped fields, treat it
        # as a flat leaf instead.
        if obj.get("networkDeviceId") is not None:
            return None
        return nested

    @classmethod
    def _resolve_key_part(
        cls,
        part: dict[str, Any],
        leaf: dict[str, Any],
        parent_id: str | None,
        indices: dict[str, dict[str, str]],
    ) -> str | None:
        """
        Resolve one ``import_id_key`` part to its natural-key string.

        Supported source kinds:
          - ``{"field": "<name>"}``        -> ``leaf["<name>"]`` verbatim.
          - ``{"source": "parent"}``       -> the threaded ``parent_id``.
          - ``{"site_hierarchy": "<f>"}``  -> resolve the uuid in ``leaf["<f>"]``
            (a siteId, or a fabricId hopped via fabric->site) to its hierarchy
            path (e.g. ``Global/Poland/Krakow``).
          - ``{"device_hostname": "<f>"}`` -> resolve the network-device uuid in
            ``leaf["<f>"]`` to its short hostname (e.g. ``BR10``).

        Returns the resolved string, or ``None`` if a required source is missing
        (the caller then omits the whole entry's key).
        """
        if "field" in part:
            value = leaf.get(part["field"])
            return None if value is None else str(value)
        if part.get("source") == "parent":
            return None if parent_id is None else str(parent_id)
        if "site_hierarchy" in part:
            uuid = leaf.get(part["site_hierarchy"])
            if uuid is None:
                # child entries carry the site id at entry level, not on the leaf
                uuid = parent_id
            if uuid is None:
                return None
            uuid = str(uuid)
            site_index = indices["site_hierarchy"]
            if uuid in site_index:
                return site_index[uuid]
            fabric_index = indices["fabric_to_site"]
            site_id = fabric_index.get(uuid)
            if site_id is not None and site_id in site_index:
                return site_index[site_id]
            return None
        if "device_hostname" in part:
            uuid = leaf.get(part["device_hostname"])
            if uuid is None:
                return None
            return indices["device_hostname"].get(str(uuid))
        return None

    @classmethod
    def _build_natural_key(
        cls,
        key_spec: dict[str, Any],
        leaf: dict[str, Any],
        parent_id: str | None,
        indices: dict[str, dict[str, str]],
    ) -> str | None:
        """
        Build the full natural key (the string the Terraform plan indexes on) for
        one ``leaf``, following the endpoint's ``import_id_key`` spec.

        ``{"field": ...}`` is the single-field shortcut; ``{"join": [parts...],
        "sep": "..."}`` composes several resolved parts. Returns ``None`` (so the
        entry's key is omitted) if any required part cannot be resolved.
        """
        if "join" in key_spec:
            sep = key_spec.get("sep", ",")
            resolved: list[str] = []
            for part in key_spec["join"]:
                value = cls._resolve_key_part(part, leaf, parent_id, indices)
                if value is None:
                    return None
                resolved.append(value)
            return sep.join(resolved)
        return cls._resolve_key_part(key_spec, leaf, parent_id, indices)

    @staticmethod
    def _flatten_key_leaves(obj: Any) -> list[dict[str, Any]]:
        """
        Descend one collected ``data`` object to its importable leaf dicts.

        Handles the three shapes the collector produces:
          - a flat leaf dict carrying the recipe fields directly;
          - a lookup group-wrapper (``{fabricId|siteId, response|data:[leaf,…]}``)
            whose real leaves are one level down (nested handoffs);
          - the ``template_version`` double-nest (``{templateId, data:[{name,
            versionsInfo:[…]}]}``) whose importable leaf is the inner ``name``
            object.
        Returns the list of leaf dicts (possibly just ``[obj]``).
        """
        if not isinstance(obj, dict):
            return []
        leaves = CiscoClientCATALYSTCENTER._group_wrapper_leaves(obj)
        if leaves is None:
            return [obj]
        flattened: list[dict[str, Any]] = []
        for leaf in leaves:
            if not isinstance(leaf, dict):
                continue
            inner = leaf.get("data")
            if isinstance(inner, list) and inner and "templateId" in leaf:
                flattened.extend(x for x in inner if isinstance(x, dict))
            else:
                flattened.append(leaf)
        return flattened

    @staticmethod
    def _group_list_leaves(obj: Any, sub_field: str) -> list[dict[str, Any]]:
        """
        Expand one shared grouped-object response into the leaves of a sub-list.

        The credential/role/user endpoints return a single object whose kinds are
        parallel sub-lists (``cliCredential``, ``snmpV2cRead``, … / ``roles`` /
        ``users``), each element carrying its own id + a human name the module
        indexes on. A given terraform_type maps to exactly one sub-list, so the
        keyed pass selects ``obj[sub_field]`` and treats each element as a leaf
        (the recipe reads its ``id``/``roleId``/``userId``; the key reads its
        ``description``/``role``/``username``). Returns ``[]`` when the sub-list
        is absent or empty.
        """
        if not isinstance(obj, dict):
            return []
        sub = obj.get(sub_field)
        if not isinstance(sub, list):
            return []
        return [x for x in sub if isinstance(x, dict)]


    @staticmethod
    def _validate_key_spec_dialect(
        name: str | None, key_spec: Any
    ) -> None:
        """
        Enforce that an ``import_id_key`` uses exactly ONE dialect.

        The three dialects are mutually exclusive:
          - ``{group: <subListField>, key_field: ...}``  (grouped sub-list)
          - ``{join: [parts...], sep: ...}``             (composite key)
          - ``{field: ...}``                             (single-field shortcut)

        ``attach_keyed_import_ids`` checks ``group`` first and returns early, so a
        spec that mixes ``group`` with ``join``/``field`` would silently ignore the
        latter. Raise loudly instead -- a mixed spec is always an authoring error.
        """
        if not isinstance(key_spec, dict):
            raise ValueError(
                f"import_id_key for endpoint {name!r} must be a mapping, "
                f"got {type(key_spec).__name__}"
            )
        present = [d for d in ("group", "join", "field") if d in key_spec]
        if len(present) > 1:
            raise ValueError(
                f"import_id_key for endpoint {name!r} mixes mutually exclusive "
                f"dialects {present}; use exactly one of group/join/field"
            )

    def attach_keyed_import_ids(
        self, final_dict: dict[str, Any], endpoints: list[dict[str, Any]]
    ) -> None:
        """
        Post-pass: replace every entry's ``terraform_import_ids`` with a dict
        keyed by the natural key the Terraform plan indexes on
        (``change["index"]``), mapping to the already-comma-joined composite
        import id::

            entry["terraform_import_ids"] = { "<index>": "<joined,id>", … }

        Runs once after all endpoints are collected so the cross-endpoint joins
        (device hostname, site hierarchy) can see ``network_devices`` and the
        ``site`` tree. Entries whose endpoint has no ``import_id_key`` (fixed
        singletons, ``no_import`` resources) are left untouched.
        """
        indices = {
            "site_hierarchy": self._build_site_hierarchy_index(final_dict),
            "fabric_to_site": self._build_fabric_to_site_index(final_dict),
            "device_hostname": self._build_device_hostname_index(final_dict),
        }

        def _key_entry(endpoint: dict[str, Any], entry: dict[str, Any]) -> None:
            """Attach the keyed ``terraform_import_ids`` dict to one entry."""
            key_spec = endpoint.get("import_id_key")
            if key_spec is None or not isinstance(entry, dict):
                return
            self._validate_key_spec_dialect(endpoint.get("name"), key_spec)
            parent_id = entry.get("id")
            keyed: dict[str, str] = {}
            objs = entry.get("data")
            obj_list = objs if isinstance(objs, list) else [objs]

            # Group C -- grouped/nested object: one shared response expands into
            # the leaves of a single sub-list, each keyed on ``key_field`` (its
            # own name) and importing its own id via the recipe. No cross-endpoint
            # join, so the key is the element's ``key_field`` verbatim.
            group = key_spec.get("group") if isinstance(key_spec, dict) else None
            if group is not None:
                key_field = key_spec["key_field"]
                for obj in obj_list:
                    for leaf in self._group_list_leaves(obj, group):
                        name = leaf.get(key_field)
                        if name is None:
                            continue
                        parts = self.build_terraform_import_ids(
                            endpoint, leaf, parent_id
                        )
                        if parts is None:
                            continue
                        keyed[str(name)] = ",".join(parts)
                entry["terraform_import_ids"] = keyed
                return

            # Group B -- wrapper-keyed types (assign_credentials, fabric_device,
            # vlanToSsids) carry the key/id field (``siteId``) on the *wrapper*;
            # their inner ``data``/``response`` leaves do not, so descent must be
            # suppressed and the wrapper itself used as the leaf.
            no_descend = bool(endpoint.get("import_id_no_descend"))
            for obj in obj_list:
                leaves = [obj] if no_descend else self._flatten_key_leaves(obj)
                for leaf in leaves:
                    key = self._build_natural_key(
                        key_spec, leaf, parent_id, indices
                    )
                    if key is None:
                        continue
                    parts = self.build_terraform_import_ids(
                        endpoint, leaf, parent_id
                    )
                    if parts is None:
                        continue
                    keyed[key] = ",".join(parts)
            entry["terraform_import_ids"] = keyed

        def _collect_child_entries(
            parent_entries: list[Any], child_name: str
        ) -> list[dict[str, Any]]:
            """
            Flatten a child endpoint's entries out of the parent entries'
            ``children`` bucket. Child data is stored as a list of lists of entry
            dicts (one inner list per parent instance), never at the top level of
            ``final_dict``.
            """
            out: list[dict[str, Any]] = []
            for parent in parent_entries:
                if not isinstance(parent, dict):
                    continue
                bucket = parent.get("children", {}).get(child_name)
                if not isinstance(bucket, list):
                    continue
                for group in bucket:
                    if isinstance(group, list):
                        out.extend(x for x in group if isinstance(x, dict))
                    elif isinstance(group, dict):
                        out.append(group)
            return out

        def _walk(
            endpoint: dict[str, Any], entries: list[Any]
        ) -> None:
            for entry in entries:
                _key_entry(endpoint, entry)
            for child in endpoint.get("children", []):
                child_entries = _collect_child_entries(entries, child["name"])
                _walk(child, child_entries)

        for endpoint in endpoints:
            _walk(endpoint, final_dict.get(endpoint["name"], []))

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
                    sanitized_parent_id = self._sanitize_id(str(parent_id))
                    child_dict = CiscoClientController.create_endpoint_dict(
                        children_endpoint
                    )

                    joined_endpoint = f"{endpoint['endpoint']}/{sanitized_parent_id}{children_endpoint['endpoint']}"
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
