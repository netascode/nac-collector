import logging
import json
import requests
import urllib3

from nac_collector.cisco_client import CiscoClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("main")

# Suppress urllib3 warnings
logging.getLogger("urllib3").setLevel(logging.ERROR)


class CiscoClientNDFC(CiscoClient):
    """
    This class inherits from the abstract class CiscoClient. It's used for authenticating
    with the Cisco Nexus Dashboard Fabric Controller (NDFC) API and retrieving data from various endpoints.
    Authentication is token-based using domain, username, and password credentials.
    A session is created upon successful authentication for subsequent requests.
    """

    NDFC_AUTH_ENDPOINT = "/login"
    SOLUTION = "ndfc"

    def __init__(
        self,
        username,
        password,
        base_url,
        max_retries,
        retry_after,
        timeout,
        ssl_verify,
        domain="local",
        fabric_name=None,
    ):
        super().__init__(
            username, password, base_url, max_retries, retry_after, timeout, ssl_verify
        )
        self.domain = domain
        self.fabric_name = fabric_name
        self.auth_cookie = None

    def authenticate(self):
        """
        Perform token-based authentication with NDFC.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """
        auth_url = f"{self.base_url}{self.NDFC_AUTH_ENDPOINT}"

        # Prepare authentication payload
        auth_payload = {
            "domain": self.domain,
            "userName": self.username,
            "userPasswd": self.password,
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        logger.debug("Attempting authentication to NDFC at: %s", auth_url)
        logger.debug(
            "Authentication payload: %s",
            {
                "domain": self.domain,
                "userName": self.username,
                "userPasswd": "***REMOVED***",
            },
        )

        try:
            response = requests.post(
                auth_url,
                data=json.dumps(auth_payload),
                headers=headers,
                verify=self.ssl_verify,
                timeout=self.timeout,
            )

            logger.debug(
                "Authentication response status code: %s", response.status_code
            )
            logger.debug("Authentication response headers: %s", dict(response.headers))

            if response and response.status_code == 200:
                logger.info("Authentication successful for NDFC URL: %s", auth_url)

                # Parse response to get token
                response_data = response.json()
                logger.debug("Authentication response data: %s", response_data)

                # NDFC typically returns the token in the response
                # The exact key may vary, common patterns are 'token', 'access_token', or 'Jwt_Token'
                token = None
                for token_key in ["token", "access_token", "Jwt_Token", "jwttoken"]:
                    if token_key in response_data:
                        token = response_data[token_key]
                        logger.debug("Found token with key: %s...", token_key[:5])
                        break

                if not token:
                    logger.error("No valid token found in authentication response")
                    logger.debug(
                        "Available keys in response: %s", list(response_data.keys())
                    )
                    return False

                # Extract AuthCookie from response headers for future API calls
                auth_cookie = None
                set_cookie_header = response.headers.get("Set-Cookie")
                if set_cookie_header:
                    # Parse AuthCookie from Set-Cookie header
                    for cookie in set_cookie_header.split(","):
                        if "AuthCookie=" in cookie:
                            auth_cookie = cookie.split("AuthCookie=")[1].split(";")[0]
                            break

                if auth_cookie:
                    self.auth_cookie = auth_cookie
                    logger.debug("Extracted AuthCookie for future API calls")
                else:
                    logger.warning("No AuthCookie found in response headers")

                # Create a session after successful authentication
                self.session = requests.Session()
                self.session.headers.update(
                    {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}",
                    }
                )

                # Add AuthCookie to session if available
                if self.auth_cookie:
                    self.session.cookies.set("AuthCookie", self.auth_cookie)

                logger.debug(
                    "Session headers configured: %s", dict(self.session.headers)
                )
                logger.info("NDFC authentication completed successfully")

                return True

            else:
                logger.error(
                    "NDFC authentication failed with status code: %s",
                    response.status_code,
                )
                if response.text:
                    logger.debug("Authentication error response: %s", response.text)
                return False

        except requests.exceptions.Timeout:
            logger.error(
                "Authentication request timed out after %s seconds", self.timeout
            )
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error during authentication: %s", str(e))
            return False
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to decode JSON response during authentication: %s", str(e)
            )
            return False
        except Exception as e:
            logger.error("Unexpected error during authentication: %s", str(e))
            return False

    def fetch_and_save_fabric_settings(self):
        """
        Fetch fabric settings for the specified fabric and save to JSON file.
        Uses AuthCookie for authentication.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.fabric_name:
            logger.error("No fabric name provided for fabric settings retrieval")
            return False

        if not self.session:
            logger.error("No authenticated session available")
            return False

        # Construct the fabric settings API endpoint
        logger.info("Fetching fabric settings for fabric: %s", self.fabric_name)

        try:
            # Make the API call using the parent class fetch_data method
            fabric_endpoint = f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics/{self.fabric_name}"
            fabric_data = self.fetch_data(fabric_endpoint)

            if fabric_data is not None:
                logger.info(
                    "Successfully retrieved fabric settings for: %s",
                    self.fabric_name,
                )
                logger.debug(
                    "Fabric settings data keys: %s",
                    list(fabric_data.keys())
                    if isinstance(fabric_data, dict)
                    else "Non-dict response",
                )

                # Save fabric settings to JSON file using parent class method
                filename = f"NDFC_{self.fabric_name}_fabric_settings.json"
                self.write_to_json(fabric_data, filename)

                logger.info("Fabric settings saved to: %s", filename)
                return True

            else:
                logger.error("Failed to fetch fabric settings")
                return False

        except Exception as e:
            logger.error(
                "Unexpected error during fabric settings retrieval: %s", str(e)
            )
            return False

    def process_endpoint_data(self, endpoint, endpoint_dict, data, id_=None):
        """
        Process the data for a given endpoint and update the endpoint_dict.
        This is a basic implementation that can be extended based on NDFC API response patterns.

        Parameters:
            endpoint (dict): The endpoint configuration.
            endpoint_dict (dict): The dictionary to store processed data.
            data (dict or list): The data fetched from the endpoint.
            id_ (str, optional): Optional ID parameter.

        Returns:
            dict: The updated endpoint dictionary with processed data.
        """

        if data is None:
            endpoint_dict[endpoint["name"]].append(
                {"data": {}, "endpoint": endpoint["endpoint"]}
            )
            return endpoint_dict

        # Handle different response patterns from NDFC
        if isinstance(data, list):
            # Direct list response
            endpoint_dict[endpoint["name"]].append(
                {"data": data, "endpoint": endpoint["endpoint"]}
            )
        elif isinstance(data, dict):
            # Check for common NDFC response patterns
            if "data" in data:
                # Response has a 'data' wrapper
                endpoint_dict[endpoint["name"]].append(
                    {"data": data["data"], "endpoint": endpoint["endpoint"]}
                )
            elif "response" in data:
                # Response has a 'response' wrapper
                endpoint_dict[endpoint["name"]].append(
                    {"data": data["response"], "endpoint": endpoint["endpoint"]}
                )
            else:
                # Direct object response
                endpoint_dict[endpoint["name"]].append(
                    {"data": data, "endpoint": endpoint["endpoint"]}
                )

        return endpoint_dict

    def get_from_endpoints(self, endpoints_yaml_file):
        """
        Retrieve data from a list of endpoints specified in a YAML file and
        run GET requests to download data from NDFC controller.

        Parameters:
            endpoints_yaml_file (str): The name of the YAML file containing the endpoints.

        Returns:
            dict: Dictionary containing the collected data from all endpoints.
        """
        logger.info("Loading NDFC API endpoints from %s", endpoints_yaml_file)

        try:
            with open(endpoints_yaml_file, "r", encoding="utf-8") as f:
                endpoints = self.yaml.load(f)
        except FileNotFoundError:
            logger.error("API Endpoints file not found: %s", endpoints_yaml_file)
            return {}
        except Exception as e:
            logger.error("Error loading API endpoints file: %s", str(e))
            return {}

        if not endpoints:
            logger.warning("No API endpoints found in %s", endpoints_yaml_file)
            return {}

        # Initialize the result dictionary
        endpoint_dict = {}

        logger.info("Processing %d API endpoints", len(endpoints))

        for endpoint in endpoints:
            if (
                not isinstance(endpoint, dict)
                or "name" not in endpoint
                or "endpoint" not in endpoint
            ):
                logger.warning(
                    "Skipping invalid API endpoint configuration: %s", endpoint
                )
                continue

            endpoint_name = endpoint["name"]
            endpoint_url = endpoint["endpoint"]

            # Replace %v placeholder with actual fabric name if provided
            if self.fabric_name and "%v" in endpoint_url:
                endpoint_url = endpoint_url.replace("%v", self.fabric_name)
                logger.debug("Replaced %v in URL: %s", endpoint_url)

            # Check if this is a Policies endpoint that requires filtering by discovered switch serial numbers
            if endpoint_name == "Policies" and "/policies" in endpoint_url:
                logger.info(
                    "Processing Policies endpoint with client-side serial number filtering"
                )
                self._process_policies_endpoint_with_filtering(endpoint, endpoint_dict)
                continue

            # Initialize list for this endpoint if not exists
            if endpoint_name not in endpoint_dict:
                endpoint_dict[endpoint_name] = []

            logger.info("Fetching data from endpoint: %s", endpoint_name)
            logger.debug("Endpoint URL: %s", endpoint_url)

            try:
                # Make the API request using the parent class fetch_data method
                data = self.fetch_data(endpoint_url)

                if data is not None:
                    logger.info("Successfully retrieved data from %s", endpoint_name)
                    logger.debug(
                        "Response data keys: %s",
                        list(data.keys())
                        if isinstance(data, dict)
                        else f"List with {len(data)} items"
                        if isinstance(data, list)
                        else "Non-dict/list response",
                    )

                    # Process the data using the existing process_endpoint_data method
                    endpoint_dict = self.process_endpoint_data(
                        endpoint, endpoint_dict, data
                    )

                else:
                    logger.error("Failed to fetch data from %s", endpoint_name)
                    # Add empty data entry for failed request
                    endpoint_dict[endpoint_name].append(
                        {
                            "data": {},
                            "endpoint": endpoint_url,
                            "error": "Failed to fetch data",
                        }
                    )

            except Exception as e:
                logger.error(
                    "Unexpected error fetching data from %s: %s", endpoint_name, str(e)
                )
                endpoint_dict[endpoint_name].append(
                    {"data": {}, "endpoint": endpoint_url, "error": str(e)}
                )

        logger.info("NDFC data collection completed from %d endpoints", len(endpoints))

        return endpoint_dict

    def save_collected_data(self, endpoint_dict, filename=None):
        """
        Save the collected endpoint data to a JSON file using the parent class write_to_json method.

        Parameters:
            endpoint_dict (dict): The dictionary containing collected data from all endpoints.
            filename (str, optional): The filename to save to. If not provided, generates a default name.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not filename:
            fabric_suffix = f"_{self.fabric_name}" if self.fabric_name else ""
            filename = f"NDFC{fabric_suffix}_collected_data.json"

        try:
            self.write_to_json(endpoint_dict, filename)
            logger.info("Successfully saved collected data to: %s", filename)
            return True
        except Exception as e:
            logger.error("Failed to save collected data: %s", str(e))
            return False

    def _process_policies_endpoint_with_filtering(self, endpoint, endpoint_dict):
        """
        Process Policies endpoint by fetching all policies and filtering by discovered switch serial numbers.

        Parameters:
            endpoint (dict): The endpoint configuration containing name and endpoint URL.
            endpoint_dict (dict): The dictionary to store results in.
        """
        endpoint_name = endpoint["name"]
        endpoint_url = endpoint["endpoint"]

        # Initialize list for this endpoint if not exists
        if endpoint_name not in endpoint_dict:
            endpoint_dict[endpoint_name] = []

        logger.info(
            "Processing Policies endpoint with client-side filtering by serial numbers"
        )

        # First, check if we have Discovered_Switches data
        if "Discovered_Switches" not in endpoint_dict:
            logger.error(
                "Cannot process Policies endpoint: Discovered_Switches data not available"
            )
            logger.error(
                "Make sure Discovered_Switches endpoint is defined before Policies endpoint"
            )
            endpoint_dict[endpoint_name].append(
                {
                    "data": {},
                    "endpoint": endpoint_url,
                    "error": "Discovered_Switches data not available",
                }
            )
            return

        # Extract serial numbers from Discovered_Switches data
        serial_numbers = self._extract_serial_numbers_from_switches(
            endpoint_dict["Discovered_Switches"]
        )

        if not serial_numbers:
            logger.warning("No serial numbers found in Discovered_Switches data")
            endpoint_dict[endpoint_name].append(
                {
                    "data": {},
                    "endpoint": endpoint_url,
                    "error": "No serial numbers found in Discovered_Switches",
                }
            )
            return

        logger.info(
            "Found %d switches with serial numbers, fetching all policies for filtering",
            len(serial_numbers),
        )

        try:
            logger.debug("Fetching all policies from endpoint: %s", endpoint_url)

            # Make the API request using the parent class fetch_data method
            all_policies_data = self.fetch_data(endpoint_url)

            if all_policies_data is not None:
                logger.info("Successfully retrieved all policies data")

                # Filter policies based on discovered switch serial numbers
                filtered_policies = self._filter_policies_by_serial_numbers(
                    all_policies_data, serial_numbers
                )

                # Store the filtered results
                endpoint_dict[endpoint_name].append(
                    {
                        "data": filtered_policies,
                        "endpoint": endpoint_url,
                        "filtered_serial_numbers": serial_numbers,
                        "total_policies_received": len(all_policies_data)
                        if isinstance(all_policies_data, list)
                        else 1,
                        "filtered_policies_count": len(filtered_policies)
                        if isinstance(filtered_policies, list)
                        else 1,
                    }
                )

                logger.info(
                    "Policy filtering completed: %d policies filtered from %d total policies for %d switches",
                    len(filtered_policies)
                    if isinstance(filtered_policies, list)
                    else 1,
                    len(all_policies_data)
                    if isinstance(all_policies_data, list)
                    else 1,
                    len(serial_numbers),
                )

            else:
                logger.error("Failed to fetch policies data")
                endpoint_dict[endpoint_name].append(
                    {
                        "data": {},
                        "endpoint": endpoint_url,
                        "error": "Failed to fetch policies data",
                    }
                )

        except Exception as e:
            logger.error("Unexpected error fetching policies data: %s", str(e))
            endpoint_dict[endpoint_name].append(
                {"data": {}, "endpoint": endpoint_url, "error": str(e)}
            )

    def _filter_policies_by_serial_numbers(self, policies_data, serial_numbers):
        """
        Filter policies data to only include policies for switches with specified serial numbers.

        Parameters:
            policies_data (dict or list): The raw policies data from NDFC API.
            serial_numbers (list): List of serial numbers to filter by.

        Returns:
            list: Filtered list of policies that match the serial numbers.
        """
        logger.debug(
            "Filtering policies data for %d serial numbers", len(serial_numbers)
        )

        # Handle different response structures
        if isinstance(policies_data, dict):
            # Check for common NDFC response patterns
            if "data" in policies_data and isinstance(policies_data["data"], list):
                policies_list = policies_data["data"]
            elif isinstance(policies_data, dict):
                # Single policy object - convert to list for consistent processing
                policies_list = [policies_data]
            else:
                policies_list = []
        elif isinstance(policies_data, list):
            policies_list = policies_data
        else:
            logger.warning("Unexpected policies data format: %s", type(policies_data))
            return []

        filtered_policies = []
        serial_numbers_set = set(serial_numbers)  # Convert to set for faster lookup

        logger.debug("Processing %d policies for filtering", len(policies_list))

        for policy in policies_list:
            if isinstance(policy, dict) and "serialNumber" in policy:
                policy_serial = policy["serialNumber"]
                if policy_serial in serial_numbers_set:
                    filtered_policies.append(policy)
                    logger.debug(
                        "Including policy %s for serial number %s",
                        policy.get("policyId", "unknown"),
                        policy_serial,
                    )
                else:
                    logger.debug(
                        "Excluding policy %s for serial number %s (not in discovered switches)",
                        policy.get("policyId", "unknown"),
                        policy_serial,
                    )
            else:
                logger.debug("Policy missing serialNumber field: %s", policy)

        logger.info(
            "Policy filtering results: %d policies matched out of %d total policies",
            len(filtered_policies),
            len(policies_list),
        )

        return filtered_policies

    def _extract_serial_numbers_from_switches(self, discovered_switches_data):
        """
        Extract serial numbers from Discovered_Switches data.

        Parameters:
            discovered_switches_data (list): List of Discovered_Switches data entries.

        Returns:
            list: List of serial numbers found in the switches data.
        """
        serial_numbers = []

        logger.debug(
            "Extracting serial numbers from %d Discovered_Switches entries",
            len(discovered_switches_data),
        )

        for entry in discovered_switches_data:
            if not isinstance(entry, dict) or "data" not in entry:
                logger.warning("Invalid Discovered_Switches entry format: %s", entry)
                continue

            switches_data = entry["data"]

            # Handle different data structures
            if isinstance(switches_data, list):
                # Direct list of switches
                switches_list = switches_data
            elif isinstance(switches_data, dict) and "data" in switches_data:
                # Wrapped in data object
                switches_list = switches_data["data"]
            elif isinstance(switches_data, dict):
                # Single switch object
                switches_list = [switches_data]
            else:
                logger.warning(
                    "Unexpected switches data format: %s", type(switches_data)
                )
                continue

            # Extract serial numbers from each switch
            for switch in switches_list:
                if isinstance(switch, dict) and "serialNumber" in switch:
                    serial_number = switch["serialNumber"]
                    if serial_number and serial_number not in serial_numbers:
                        serial_numbers.append(serial_number)
                        logger.debug("Found serial number: %s", serial_number)
                else:
                    logger.debug("Switch entry missing serialNumber: %s", switch)

        logger.info(
            "Extracted %d unique serial numbers from discovered switches",
            len(serial_numbers),
        )
        return serial_numbers

    @staticmethod
    def get_id_value(item):
        """
        Attempts to get an identifier value from a dictionary.
        Common NDFC ID fields to check.

        Parameters:
            item (dict): The dictionary to get the identifier value from.

        Returns:
            str or None: The identifier value if it exists, None otherwise.
        """
        # Common NDFC identifier fields
        id_fields = ["id", "uuid", "fabricName", "name", "serialNumber", "switchDbId"]

        for field in id_fields:
            value = item.get(field)
            if value is not None:
                return str(value)

        return None
